"""Models for MediaItem Metadata."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from mashumaro import DataClassDictMixin

from music_assistant_models.enums import ArtistEntityType, ImageType, LinkType
from music_assistant_models.helpers import create_safe_string, create_sort_name, merge_lists
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
            return NotImplemented
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
            return NotImplemented
        return self.__hash__() == other.__hash__()

    def __post_serialize__(self, d: dict[str, Any]) -> dict[str, Any]:
        """Inject `proxy_id` when a resolver is set on the current context."""
        # A proxy_id is filled regardless of `remotely_accessible`: even when a
        # client can fetch the image directly, it still needs the proxy to obtain
        # a resized/reformatted thumbnail (`?size=...&fmt=...`).
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
class MediaItemTranscriptCue(DataClassDictMixin):
    """Model for a single timed cue of a MediaItem's transcript."""

    start: float  # start position in seconds
    end: float | None = None  # end position in seconds if known
    text: str  # spoken text of this cue
    speaker: str | None = None  # speaker name/label if the source identifies one


@dataclass(frozen=True, kw_only=True)
class MediaItemCollection(DataClassDictMixin):
    """
    Model for a MediaItem's collection.

    A book can be part of one or multiple collections. The backend will collect all books belonging
    to a series, the provider only needs use this model and add it as often as needed to the
    audiobooks collections field. One may optionally specify a certain sequence (e.g. for a book
    series), and the backend will then sort accordingly. Otherwise the collection entries will just
    be returned alphabetically.
    """

    title: str
    # sequence is used for sorting
    # we will first sort by number, and then alphabetically
    sequence: float | str | None = None

    def __hash__(self) -> int:
        """Return custom hash."""
        return hash(self.title)

    def __post_serialize__(self, d: dict[str, Any]) -> dict[str, Any]:
        """Add search strings."""
        d["search_title"] = create_safe_string(self.title, lowercase=True, replace_space=True)
        d["search_sort_title"] = create_safe_string(
            create_sort_name(self.title), lowercase=True, replace_space=True
        )
        return d


@dataclass(kw_only=True)
class AudioMetadata(DataClassDictMixin):
    """Model for audio-analysis-derived metadata of a track."""

    bpm: float | None = None  # beats per minute
    musical_key: str | None = None  # pitch class plus mode, e.g. "F# minor"


@dataclass(frozen=True, kw_only=True)
class LifeSpan(DataClassDictMixin):
    """Life span dates for an artist (person or group)."""

    begin: str | None = None  # ISO date (YYYY-MM-DD) or partial (YYYY-MM or YYYY)
    end: str | None = None  # ISO date (YYYY-MM-DD) or partial (YYYY-MM or YYYY)
    ended: bool = False  # whether the artist is deceased or the group has disbanded


@dataclass(frozen=True, kw_only=True)
class ReviewLink(DataClassDictMixin):
    """One labeled post link for a critical-reception source (TAG_SCHEMA_VERSION 3.3.0+).

    One entry per post (not per honor): an album appearing in several writers' year-end
    lists yields several entries that share a ``label`` but differ by ``url``. ``label``
    mirrors a value from the source's ``accolades`` ("Review", "Album of the Year (2024)",
    "Score Revised", …). Frozen as an immutable value object so it compares (and hashes)
    by value — review-data comparisons that snapshot a source's links rely on that.
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


def _merge_review_sources(
    cur: list[ReviewSourceEntry] | None,
    new: list[ReviewSourceEntry] | None,
) -> list[ReviewSourceEntry] | None:
    """Union two critical-reception source lists by source name.

    Keeps stored sources that the incoming list does not mention and lets the
    incoming entry win for a source present on both sides. Either side being
    empty/None falls back to the other, so a probe that only carries one source
    (e.g. TPS) no longer drops the others (e.g. a stored AMG entry).
    """
    # Always hand back a fresh list: the merged CriticalReception is stored on a
    # different MediaItemMetadata than the inputs, and returning an input list by
    # reference would alias the two (entries are mutated in place downstream, e.g.
    # by the server's normalize_review_entries).
    if not new:
        return list(cur) if cur else cur
    if not cur:
        return list(new)
    merged: dict[str, ReviewSourceEntry] = {s.source: s for s in cur}
    for entry in new:
        merged[entry.source] = entry
    return list(merged.values())


@dataclass(kw_only=True)
class MediaItemMetadata(DataClassDictMixin):
    """Model for a MediaItem's metadata."""

    description: str | None = None
    # ISO 639-1 language code for `description`
    description_language: str | None = None
    # Artist-specific metadata (applicable to Artist media type only)
    life_span: LifeSpan | None = None  # birth/death for persons, founded/disbanded for groups
    artist_entity_type: ArtistEntityType | None = None  # MusicBrainz artist entity type
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
    # transcript of the spoken content, most commonly used for podcast episodes
    transcript: str | None = None
    # transcript split into timed cues, sorted by start position
    transcript_cues: list[MediaItemTranscriptCue] | None = None
    # whether a transcript is available, set to None if the provider cannot tell
    has_transcript: bool | None = None
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
    # Make the item part of one or multiple collections. Refer to the docstring for
    # MediaItemCollection.
    collections: UniqueList[MediaItemCollection] | None = None
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
    # last_musicbrainz_lookup: timestamp the item was last looked up on MusicBrainz,
    # set on every attempt, so an item MusicBrainz does not know is not retried endlessly
    last_musicbrainz_lookup: int | None = None

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
            elif fld.name == "dynamic_range":
                # dynamic_range is a measured scalar: a re-probe/refresh should land,
                # so always overwrite with the incoming value rather than only filling
                # a None gap (otherwise a corrected DR could never replace a stale one).
                # Deliberately gated on "not None" (already guaranteed above) instead of
                # truthiness, unlike the fields below: DR 0.0 is a legitimate reading for
                # fully-clipped audio, whereas a 0 popularity / 0 last_refresh is a
                # not-measured sentinel that must not clobber a stored value.
                setattr(self, fld.name, new_val)
            elif new_val and fld.name in (
                "popularity",
                "last_refresh",
                "last_musicbrainz_lookup",
            ):
                # some fields are always allowed to be overwritten
                # (such as popularity and the refresh/lookup timestamps)
                setattr(self, fld.name, new_val)
            elif fld.name == "critical_reception" and isinstance(cur_val, CriticalReception):
                # CR is a structured nested field: deep-merge rather than wholesale
                # replace, so a partial probe (e.g. amg_dr only, sources unset) can't
                # silently drop the existing data. amg_dr prefers the incoming value when
                # populated and falls back to the stored one; sources are unioned per
                # source name (incoming entry wins for a source present on both sides,
                # stored-only sources are kept) so a probe that surfaces a new source
                # without re-emitting the others is additive instead of destructive.
                # (If nothing is stored yet, the generic fallback below applies.)
                setattr(
                    self,
                    fld.name,
                    CriticalReception(
                        amg_dr=new_val.amg_dr if new_val.amg_dr is not None else cur_val.amg_dr,
                        sources=_merge_review_sources(cur_val.sources, new_val.sources),
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
