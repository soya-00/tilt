"""Splitting a folder, and above all not splitting one.

Every gate here exists because of an asymmetry the merge pass does not have. A
wrong merge leaves one folder where there should be two: visible, and the next
pass can still separate them. A wrong split leaves two folders where there
should be one, named differently, so the merge pass — which only ever looks at
folders with similar names — will never consider the pair again. Nothing in the
app puts it back.

So the tests that matter most are the ones asserting that nothing happened.
"""

from __future__ import annotations

import math
import random
from datetime import timedelta

import pytest

from tilt.agents.base import Completion, Pricing
from tilt.agents.ledger import MeteredProvider
from tilt.jobs import split as splitpass
from tilt.jobs.themes import keep_themes
from tilt.journal import Journal
from tilt.models import Entry, Theme, ThemeSplit, utcnow
from tilt.store import files
from tilt.store.index import Index, content_hash
from tilt.store.vectors import VectorStore

DIMS = 32

VERDICT = '{"split": true, "keep": "Attention", "move": "Sleep"}'
REFUSAL = '{"split": false}'


class Scripted:
    """Says what it is told to, so a veto can be given or withheld on demand."""

    name = "scripted"
    pricing = Pricing(0.0, 0.0)

    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    async def complete(self, prompt: str, *, system: str | None = None):
        self.prompts.append(prompt)
        return Completion(text=self.text, model="scripted", tokens_in=1, tokens_out=1)


class Placed:
    """An embedder that puts text where the test says, rather than where a model
    would. Stands in for the only property the pass uses: position by meaning."""

    signature = "test/placed/32"
    dims = DIMS

    def __init__(self) -> None:
        self.places: dict[str, list[float]] = {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.places[t.strip()] for t in texts]


def unit(rng: random.Random) -> list[float]:
    raw = [rng.gauss(0, 1) for _ in range(DIMS)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


def near(rng: random.Random, centre: list[float], spread: float = 0.07) -> list[float]:
    raw = [c + spread * rng.gauss(0, 1) for c in centre]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


class Folder:
    """A journal with one folder in it, and control over where its entries sit."""

    def __init__(self, tmp_path, label: str = "Attention") -> None:
        self.index = Index(tmp_path / "index.db")
        self.vectors = VectorStore(tmp_path / "vectors.db")
        self.embedder = Placed()
        self.journal = Journal(tmp_path / "journal", self.index, self.vectors, self.embedder)
        now = utcnow()
        self.theme = self.index.upsert_theme(
            Theme(id=files.new_id(), label=label, created=now, updated=now)
        )
        self.rng = random.Random(19)

    def fill(self, centre: list[float], n: int, *, prefix: str, embed: bool = True) -> None:
        for i in range(n):
            body = f"{prefix} {i}: a thought worth keeping."
            when = utcnow() - timedelta(days=n - i)
            entry = Entry(id=files.new_id(), created=when, updated=when, body=body)
            self.index.upsert(entry, files.write(entry, self.journal.entries_root))
            self.index.set_entry_themes(entry.id, [self.theme.id])
            self.journal.set_themes(entry.id, [self.theme.label])
            if embed:
                self.vectors.put(
                    entry.id,
                    self.embedder.signature,
                    content_hash(entry.body),
                    near(self.rng, centre),
                )

    def two_subjects(self, *, left: int = 15, right: int = 12) -> None:
        a, b = unit(self.rng), unit(self.rng)
        self.fill(a, left, prefix="Attention")
        self.fill(b, right, prefix="Sleep")

    def one_subject(self, n: int = 27) -> None:
        self.fill(unit(self.rng), n, prefix="Attention")

    def current(self) -> Theme:
        return self.index.get_theme(self.theme.id)

    def close(self) -> None:
        self.vectors.close()
        self.index.close()


@pytest.fixture
def folder(tmp_path):
    f = Folder(tmp_path)
    yield f
    f.close()


def metered(index: Index, text: str) -> tuple[MeteredProvider, Scripted]:
    scripted = Scripted(text)
    return MeteredProvider(scripted, index, ceiling_usd=1.0), scripted


# ------------------------------------------------------------ nothing happens


async def test_a_proposal_changes_nothing_on_disk(folder: Folder) -> None:
    """The one that matters. A folder that plainly holds two subjects, a model
    that plainly agrees — and the journal is byte-for-byte where it was."""
    folder.two_subjects()
    before = {
        path: path.read_text() for path in folder.journal.entries_root.rglob("*.md")
    }
    provider, _ = metered(folder.index, VERDICT)

    split = await splitpass.propose_split(
        folder.journal, provider, folder.index.themes()
    )

    assert split is not None, "the candidate should have been found"
    assert {p: p.read_text() for p in folder.journal.entries_root.rglob("*.md")} == before
    assert [t.label for t in folder.index.themes()] == ["Attention"]


async def test_the_keeper_proposes_rather_than_reorganises(folder: Folder) -> None:
    """Through the nightly job, not the pass in isolation — the keeper is the
    thing that runs at 3am while nobody is looking."""
    folder.two_subjects()
    provider, _ = metered(folder.index, VERDICT)

    summary = await keep_themes(folder.journal, provider)

    assert summary.proposed == 1
    assert "waiting on you" in summary.detail
    assert len(folder.index.themes()) == 1
    assert len(folder.index.pending_splits()) == 1


async def test_a_refusal_leaves_no_proposal(folder: Folder) -> None:
    """The model has the last word, and its expected answer is no."""
    folder.two_subjects()
    provider, scripted = metered(folder.index, REFUSAL)

    assert await splitpass.propose_split(folder.journal, provider, folder.index.themes()) is None
    assert scripted.prompts, "it should still have been asked"
    assert folder.index.pending_splits() == []


async def test_half_a_verdict_is_not_one(folder: Folder) -> None:
    """A split with only one name would leave the smaller folder called
    something nobody chose."""
    folder.two_subjects()
    provider, _ = metered(folder.index, '{"split": true, "keep": "Attention"}')

    assert await splitpass.propose_split(folder.journal, provider, folder.index.themes()) is None


# ------------------------------------------------- the gates, before any cost


async def test_one_subject_is_never_even_put_to_the_model(folder: Folder) -> None:
    """The measurement is the filter. A folder about one thing costs nothing to
    leave alone, and it must not be the model's job to notice that."""
    folder.one_subject()
    provider, scripted = metered(folder.index, VERDICT)

    assert await splitpass.propose_split(folder.journal, provider, folder.index.themes()) is None
    assert scripted.prompts == [], "no call should have been made at all"


async def test_a_small_folder_is_left_alone(folder: Folder) -> None:
    """Eight entries is not two subjects, however they sit."""
    a, b = unit(folder.rng), unit(folder.rng)
    folder.fill(a, 4, prefix="Attention")
    folder.fill(b, 4, prefix="Sleep")
    provider, scripted = metered(folder.index, VERDICT)

    assert await splitpass.propose_split(folder.journal, provider, folder.index.themes()) is None
    assert scripted.prompts == []


async def test_an_outlier_pair_is_not_a_subject(folder: Folder) -> None:
    """A 20/2 division is the two entries furthest from the middle, and peeling
    them off would leave a folder of two nobody can name."""
    a, b = unit(folder.rng), unit(folder.rng)
    folder.fill(a, 20, prefix="Attention")
    folder.fill(b, 2, prefix="Sleep")
    provider, scripted = metered(folder.index, VERDICT)

    assert await splitpass.propose_split(folder.journal, provider, folder.index.themes()) is None
    assert scripted.prompts == []


async def test_a_half_embedded_folder_waits(folder: Folder) -> None:
    """Judging on the entries that happen to have been embedded means judging on
    the hourly job's progress, and the part it has not reached is exactly where
    a second subject would be.

    Arranged so that coverage is the *only* thing stopping it: the entries that
    are embedded do divide cleanly into two, and would be proposed on their own.
    """
    a, b, c = unit(folder.rng), unit(folder.rng), unit(folder.rng)
    folder.fill(a, 15, prefix="Attention")
    folder.fill(b, 8, prefix="Sleep")
    folder.fill(c, 10, prefix="Reading", embed=False)
    provider, scripted = metered(folder.index, VERDICT)

    assert await splitpass.propose_split(folder.journal, provider, folder.index.themes()) is None
    assert scripted.prompts == []


async def test_without_an_embedder_the_pass_is_simply_absent(tmp_path) -> None:
    """No key, no vectors, no splitting — and no error either. Same posture as
    every other capability that needs one."""
    index = Index(tmp_path / "index.db")
    journal = Journal(tmp_path / "journal", index)
    provider, scripted = metered(index, VERDICT)
    try:
        assert await splitpass.propose_split(journal, provider, index.themes()) is None
        assert scripted.prompts == []
    finally:
        index.close()


# ------------------------------------------------------------- what it stores


async def test_the_proposal_names_both_halves_and_its_evidence(folder: Folder) -> None:
    folder.two_subjects(left=15, right=12)
    provider, _ = metered(folder.index, VERDICT)

    split = await splitpass.propose_split(folder.journal, provider, folder.index.themes())

    assert split.keep_label == "Attention"
    assert split.move_label == "Sleep"
    assert len(split.keep_ids) == 15
    assert len(split.move_ids) == 12
    assert split.separation > splitpass.SEPARATION
    assert folder.index.pending_splits()[0].theme_label == "Attention"


async def test_a_name_you_typed_is_never_overwritten(tmp_path) -> None:
    """The larger half keeps the folder, so it keeps the name you gave it —
    whatever the model would have preferred to call it."""
    f = Folder(tmp_path, label="My own name")
    try:
        f.index.rename_theme(f.theme.id, "My own name")
        f.two_subjects()
        provider, _ = metered(f.index, VERDICT)

        split = await splitpass.propose_split(f.journal, provider, f.index.themes())

        assert split.keep_label == "My own name"
        assert split.move_label == "Sleep"
    finally:
        f.close()


async def test_only_one_folder_is_proposed_per_run(tmp_path) -> None:
    """Two obvious candidates, one proposal. Unreviewed splits should not
    accumulate faster than anyone looks at them."""
    f = Folder(tmp_path)
    try:
        now = utcnow()
        second = f.index.upsert_theme(
            Theme(id=files.new_id(), label="Reading", created=now, updated=now)
        )
        f.two_subjects()
        f.theme = second
        f.two_subjects()

        provider, scripted = metered(f.index, VERDICT)
        await splitpass.propose_split(f.journal, provider, f.index.themes())

        assert len(scripted.prompts) == 1
        assert len(f.index.pending_splits()) == 1
    finally:
        f.close()


async def test_the_model_is_shown_both_halves(folder: Folder) -> None:
    folder.two_subjects()
    provider, scripted = metered(folder.index, VERDICT)

    await splitpass.propose_split(folder.journal, provider, folder.index.themes())

    [prompt] = scripted.prompts
    assert "GROUP A" in prompt and "GROUP B" in prompt
    assert prompt.count("- ") == 2 * splitpass.SAMPLE, "a sample from each, not the folder"


# ------------------------------------------------------- accepting, and after


async def proposal(folder: Folder) -> object:
    folder.two_subjects()
    provider, _ = metered(folder.index, VERDICT)
    return await splitpass.propose_split(folder.journal, provider, folder.index.themes())


async def test_accepting_moves_the_smaller_half(folder: Folder) -> None:
    split = await proposal(folder)

    moved = splitpass.apply_split(folder.journal, split)

    assert moved == len(split.move_ids)
    labels = sorted(t.label for t in folder.index.themes())
    assert labels == ["Attention", "Sleep"]
    assert {e.id for e in folder.index.entries_in_theme(folder.theme.id)} == set(split.keep_ids)


async def test_the_split_survives_a_rebuild(folder: Folder) -> None:
    """The lesson the merge pass had to learn. Folders are restored from each
    entry's own Markdown on boot, so a split confined to SQLite lasts until the
    next restart — at which point the old folder is recreated from frontmatter
    that still names it and every entry follows it back."""
    split = await proposal(folder)
    splitpass.apply_split(folder.journal, split)

    folder.journal.rebuild()

    labels = sorted(t.label for t in folder.index.themes())
    assert labels == ["Attention", "Sleep"]
    sleep = next(t for t in folder.index.themes() if t.label == "Sleep")
    assert len(folder.index.entries_in_theme(sleep.id)) == len(split.move_ids)


async def test_accepting_clears_the_proposal(folder: Folder) -> None:
    """The two folders are the record of that decision now. A proposal left
    standing would offer a split that has already happened."""
    split = await proposal(folder)
    splitpass.apply_split(folder.journal, split)

    assert folder.index.pending_splits() == []


async def test_entries_filed_elsewhere_since_are_not_dragged_along(folder: Folder) -> None:
    """A proposal made at 3am can be accepted at noon."""
    split = await proposal(folder)
    gone = split.move_ids[0]
    folder.journal.delete(gone)

    moved = splitpass.apply_split(folder.journal, split)

    assert moved == len(split.move_ids) - 1


# ------------------------------------------------------------ turning it down


async def test_a_dismissal_is_not_asked_again_tomorrow(folder: Folder) -> None:
    split = await proposal(folder)
    assert folder.index.dismiss_split(split.id)

    provider, scripted = metered(folder.index, VERDICT)
    assert await splitpass.propose_split(folder.journal, provider, folder.index.themes()) is None
    assert scripted.prompts == [], "and not by spending a call to be told no again"


async def test_a_dismissal_lifts_once_the_folder_has_really_grown(folder: Folder) -> None:
    """Half as many entries again is arguably a different folder, and asking
    once more about it is a new observation rather than nagging."""
    split = await proposal(folder)
    folder.index.dismiss_split(split.id)

    folder.fill(unit(folder.rng), 20, prefix="Sleep")
    provider, _ = metered(folder.index, VERDICT)

    assert await splitpass.propose_split(folder.journal, provider, folder.index.themes())


async def test_a_pending_proposal_is_not_proposed_twice(folder: Folder) -> None:
    """One unanswered question per folder. Asking again while the first is still
    on screen is how a suggestion becomes a queue."""
    await proposal(folder)
    provider, scripted = metered(folder.index, VERDICT)

    assert await splitpass.propose_split(folder.journal, provider, folder.index.themes()) is None
    assert scripted.prompts == []


async def test_nothing_is_deleted_by_either_answer(folder: Folder) -> None:
    """Accepting refiles entries and dismissing refiles nothing. Neither
    removes a thought."""
    split = await proposal(folder)
    before = folder.index.count()

    splitpass.apply_split(folder.journal, split)

    assert folder.index.count() == before
    assert len(list(folder.journal.entries_root.rglob("*.md"))) == before


# ------------------------------------------------------------- over the wire


def planted(client, label: str = "Attention") -> dict:
    """A folder with two entries in it and a proposal against it, made by hand.

    The measurement has its own tests; these are about the routes, and building
    a real candidate through the API would need an embedder and a key.
    """
    index = client.app.state.journal.index
    ids = [client.post("/entries", json={"body": f"{label} {i}"}).json()["entry"]["id"]
           for i in range(2)]
    now = utcnow()
    theme = index.upsert_theme(Theme(id=files.new_id(), label=label, created=now, updated=now))
    for entry_id in ids:
        index.set_entry_themes(entry_id, [theme.id])
        client.app.state.journal.set_themes(entry_id, [theme.label])
    index.propose_split(
        ThemeSplit(
            id=files.new_id(),
            theme_id=theme.id,
            keep_label=label,
            move_label="Sleep",
            keep_ids=ids[:1],
            move_ids=ids[1:],
            separation=0.4,
            created=now,
        ),
        members=2,
    )
    return {"theme": theme, "ids": ids}


def test_the_route_offers_what_the_keeper_found(client) -> None:
    planted(client)

    [proposal] = client.get("/themes/splits").json()

    assert proposal["move_label"] == "Sleep"
    assert proposal["theme_label"] == "Attention"


def test_a_healthy_sidebar_offers_nothing(client) -> None:
    """The common case. A list that is never empty is one nobody reads."""
    assert client.get("/themes/splits").json() == []


def test_accepting_over_the_wire_makes_two_folders(client) -> None:
    planted(client)
    [proposal] = client.get("/themes/splits").json()

    folders = client.post(f"/themes/splits/{proposal['id']}").json()

    assert sorted(t["label"] for t in folders) == ["Attention", "Sleep"]
    assert client.get("/themes/splits").json() == []


def test_dismissing_over_the_wire_leaves_one(client) -> None:
    planted(client)
    [proposal] = client.get("/themes/splits").json()

    assert client.delete(f"/themes/splits/{proposal['id']}").status_code == 204

    assert [t["label"] for t in client.get("/themes").json()] == ["Attention"]
    assert client.get("/themes/splits").json() == []


def test_a_proposal_that_is_gone_says_so(client) -> None:
    assert client.post("/themes/splits/nope").status_code == 404
    assert client.delete("/themes/splits/nope").status_code == 404
