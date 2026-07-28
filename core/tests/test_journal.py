from __future__ import annotations

from tilt.journal import Journal
from tilt.models import EntryCreate, EntryKind, EntryUpdate, ReplyKind


def test_create_returns_entry_and_indexes_it(journal: Journal) -> None:
    entry = journal.create(EntryCreate(body="  Attention is a filter, not a spotlight.  "))
    assert entry.body == "Attention is a filter, not a spotlight."
    assert journal.get(entry.id) is not None


def test_stream_is_newest_first_and_excludes_replies(journal: Journal) -> None:
    first = journal.create(EntryCreate(body="First thought."))
    second = journal.create(EntryCreate(body="Second thought."))
    journal.add_reply(first.id, "A reflection.", ReplyKind.REFLECTION)

    stream = journal.stream()
    assert [t.entry.id for t in stream] == [second.id, first.id]

    threads = {t.entry.id: t for t in stream}
    assert len(threads[first.id].replies) == 1
    assert threads[first.id].replies[0].kind is EntryKind.REPLY


def test_update_changes_body_and_bumps_timestamp(journal: Journal) -> None:
    entry = journal.create(EntryCreate(body="Original."))
    updated = journal.update(entry.id, EntryUpdate(body="Revised."))

    assert updated is not None
    assert updated.body == "Revised."
    assert updated.updated >= entry.updated
    assert journal.get(entry.id).body == "Revised."


def test_delete_cascades_to_replies(journal: Journal) -> None:
    entry = journal.create(EntryCreate(body="A thought worth reflecting on."))
    reply = journal.add_reply(entry.id, "The reflection.", ReplyKind.REFLECTION)

    assert journal.delete(entry.id) is True
    assert journal.get(entry.id) is None
    assert journal.get(reply.id) is None, "replies must not outlive their parent"


def test_delete_removes_the_file_from_disk(journal: Journal) -> None:
    entry = journal.create(EntryCreate(body="Ephemeral."))
    path = journal.index.path_of(entry.id)
    assert path.exists()

    journal.delete(entry.id)
    assert not path.exists()


def test_search_finds_entries_by_content(journal: Journal) -> None:
    journal.create(EntryCreate(body="Kestrels hunt by hovering."))
    journal.create(EntryCreate(body="Albatrosses glide for hours."))

    hits = journal.search("kestrels")
    assert len(hits) == 1
    assert "Kestrels" in hits[0].body


def test_search_survives_punctuation(journal: Journal) -> None:
    """Apostrophes and hyphens reach FTS5 constantly; unescaped they raise."""
    journal.create(EntryCreate(body="It's a well-formed thought."))
    assert journal.search("it's well-formed") != []


def test_context_excludes_the_entry_itself_and_replies(journal: Journal) -> None:
    target = journal.create(EntryCreate(body="Memory is reconstructive, not a recording."))
    journal.create(EntryCreate(body="Memory keeps rewriting itself on recall."))
    journal.add_reply(target.id, "A machine reply about memory.", ReplyKind.REFLECTION)

    context = journal.context_for(target.id)
    ids = {e.id for e in context}
    assert target.id not in ids
    assert all(e.kind is not EntryKind.REPLY for e in context)


def test_rebuild_after_index_loss(journal: Journal) -> None:
    for i in range(5):
        journal.create(EntryCreate(body=f"Thought {i}."))
    journal.index.rebuild(journal.entries_root)
    assert journal.index.count() == 5
