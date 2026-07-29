"""The gate for this phase: can a bridge be found at all?

`bridges to` is the link kind for two unrelated areas turning out to touch. Its
whole value is in pairs that share no vocabulary — proofing dough and a polling
interval, alike because waiting is a thing in the world.

Before this, `context_for` drew candidates from an FTS5 search and the recency
window, and nothing else. The model only ever judges pairs it is shown, so such
a pair was presentable only while both entries were recent. After that the link
could never be proposed however good the model was: the feature was shipped,
prompted for, rendered with its own label, and unreachable.

The embedder here is a stand-in — a real one costs a key and a network — but it
stands in for the only property that matters: it maps text to a position by
*meaning* rather than by words. That is precisely what the retrieval path could
not do, and these tests fail without the change regardless of which embedder
supplies the vectors.
"""

from __future__ import annotations

import math

import pytest

from tilt.journal import Journal
from tilt.models import EntryCreate
from tilt.store import search
from tilt.store.index import Index, content_hash
from tilt.store.vectors import VectorStore

# Two subjects, written about with entirely disjoint vocabularies, that share
# one idea: the work is the waiting rather than the doing. A model that has read
# the world places them near each other. BM25 cannot, because there is not one
# word in common.
BAKING = "Proofing sourdough is mostly leaving it alone and deciding when to stop."
SCHEDULING = "The sweep costs one indexed query; its expense is the interval, not the action."
UNRELATED = "Attention discards most of what arrives before any of it reaches awareness."

# Enough baking entries to fill both windows the old candidate set drew from.
# Without them the journal is small enough that everything is a candidate and
# the test proves nothing — which is exactly what the first version of it did.
FILLER = [
    f"Sourdough note {n}: the starter wants a wetter feed and a warmer shelf "
    "through winter, and the crumb shows it."
    for n in range(20)
]

# Where a real embedder would put them: the two patient ones adjacent, the third
# somewhere else entirely, and the filler in its own region.
PLACES = {BAKING: (1.0, 0.10), SCHEDULING: (0.97, 0.24), UNRELATED: (-0.30, 0.95)}


class PlacedEmbedder:
    """Positions text by meaning, from a lookup rather than a model."""

    signature = "test/placed/2"
    dims = 2

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Anything not placed by hand is filler, parked far from all three.
        return [_unit(PLACES.get(text.strip(), (-0.9, -0.4))) for text in texts]


def _unit(pair: tuple[float, float]) -> list[float]:
    norm = math.hypot(*pair)
    return [pair[0] / norm, pair[1] / norm]


@pytest.fixture
def wired(tmp_path) -> Journal:
    """A journal with vectors, and every entry embedded."""
    index = Index(tmp_path / "index.db")
    vectors = VectorStore(tmp_path / "vectors.db")
    embedder = PlacedEmbedder()
    journal = Journal(tmp_path / "journal", index, vectors, embedder)

    # Order matters. SCHEDULING is written first so it falls out of the recency
    # window, and the filler is lexically nearer to BAKING than SCHEDULING is,
    # so it fills the lexical window too. Between them they reproduce the real
    # condition: an old entry about something else, in a journal with enough in
    # it that neither of the old candidate sources can reach it.
    for body in (SCHEDULING, UNRELATED, *FILLER, BAKING):
        entry = journal.create(EntryCreate(body=body))
        vectors.put(
            entry.id,
            embedder.signature,
            content_hash(entry.body),
            embedder.embed([entry.body])[0],
        )
    yield journal
    vectors.close()
    index.close()


def _find(journal: Journal, body: str) -> str:
    return next(e.id for e in journal.index.all_entries() if e.body == body)


# ------------------------------------------------------------------- the gate


def test_lexical_search_cannot_find_the_partner(wired: Journal) -> None:
    """The premise. If BM25 could find this pair the rest proves nothing.

    Calls the lexical ranker directly rather than `journal.search`, which now
    fuses in the vector list and would find it for the wrong reason."""
    hits = [e.body for e in search.search(wired.index, BAKING, limit=12)]
    assert BAKING in hits, "the entry can find itself, so the search works"
    assert SCHEDULING not in hits, "and cannot find its bridge partner"


def test_recency_cannot_find_it_either(wired: Journal) -> None:
    """The other half of the premise. The two old sources of candidates were
    shared words and an adjacent timestamp, and this pair has neither."""
    recent = [e.body for e in wired.index.recent_bodies(limit=12)]
    assert SCHEDULING not in recent


def test_the_bridge_partner_reaches_the_candidate_set(wired: Journal) -> None:
    """The repair, stated as the failure it fixes: before this, the connector
    was never shown this pair and so could never propose the link."""
    baking = _find(wired, BAKING)
    candidates = [e.body for e in wired.context_for(baking)]
    assert SCHEDULING in candidates


def test_it_is_the_vector_path_that_supplies_it(wired: Journal) -> None:
    """Not recency wearing a disguise. `neighbours` is the only source of
    candidates that does not require shared words or an adjacent timestamp."""
    baking = _find(wired, BAKING)
    assert [e.body for e in wired.neighbours(baking)] == [SCHEDULING]


def test_an_unrelated_entry_is_not_dragged_in_with_it(wired: Journal) -> None:
    """A nearest-neighbour query always returns something. The floor is what
    stops the third-nearest entry becoming a paid-for proposal about nothing."""
    baking = _find(wired, BAKING)
    assert UNRELATED not in [e.body for e in wired.neighbours(baking)]


# ------------------------------------------------------- degrading without a key


def test_without_an_embedder_nothing_breaks(tmp_path) -> None:
    """No key means no vector ranker, not an error. The candidate set is the
    one it was before — narrower, and working."""
    index = Index(tmp_path / "index.db")
    journal = Journal(tmp_path / "journal", index)
    first = journal.create(EntryCreate(body=BAKING))
    journal.create(EntryCreate(body=SCHEDULING))

    assert journal.neighbours(first.id) == []
    assert journal.context_for(first.id) is not None
    assert journal.search("sourdough")
    index.close()


def test_a_journal_with_a_store_but_no_vectors_yet_is_fine(tmp_path) -> None:
    """The window between writing an entry and the hourly job embedding it."""
    index = Index(tmp_path / "index.db")
    vectors = VectorStore(tmp_path / "vectors.db")
    journal = Journal(tmp_path / "journal", index, vectors, PlacedEmbedder())
    entry = journal.create(EntryCreate(body=BAKING))

    assert journal.neighbours(entry.id) == []
    vectors.close()
    index.close()
