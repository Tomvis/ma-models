"""Tests for MediaItemMetadata.update() merge behavior and CriticalReception filtering."""

from music_assistant_models.media_items.metadata import (
    CriticalReception,
    MediaItemMetadata,
    ReviewSourceEntry,
)


def _cr(*entries: ReviewSourceEntry, amg_dr: float | None = None) -> CriticalReception:
    return CriticalReception(amg_dr=amg_dr, sources=list(entries) or None)


def test_critical_reception_post_init_drops_blank_and_none_sources() -> None:
    """Blank / literal-'None' source rows are dropped so they can't poison filters."""
    cr = CriticalReception(
        sources=[
            ReviewSourceEntry(source="AMG", rating=4.0),
            ReviewSourceEntry(source=""),
            ReviewSourceEntry(source="None"),
        ]
    )
    assert cr.sources is not None
    assert [s.source for s in cr.sources] == ["AMG"]


def test_review_source_entry_null_source_coerced_to_none_string_is_dropped() -> None:
    """A wire-sent null source deserializes to the literal 'None' and is filtered out."""
    entry = ReviewSourceEntry.from_dict({"source": None, "rating": 4.0})
    assert entry.source == "None"
    cr = CriticalReception(sources=[entry])
    assert cr.sources is None


def test_update_unions_sources_by_name() -> None:
    """A probe that only carries TPS keeps the stored AMG entry (additive, not replace)."""
    stored = MediaItemMetadata(critical_reception=_cr(ReviewSourceEntry(source="AMG", rating=4.0)))
    incoming = MediaItemMetadata(
        critical_reception=_cr(ReviewSourceEntry(source="TPS", rating=8.0))
    )
    stored.update(incoming)
    assert stored.critical_reception is not None
    sources = stored.critical_reception.sources or []
    assert {s.source for s in sources} == {"AMG", "TPS"}


def test_update_incoming_source_wins_for_same_name() -> None:
    """For a source present on both sides, the incoming entry replaces the stored one."""
    stored = MediaItemMetadata(critical_reception=_cr(ReviewSourceEntry(source="AMG", rating=4.0)))
    incoming = MediaItemMetadata(
        critical_reception=_cr(ReviewSourceEntry(source="AMG", rating=5.0))
    )
    stored.update(incoming)
    assert stored.critical_reception is not None
    sources = stored.critical_reception.sources or []
    assert len(sources) == 1
    assert sources[0].rating == 5.0


def test_update_amg_dr_falls_back_to_stored_when_incoming_none() -> None:
    """An amg_dr-only-absent probe keeps the stored amg_dr."""
    stored = MediaItemMetadata(critical_reception=_cr(amg_dr=8.0))
    incoming = MediaItemMetadata(
        critical_reception=_cr(ReviewSourceEntry(source="AMG", rating=4.0))
    )
    stored.update(incoming)
    assert stored.critical_reception is not None
    assert stored.critical_reception.amg_dr == 8.0


def test_update_dynamic_range_overwrites_stale_value() -> None:
    """A re-measured dynamic_range lands even when a non-None value is already stored."""
    stored = MediaItemMetadata(dynamic_range=11.5)
    incoming = MediaItemMetadata(dynamic_range=12.0)
    stored.update(incoming)
    assert stored.dynamic_range == 12.0


def test_update_dynamic_range_keeps_stored_when_incoming_none() -> None:
    """A merge that carries no dynamic_range leaves the stored value intact."""
    stored = MediaItemMetadata(dynamic_range=11.5)
    incoming = MediaItemMetadata(popularity=10)
    stored.update(incoming)
    assert stored.dynamic_range == 11.5


def test_update_dynamic_range_zero_overwrites_stored_value() -> None:
    """A measured DR of exactly 0.0 is a real reading and must replace a stale one."""
    stored = MediaItemMetadata(dynamic_range=11.5)
    incoming = MediaItemMetadata(dynamic_range=0.0)
    stored.update(incoming)
    assert stored.dynamic_range == 0.0


def test_update_popularity_zero_does_not_overwrite_stored_value() -> None:
    """Unlike dynamic_range, a falsy popularity stays a no-op against a stored value."""
    stored = MediaItemMetadata(popularity=42)
    incoming = MediaItemMetadata(popularity=0)
    stored.update(incoming)
    assert stored.popularity == 42


def test_update_popularity_zero_fills_empty_gap() -> None:
    """A zero popularity still lands when nothing is stored yet (gap-fill arm)."""
    stored = MediaItemMetadata()
    incoming = MediaItemMetadata(popularity=0)
    stored.update(incoming)
    assert stored.popularity == 0


def test_update_takes_incoming_review_text_per_source() -> None:
    """A re-probe carrying a source's review text replaces that source's stored entry."""
    stored = MediaItemMetadata(critical_reception=_cr(ReviewSourceEntry(source="AMG", rating=4.0)))
    incoming = MediaItemMetadata(
        critical_reception=_cr(
            ReviewSourceEntry(source="AMG", rating=4.0, review="Riffs.\n\nMore.")
        )
    )
    stored.update(incoming)
    assert stored.critical_reception is not None
    assert stored.critical_reception.sources is not None
    assert stored.critical_reception.sources[0].review == "Riffs.\n\nMore."
    assert ReviewSourceEntry.from_dict({"source": "TPS", "review": "Prog."}).review == "Prog."
