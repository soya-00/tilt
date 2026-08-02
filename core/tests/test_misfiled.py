"""Refiling an entry the original filing got wrong.

Filing is path dependent: an entry written before a subject had a folder lands
in whichever folder was nearest that week and stays there. This is the repair,
and like every other repair here that changes what you wrote, the test that
matters most is the one asserting that nothing happened.
"""

from __future__ import annotations

import random
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tilt.folders import FolderStore
from tilt.jobs import misfiled
from tilt.jobs.split import normalise
from tilt.journal import Journal
from tilt.models import Entry, Theme, utcnow
from tilt.store import files
from tilt.store.index import Index, content_hash
from tilt.store.vectors import VectorStore

DIMS = 32


class Placed:
    signature = "test/placed/32"
    dims = DIMS

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        raise AssertionError("the filing pass must never embed anything")


def unit(rng: random.Random) -> list[float]:
    return normalise([rng.gauss(0, 1) for _ in range(DIMS)])


def near(rng: random.Random, centre: list[float]) -> list[float]:
    return normalise([c + 0.07 * rng.gauss(0, 1) for c in centre])


class Shelf:
    """Two folders, and control over where each entry actually sits."""

    def __init__(self, tmp_path) -> None:
        self.index = Index(tmp_path / "index.db")
        self.vectors = VectorStore(tmp_path / "vectors.db")
        self.embedder = Placed()
        self.journal = Journal(tmp_path / "journal", self.index, self.vectors, self.embedder)
        self.rng = random.Random(19)
        self.here = unit(self.rng)
        self.there = unit(self.rng)
        now = utcnow()
        self.attention = self.index.upsert_theme(
            Theme(id=files.new_id(), label="Attention", created=now, updated=now)
        )
        self.sleep = self.index.upsert_theme(
            Theme(id=files.new_id(), label="Sleep", created=now, updated=now)
        )
        self.age = 0

    def filed(self, theme: Theme, centre: list[float], *, body: str = "") -> Entry:
        self.age += 1
        when = utcnow() - timedelta(days=self.age)
        entry = Entry(
            id=files.new_id(),
            created=when,
            updated=when,
            body=body or f"A thought about {theme.label}, number {self.age}.",
        )
        self.index.upsert(entry, files.write(entry, self.journal.entries_root))
        self.index.set_entry_themes(entry.id, [theme.id])
        self.journal.set_themes(entry.id, [theme.label])
        self.vectors.put(
            entry.id, self.embedder.signature, content_hash(entry.body), near(self.rng, centre)
        )
        return entry

    def fill(self, theme: Theme, centre: list[float], n: int) -> None:
        for _ in range(n):
            self.filed(theme, centre)

    def themes(self) -> list[Theme]:
        return self.index.themes()

    def labels_of(self, entry_id: str) -> list[str]:
        return sorted(t.label for t in self.index.themes_for([entry_id]).get(entry_id, []))

    def close(self) -> None:
        self.vectors.close()
        self.index.close()


@pytest.fixture
def shelf(tmp_path):
    s = Shelf(tmp_path)
    yield s
    s.close()


def a_stray(shelf: Shelf) -> Entry:
    """One entry filed under Attention that sits squarely in Sleep."""
    shelf.fill(shelf.attention, shelf.here, 6)
    shelf.fill(shelf.sleep, shelf.there, 6)
    return shelf.filed(shelf.attention, shelf.there, body="Slept badly; everything was slower.")


# ------------------------------------------------------------ nothing happens


async def test_a_proposal_changes_nothing_on_disk(shelf: Shelf) -> None:
    """The one that matters. An entry that plainly sits in the other folder, a
    pass that plainly finds it — and the journal byte-for-byte where it was."""
    stray = a_stray(shelf)
    before = {p: p.read_text() for p in shelf.journal.entries_root.rglob("*.md")}

    await misfiled.keep_filing(shelf.journal, shelf.themes())

    assert {p: p.read_text() for p in shelf.journal.entries_root.rglob("*.md")} == before
    assert shelf.labels_of(stray.id) == ["Attention"]
    assert len(shelf.index.pending_moves()) == 1


async def test_it_costs_nothing_to_find(shelf: Shelf) -> None:
    """No model call, by design rather than by omission: a wrong move relocates
    one entry and costs one dismissal, so a second opinion would be paying to be
    told what the arithmetic already says."""
    a_stray(shelf)

    # `Placed.embed` raises if anything tries to embed, and the pass takes no
    # provider at all — there is nothing here that could spend.
    await misfiled.keep_filing(shelf.journal, shelf.themes())

    assert shelf.index.pending_moves()


async def test_it_names_both_folders_and_its_evidence(shelf: Shelf) -> None:
    stray = a_stray(shelf)

    await misfiled.keep_filing(shelf.journal, shelf.themes())

    [move] = shelf.index.pending_moves()
    assert move.entry_id == stray.id
    assert move.from_label == "Attention"
    assert move.to_label == "Sleep"
    assert move.margin >= misfiled.MARGIN
    assert "Slept badly" in move.opening


# ------------------------------------------------------------------ the gates


async def test_a_well_filed_journal_proposes_nothing(shelf: Shelf) -> None:
    """The common case, and it has to stay quiet. Filing is right most of the
    time, and a suggestion list that is never empty is one nobody reads."""
    shelf.fill(shelf.attention, shelf.here, 8)
    shelf.fill(shelf.sleep, shelf.there, 8)

    await misfiled.keep_filing(shelf.journal, shelf.themes())

    assert shelf.index.pending_moves() == []


async def test_small_folders_are_left_out_of_it(shelf: Shelf) -> None:
    """The average of three entries is three entries, not a subject's position —
    neither compared against nor moved out of."""
    shelf.fill(shelf.attention, shelf.here, 3)
    shelf.fill(shelf.sleep, shelf.there, 3)
    shelf.filed(shelf.attention, shelf.there)

    await misfiled.keep_filing(shelf.journal, shelf.themes())

    assert shelf.index.pending_moves() == []


async def test_an_entry_already_in_both_is_not_a_finding(shelf: Shelf) -> None:
    """Entries can be in several folders. "You would be better off somewhere you
    already are" is not something to interrupt anyone with."""
    shelf.fill(shelf.attention, shelf.here, 6)
    shelf.fill(shelf.sleep, shelf.there, 6)
    both = shelf.filed(shelf.attention, shelf.there)
    shelf.index.set_entry_themes(both.id, [shelf.attention.id, shelf.sleep.id])

    await misfiled.keep_filing(shelf.journal, shelf.themes())

    assert shelf.index.pending_moves() == []


async def test_without_vectors_the_pass_is_simply_absent(tmp_path) -> None:
    """No key, no filing repair — and no error, like every other capability
    that needs one."""
    index = Index(tmp_path / "index.db")
    journal = Journal(tmp_path / "journal", index)
    try:
        assert await misfiled.keep_filing(journal, index.themes()) == 0
    finally:
        index.close()


async def test_at_most_three_at_a_time(shelf: Shelf) -> None:
    """Reviewable per entry, so more than one is fine — but a stream of them is
    a queue, which is the thing this app refuses to become."""
    shelf.fill(shelf.attention, shelf.here, 8)
    shelf.fill(shelf.sleep, shelf.there, 8)
    for _ in range(6):
        shelf.filed(shelf.attention, shelf.there)

    await misfiled.keep_filing(shelf.journal, shelf.themes())

    assert len(shelf.index.pending_moves()) == misfiled.MAX_PROPOSALS


# ----------------------------------------------------------------- accepting


async def test_accepting_refiles_the_entry(shelf: Shelf) -> None:
    stray = a_stray(shelf)
    await misfiled.keep_filing(shelf.journal, shelf.themes())
    [move] = shelf.index.pending_moves()

    assert misfiled.apply_move(shelf.journal, move) is True

    assert shelf.labels_of(stray.id) == ["Sleep"]
    assert shelf.index.pending_moves() == []


async def test_the_move_survives_a_rebuild(shelf: Shelf) -> None:
    """The lesson every other structural change here had to learn: folders are
    restored from each entry's own Markdown on boot, so a move confined to
    SQLite lasts until the next restart and then the entry goes home."""
    stray = a_stray(shelf)
    await misfiled.keep_filing(shelf.journal, shelf.themes())
    misfiled.apply_move(shelf.journal, shelf.index.pending_moves()[0])

    shelf.journal.rebuild()

    assert shelf.labels_of(stray.id) == ["Sleep"]


async def test_an_entry_deleted_since_is_not_an_error(shelf: Shelf) -> None:
    """A proposal made at 3am can be answered at noon."""
    stray = a_stray(shelf)
    await misfiled.keep_filing(shelf.journal, shelf.themes())
    [move] = shelf.index.pending_moves()
    shelf.journal.delete(stray.id)

    assert misfiled.apply_move(shelf.journal, move) is False


# ---------------------------------------------------------------- refusing


async def test_a_refusal_is_not_raised_again(shelf: Shelf) -> None:
    stray = a_stray(shelf)
    await misfiled.keep_filing(shelf.journal, shelf.themes())
    shelf.journal.folders.refuse_move(stray.id, "Sleep")
    shelf.index.clear_move(stray.id)

    await misfiled.keep_filing(shelf.journal, shelf.themes())

    assert shelf.index.pending_moves() == []


async def test_a_refusal_survives_losing_the_index(shelf: Shelf, tmp_path) -> None:
    """`index.db` is the one store the app promises is safe to delete, so a
    decision that lived only there came back the first time anyone believed it."""
    stray = a_stray(shelf)
    shelf.journal.folders.refuse_move(stray.id, "Sleep")

    assert shelf.journal.folders.load().refused_move(stray.id, "Sleep")
    assert "refused" in (shelf.journal.data_dir / "folders.md").read_text()


async def test_refusing_one_folder_does_not_silence_the_entry(shelf: Shelf) -> None:
    """"Not that folder" is a narrower answer than "leave this entry alone
    forever", and the narrower one is what was actually said."""
    stray = a_stray(shelf)
    shelf.journal.folders.refuse_move(stray.id, "Reading")

    await misfiled.keep_filing(shelf.journal, shelf.themes())

    assert len(shelf.index.pending_moves()) == 1


# ------------------------------------------------------------- over the wire


def test_the_routes_are_there_and_quiet(client: TestClient) -> None:
    assert client.get("/moves").json() == []
    assert client.post("/moves/nope").status_code == 404
    assert client.delete("/moves/nope").status_code == 404


def test_a_refusal_can_be_read_back_as_a_sentence(client: TestClient, settings) -> None:
    """What `folders.md` stores is an id and a folder name, which is what the
    keeper needs and nothing anyone can recognise. The panel that lists your
    decisions has to show the entry."""
    entry = client.post(
        "/entries", json={"body": "Slept badly; everything was slower."}
    ).json()["entry"]
    FolderStore(settings.data_dir / "folders.md").refuse_move(entry["id"], "Sleep")

    [refusal] = client.get("/folders").json()["refused"]

    assert refusal["to"] == "Sleep"
    assert refusal["opening"] == "Slept badly; everything was slower."


def test_a_refusal_whose_entry_is_gone_is_not_listed(client: TestClient, settings) -> None:
    """Deleting an entry drops its refusals, so this is the leftover case — a
    hand-edited file, or Markdown removed from under the app. A row nobody can
    place is worse than no row."""
    FolderStore(settings.data_dir / "folders.md").refuse_move("not-an-entry", "Sleep")

    assert client.get("/folders").json()["refused"] == []


def test_asking_again_is_one_request(client: TestClient, settings) -> None:
    """And it restores the question rather than answering it: nothing moves."""
    entry = client.post("/entries", json={"body": "Slept badly."}).json()["entry"]
    store = FolderStore(settings.data_dir / "folders.md")
    store.refuse_move(entry["id"], "Sleep")

    response = client.delete(f"/folders/refused/{entry['id']}", params={"to": "Sleep"})

    assert response.status_code == 204
    assert store.load().refused == []
    assert client.get(f"/entries/{entry['id']}").json()["themes"] == []
