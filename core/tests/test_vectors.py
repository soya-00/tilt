"""The vector store, and the promises that justify it being a separate file.

The store exists because `index.db` is advertised as free to delete and vectors
are not free to replace. Most of what is tested here is that separation holding.
"""

from __future__ import annotations

import math

import pytest

from tilt.store.vectors import VectorStore, pack, unpack

SIG = "gemini/test/4"


@pytest.fixture
def store(tmp_path) -> VectorStore:
    s = VectorStore(tmp_path / "vectors.db")
    yield s
    s.close()


def unit(*values: float) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


# ----------------------------------------------------------------- round trip


def test_a_vector_survives_the_round_trip() -> None:
    vector = [0.5, -0.25, 0.125, 0.0]
    assert unpack(pack(vector)) == pytest.approx(vector)


def test_storing_the_same_entry_twice_replaces_rather_than_duplicates(store) -> None:
    store.put("A", SIG, "hash-1", unit(1, 0, 0, 0))
    store.put("A", SIG, "hash-2", unit(0, 1, 0, 0))
    assert store.count(SIG) == 1
    assert store.fresh(SIG) == {"A": "hash-2"}


# ------------------------------------------------------------------- staleness


def test_an_unchanged_entry_is_never_paid_for_twice(store) -> None:
    """`fresh` is what the job compares against the index's own hash. An entry
    whose text has not moved must not come back as pending."""
    store.put("A", SIG, "hash-1", unit(1, 0, 0, 0))
    assert store.fresh(SIG)["A"] == "hash-1"


def test_a_deleted_entry_takes_its_vector_with_it(store) -> None:
    # Otherwise it keeps surfacing as a neighbour of entries that still exist.
    store.put("A", SIG, "h", unit(1, 0, 0, 0))
    store.forget("A")
    assert store.count(SIG) == 0


# ------------------------------------------------------------------- neighbours


def test_nearest_ranks_by_cosine_and_excludes_the_query(store) -> None:
    store.put("query", SIG, "h", unit(1, 0, 0, 0))
    store.put("near", SIG, "h", unit(0.9, 0.1, 0, 0))
    store.put("far", SIG, "h", unit(0, 0, 1, 0))

    found = store.nearest(unit(1, 0, 0, 0), SIG, limit=5, exclude="query")
    assert [eid for eid, _ in found] == ["near", "far"]


def test_the_floor_refuses_a_neighbour_that_is_merely_the_closest(store) -> None:
    """A nearest-neighbour query always returns something. On a journal about
    one subject the tenth-nearest entry may be unrelated, and handing that to
    the connector spends a model call on a pair with nothing between them."""
    store.put("unrelated", SIG, "h", unit(0, 0, 1, 0))
    assert store.nearest(unit(1, 0, 0, 0), SIG, floor=0.55) == []


def test_nearest_over_an_empty_store_is_empty_rather_than_an_error(store) -> None:
    assert store.nearest(unit(1, 0, 0, 0), SIG) == []


# -------------------------------------------------------------- signatures


def test_vectors_from_another_embedder_are_never_returned(store) -> None:
    """Cosine between vectors from two models is a number with no meaning, and
    the failure would look like bad suggestions rather than like a bug."""
    store.put("mine", SIG, "h", unit(1, 0, 0, 0))
    store.put("theirs", "other/model/4", "h", unit(1, 0, 0, 0))

    found = store.nearest(unit(1, 0, 0, 0), SIG, limit=10)
    assert [eid for eid, _ in found] == ["mine"]


def test_a_width_change_cannot_corrupt_a_comparison(store) -> None:
    """Two widths under one signature should be impossible, but a mismatched
    row must be skipped rather than raise from inside a search box."""
    store.put("wide", SIG, "h", unit(1, 0, 0, 0))
    store._conn.execute(
        "INSERT INTO vectors (entry_id, signature, content_hash, dims, vector)"
        " VALUES (?,?,?,?,?)",
        ("narrow", SIG, "h", 2, pack([1.0, 0.0])),
    )
    found = store.nearest(unit(1, 0, 0, 0), SIG, limit=10)
    assert [eid for eid, _ in found] == ["wide"]


def test_changing_model_discards_the_old_vectors(store) -> None:
    store.put("A", SIG, "h", unit(1, 0, 0, 0))
    store.put("B", SIG, "h", unit(0, 1, 0, 0))
    assert store.drop_signature(SIG) == 2
    assert store.count(SIG) == 0


# ------------------------------------------------- the reason for two files


def test_vectors_survive_deleting_the_index(tmp_path) -> None:
    """The whole argument for a second file.

    `index.db` is advertised as free to delete and rebuild from Markdown.
    Vectors were bought from a hosted model, so if they lived there the app
    would be attaching a bill to an operation it calls costless — and sooner or
    later someone deletes the index to fix something unrelated.
    """
    from tilt.journal import Journal
    from tilt.models import EntryCreate
    from tilt.store.index import Index, content_hash

    index = Index(tmp_path / "index.db")
    store = VectorStore(tmp_path / "vectors.db")
    journal = Journal(tmp_path / "journal", index, store)
    entry = journal.create(EntryCreate(body="Attention is a budget."))
    store.put(entry.id, SIG, content_hash(entry.body), unit(1, 0, 0, 0))

    index.close()
    (tmp_path / "index.db").unlink()

    rebuilt = Index(tmp_path / "index.db")
    assert Journal(tmp_path / "journal", rebuilt, store).rebuild() == 1
    assert store.fresh(SIG) == {entry.id: content_hash(entry.body)}, (
        "rebuilding the free cache must not cost the expensive one"
    )
    rebuilt.close()
    store.close()


def test_deleting_an_entry_takes_its_vector_too(tmp_path) -> None:
    """The other direction: the store must not accumulate vectors for thoughts
    that no longer exist, or they keep surfacing as neighbours."""
    from tilt.journal import Journal
    from tilt.models import EntryCreate
    from tilt.store.index import Index, content_hash

    index = Index(tmp_path / "index.db")
    store = VectorStore(tmp_path / "vectors.db")
    journal = Journal(tmp_path / "journal", index, store)
    entry = journal.create(EntryCreate(body="A thought."))
    store.put(entry.id, SIG, content_hash(entry.body), unit(1, 0, 0, 0))

    journal.delete(entry.id)
    assert store.count(SIG) == 0
    store.close()
    index.close()
