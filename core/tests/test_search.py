from __future__ import annotations

from tilt.models import Entry, utcnow
from tilt.store.search import reciprocal_rank_fusion, sanitize_query


def _entry(entry_id: str) -> Entry:
    now = utcnow()
    return Entry(id=entry_id, created=now, updated=now, body=entry_id)


def test_sanitize_strips_fts_operators() -> None:
    """Hyphens and stray quotes are FTS5 syntax and must be neutralised.
    Apostrophes need no escaping once each term is double-quoted."""
    assert (
        sanitize_query('it\'s well-formed "quoted"')
        == '"it\'s" OR "well" OR "formed" OR "quoted"'
    )


def test_sanitize_empty_input_yields_empty_query() -> None:
    assert sanitize_query("   -- ^^ ") == ""


def test_fusion_rewards_agreement_between_rankers() -> None:
    """An item ranked highly by both rankers must beat one ranked first by
    only a single ranker."""
    a, b, c = _entry("a"), _entry("b"), _entry("c")
    fused = reciprocal_rank_fusion([c, a, b], [a, b, c])
    assert fused[0].id == "a"


def test_fusion_deduplicates() -> None:
    a = _entry("a")
    assert [e.id for e in reciprocal_rank_fusion([a], [a], [a])] == ["a"]


def test_fusion_respects_limit() -> None:
    entries = [_entry(str(i)) for i in range(10)]
    assert len(reciprocal_rank_fusion(entries, limit=3)) == 3


def test_fusion_of_nothing_is_empty() -> None:
    assert reciprocal_rank_fusion([], []) == []
