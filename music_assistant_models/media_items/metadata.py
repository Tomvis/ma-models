"""Models for MediaItem Metadata."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from mashumaro import DataClassDictMixin

from music_assistant_models.enums import ImageType, LinkType
from music_assistant_models.helpers import merge_lists
from music_assistant_models.unique_list import UniqueList

# ContextVar set by the Music Assistant server during outbound API serialization.
# When set, MediaItemImage.__post_serialize__ uses the resolver to fill `proxy_id`
# on the serialized dict, so clients can build the imageproxy URL by appending
# the id to their own connection's base URL — no need to construct the long
# legacy `/imageproxy?provider=…&path=…` form themselves. The resolver receives
# (provider, path) and must return an opaque, server-defined image id that is
# safe to embed directly as a single URL path segment (URL-safe, no `/`, `?`,
# `#`, or whitespace), so clients can build `<api_base>/imageproxy/<proxy_id>`
# without any extra escaping.
IMAGE_PROXY_ID_RESOLVER: ContextVar[Callable[[str, str], str] | None] = ContextVar(
    "image_proxy_id_resolver", default=None
)


@dataclass(frozen=True, kw_only=True)
class MediaItemLink(DataClassDictMixin):
    """Model for a link."""

    type: LinkType
    url: str

    def __hash__(self) -> int:
        """Return custom hash."""
        return hash(self.type)

    def __eq__(self, other: object) -> bool:
        """Check equality of two items."""
        if not isinstance(other, MediaItemLink):
            return False
        return self.url == other.url


@dataclass(frozen=True, kw_only=True)
class MediaItemImage(DataClassDictMixin):
    """Model for a image."""

    type: ImageType
    path: str
    provider: str  # provider lookup key (only use instance id for fileproviders)
    remotely_accessible: bool = False  # url that is accessible from anywhere
    # Opaque server-side imageproxy id. Populated only by the MA server during
    # outbound API serialization (via __post_serialize__ + IMAGE_PROXY_ID_RESOLVER).
    # Clients fetch the image at `<api_base>/imageproxy/<proxy_id>?size=...&fmt=...`.
    proxy_id: str | None = None

    def __hash__(self) -> int:
        """Return custom hash."""
        return hash((self.type.value, self.provider, self.path))

    def __eq__(self, other: object) -> bool:
        """Check equality of two items."""
        if not isinstance(other, MediaItemImage):
            return False
        return self.__hash__() == other.__hash__()

    def __post_serialize__(self, d: dict[str, Any]) -> dict[str, Any]:
        """Inject `proxy_id` when a resolver is set on the current context."""
        if self.remotely_accessible:
            return d
        # only inject when proxy_id was not already provided so that values
        # round-tripped via from_dict (or set explicitly by the caller) survive
        if d.get("proxy_id") is not None:
            return d
        resolver = IMAGE_PROXY_ID_RESOLVER.get()
        if resolver is not None:
            d["proxy_id"] = resolver(self.provider, self.path)
        return d


@dataclass(frozen=True, kw_only=True)
class MediaItemPalette(DataClassDictMixin):
    """Color palette derived from a MediaItem's artwork. Mirrors the Sendspin color@v1 spec."""

    background_dark: tuple[int, int, int] | None = None
    background_light: tuple[int, int, int] | None = None
    primary: tuple[int, int, int] | None = None
    accent: tuple[int, int, int] | None = None
    on_dark: tuple[int, int, int] | None = None
    on_light: tuple[int, int, int] | None = None


@dataclass(frozen=True, kw_only=True)
class MediaItemChapter(DataClassDictMixin):
    """Model for a MediaItem's chapter/bookmark."""

    position: int  # sort position/number
    name: str  # friendly name
    start: float  # start position in seconds
    end: float | None = None  # start position in seconds if known

    @property
    def duration(self) -> float:
        """Return duration of chapter."""
        return self.end - self.start if self.end else 0

    def __hash__(self) -> int:
        """Return custom hash."""
        return hash(self.position)


@dataclass(frozen=True, kw_only=True)
class ReviewLink(DataClassDictMixin):
    """One labeled post link for a critical-reception source (TAG_SCHEMA_VERSION 3.3.0+).

    One entry per post (not per honor): an album appearing in several writers' year-end
    lists yields several entries that share a ``label`` but differ by ``url``. ``label``
    mirrors a value from the source's ``accolades`` ("Review", "Album of the Year (2024)",
    "Score Revised", …). Frozen as an immutable value object; the richness-merge helpers
    compare links by value via the per-source signature tuple.
    """

    label: str = ""
    url: str = ""


@dataclass(kw_only=True)
class ReviewSourceEntry(DataClassDictMixin):
    """One source of critical reception for an album (AMG, TPS, …).

    Carries the source's rating on its native scale (5pt for AMG, 10pt for TPS),
    plus optional editorial accolades and post links pulled from custom file tags.
    """

    # short identifier, e.g. "AMG" or "TPS". Defaults to "" so a wire payload with
    # a missing/blank/null source still deserializes (mashumaro would otherwise raise
    # MissingField); CriticalReception.__post_init__ drops such unusable entries.
    source: str = ""
    rating: float | None = None
    # favorite: list-pick / personal-pick flag in lieu of a numeric rating
    favorite: bool | None = None
    # accolades: editorial honors as human-readable display strings, each appearing
    # once with any date inlined, e.g. ["Review", "Album of the Year (2024)",
    # "Record of the Month (Sep 2024)"] (TAG_SCHEMA_VERSION 3.2.0+).
    accolades: list[str] | None = None
    # links: one labeled post URL per post (TAG_SCHEMA_VERSION 3.3.0+). Each ``label``
    # mirrors an ``accolades`` value, but several links can share a label (e.g. an
    # Album of the Year honor appearing in multiple writers' year-end lists).
    links: list[ReviewLink] | None = None
    # authors: contributing reviewer/list-pick author names
    authors: list[str] | None = None

    # DEPRECATED (TAG_SCHEMA_VERSION <= 3.1.1): the separate review-kind / award-label
    # lists, superseded by the merged ``accolades`` field above. Still accepted on the
    # wire so pre-3.2.0 senders deserialize during the transition; the server folds them
    # into ``accolades`` on ingest. Remove once all senders/files are re-tagged.
    types: list[str] | None = None
    labels: list[str] | None = None
    # DEPRECATED (TAG_SCHEMA_VERSION <= 3.2.x): the single canonical review URL,
    # superseded by ``links``. Folded into a single {"Review", url} link on ingest.
    review_url: str | None = None


@dataclass(kw_only=True)
class CriticalReception(DataClassDictMixin):
    """Aggregated critical-reception metadata for a media item (album).

    Note: the canonical Dynamic Range value lives on ``MediaItemMetadata.dynamic_range``
    (measured from the audio). ``amg_dr`` here is the secondary, AMG-review-reported DR
    kept alongside the rest of AMG's review-derived data.
    """

    # AMG-reported album DR, parsed from AMG's review metadata block. AMG-only —
    # TPS doesn't extract DR. Not authoritative for filter/sort; see
    # MediaItemMetadata.dynamic_range for the measured value used everywhere else.
    amg_dr: float | None = None
    sources: list[ReviewSourceEntry] | None = None

    def __post_init__(self) -> None:
        """Drop blank/None-sourced entries instead of failing the whole payload.

        Downstream filters key on the source string, so an entry with an empty or
        null source is unusable. mashumaro coerces a wire-sent ``null`` (or a missing
        key) into the literal string "None" before we see it, so filter that too.
        Dropping the bad row keeps deserialization total — a single corrupt entry
        can't poison the enclosing Album/Track — matching the library's forward-
        compatibility contract (cf. the enum ``_missing_`` convention).
        """
        if self.sources:
            self.sources = [s for s in self.sources if s.source and s.source != "None"] or None


@dataclass(kw_only=True)
class MediaItemMetadata(DataClassDictMixin):
    """Model for a MediaItem's metadata."""

    description: str | None = None
    # ISO 639-1 language code for `description`
    description_language: str | None = None
    review: str | None = None
    explicit: bool | None = None
    # NOTE: images is a list of available images, sorted by preference
    images: UniqueList[MediaItemImage] | None = None
    grouping: str | None = None
    genres: set[str] | None = None
    mood: str | None = None
    style: str | None = None
    copyright: str | None = None
    lyrics: str | None = None  # tracks only
    lrc_lyrics: str | None = None  # tracks only
    label: str | None = None
    links: set[MediaItemLink] | None = None
    performers: set[str] | None = None
    preview: str | None = None
    popularity: int | None = None
    release_date: datetime | None = None
    languages: UniqueList[str] | None = None
    # chapters is a list of available chapters, sorted by position
    # most commonly used for audiobooks and podcast episodes
    chapters: list[MediaItemChapter] | None = None
    # critical_reception: per-source ratings/accolades (album scope, review-derived)
    critical_reception: CriticalReception | None = None
    # Dynamic Range (foobar2000 DR Meter convention). Measured from the audio file:
    #   - on Album: the album-scope mean of measured track DRs (rounded)
    #   - on Track: the per-track DR14 value
    # This is the canonical DR used for filtering and sorting. AMG's review-reported
    # DR is exposed separately as critical_reception.amg_dr.
    dynamic_range: float | None = None
    # last_refresh: timestamp the (full) metadata was last collected
    last_refresh: int | None = None

    def update(
        self,
        new_values: MediaItemMetadata,
    ) -> MediaItemMetadata:
        """Update metadata (in-place) with new values."""
        if not new_values:
            return self
        # description paired with description_language: overwrite on language change,
        # otherwise fill-the-gap (preserves higher-priority provider's bio)
        if new_values.description is not None:
            new_lang = new_values.description_language
            lang_changed = new_lang is not None and new_lang != self.description_language
            if lang_changed or self.description is None:
                self.description = new_values.description
                self.description_language = new_lang
        for fld in fields(self):
            if fld.name in ("description", "description_language"):
                continue
            new_val = getattr(new_values, fld.name)
            if new_val is None:
                continue
            cur_val = getattr(self, fld.name)
            if isinstance(cur_val, list) and isinstance(new_val, list):
                new_val = UniqueList(merge_lists(cur_val, new_val))
                setattr(self, fld.name, new_val)
            elif isinstance(cur_val, set) and isinstance(new_val, set | list | tuple):
                cur_val.update(new_val)
            elif new_val and fld.name in (
                "popularity",
                "last_refresh",
            ):
                # some fields are always allowed to be overwritten
                # (such as popularity and last_refresh)
                setattr(self, fld.name, new_val)
            elif fld.name == "critical_reception" and isinstance(cur_val, CriticalReception):
                # CR is a structured nested field: deep-merge rather than wholesale
                # replace, so a partial probe (e.g. amg_dr only, sources unset) can't
                # silently drop the existing sources list. Per-field rule: prefer the
                # incoming value when populated, fall back to the stored one.
                # (If nothing is stored yet, the generic fallback below applies.)
                setattr(
                    self,
                    fld.name,
                    CriticalReception(
                        amg_dr=new_val.amg_dr if new_val.amg_dr is not None else cur_val.amg_dr,
                        sources=new_val.sources or cur_val.sources,
                    ),
                )
            elif cur_val is None:
                setattr(self, fld.name, new_val)
        return self

    def add_image(self, image: MediaItemImage) -> None:
        """Add an image to the list."""
        if not self.images:
            self.images = UniqueList()
        self.images.append(image)
