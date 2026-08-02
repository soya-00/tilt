"""Decisions about folders, and whether a disposable index is really disposable.

`index.db` is advertised as free to delete. It was — for everything except the
two things nobody could re-derive: a folder name the writer typed, and a split
they turned down. Both lived in the index and nowhere else, so the one operation
the app calls costless quietly discarded the only state in the system that was
not a projection of something else.

These tests all have the same shape: make a decision, delete the index the way
the README says you may, and check the decision is still there.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from tilt.folders import FolderStore
from tilt.journal import Journal
from tilt.models import Entry, Theme, ThemeSplit, utcnow
from tilt.store import files
from tilt.store.index import Index


class Restartable:
    """A journal you can throw the index away under, as a user would.

    The point of the fixture: nothing here fakes a rebuild. It deletes the file
    and opens a new `Index` on the same path, which is what happens when the
    cache is corrupt, when `POST /index/rebuild` is called, or when somebody
    follows the README.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.index = Index(root / "support" / "index.db")
        self.journal = Journal(root / "journal", self.index)

    def filed(self, body: str, label: str, *, age: timedelta = timedelta(days=1)) -> Entry:
        when = utcnow() - age
        entry = Entry(id=files.new_id(), created=when, updated=when, body=body)
        self.index.upsert(entry, files.write(entry, self.journal.entries_root))
        now = utcnow()
        theme = self.index.upsert_theme(
            Theme(id=files.new_id(), label=label, created=now, updated=now)
        )
        self.index.set_entry_themes(entry.id, [theme.id])
        self.journal.set_themes(entry.id, [theme.label])
        return entry

    def theme(self, label: str) -> Theme:
        return next(t for t in self.index.themes() if t.label.casefold() == label.casefold())

    def lose_the_index(self) -> None:
        """Exactly what the README says you may do."""
        self.index.close()
        path = self.index.path
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(path) + suffix)
            if candidate.exists():
                candidate.unlink()
        self.index = Index(path)
        self.journal = Journal(self.journal.data_dir, self.index)
        self.journal.rebuild()

    def close(self) -> None:
        self.index.close()


@pytest.fixture
def app(tmp_path):
    a = Restartable(tmp_path)
    yield a
    a.close()


# --------------------------------------------------------------- a pinned name


def test_a_name_you_typed_survives_losing_the_index(app: Restartable) -> None:
    """The half that always worked, kept as the baseline: the rename rewrites
    every member's frontmatter, so the *string* comes back on its own. What did
    not come back is the next test."""
    app.filed("Attention behaves like a filter.", "Focus")
    app.journal.rename_theme(app.theme("Focus").id, "Attention")

    app.lose_the_index()

    assert app.theme("Attention").label == "Attention"


def test_and_it_is_still_yours_afterwards(app: Restartable) -> None:
    """Not just the string. `pinned_label` is what stops the next categorise
    pass renaming it straight back, so a name that came back unpinned would be
    the same bug with a slower fuse."""
    app.filed("Attention behaves like a filter.", "Focus")
    app.journal.rename_theme(app.theme("Focus").id, "Attention")

    app.lose_the_index()

    assert app.theme("Attention").pinned_label is True


def test_the_record_is_readable(app: Restartable) -> None:
    """It lives in the journal folder, so it has to read like everything else
    there — you are invited to open that folder."""
    app.filed("Attention behaves like a filter.", "Focus")
    app.journal.rename_theme(app.theme("Focus").id, "Attention")

    text = (app.journal.data_dir / "folders.md").read_text()

    assert "Attention" in text
    assert "pinned" in text


def test_renaming_twice_leaves_one_record(app: Restartable) -> None:
    """The pin follows the folder. Left on the old name it would be orphaned,
    and the folder would come back from a rebuild unpinned under the new one."""
    app.filed("Attention behaves like a filter.", "Focus")
    app.journal.rename_theme(app.theme("Focus").id, "Attention")
    app.journal.rename_theme(app.theme("Attention").id, "Paying attention")

    assert app.journal.folders.load().pinned == ["Paying attention"]

    app.lose_the_index()
    assert app.theme("Paying attention").pinned_label is True


def test_deleting_a_folder_forgets_its_name(app: Restartable) -> None:
    """Otherwise the file grows a line for every folder ever deleted, and the
    name would be re-pinned if the agent ever minted that label again."""
    app.filed("Attention behaves like a filter.", "Focus")
    theme = app.theme("Focus")
    app.journal.rename_theme(theme.id, "Attention")
    app.journal.delete_theme(theme.id)

    assert app.journal.folders.load().pinned == []


# ------------------------------------------------------------ a refused split


def proposal(app: Restartable, label: str, *, members: int) -> ThemeSplit:
    theme = app.theme(label)
    return app.index.propose_split(
        ThemeSplit(
            id=files.new_id(),
            theme_id=theme.id,
            keep_label=label,
            move_label="Rest",
            keep_ids=[],
            move_ids=[],
            separation=0.4,
            created=utcnow(),
        ),
        members=members,
    )


def test_a_split_you_refused_stays_refused(app: Restartable) -> None:
    """The tombstone is the whole mechanism. Lose it and the keeper proposes
    the same folder again the next night, having been told no."""
    for i in range(6):
        app.filed(f"Attention note {i}.", "Attention")
    split = proposal(app, "Attention", members=6)
    app.index.dismiss_split(split.id)
    theme = app.theme("Attention")
    app.journal.folders.decline(theme.label, members=theme.count)

    app.lose_the_index()

    assert app.index.split_settled(app.theme("Attention").id, members=6, growth=1.5)


def test_the_folder_can_still_grow_its_way_to_a_second_question(app: Restartable) -> None:
    """The refusal is restored with the size it was made at, not as a blanket
    no. A folder half again as large is arguably a different folder."""
    for i in range(6):
        app.filed(f"Attention note {i}.", "Attention")
    split = proposal(app, "Attention", members=6)
    app.index.dismiss_split(split.id)
    app.journal.folders.decline("Attention", members=6)

    app.lose_the_index()

    assert not app.index.split_settled(app.theme("Attention").id, members=12, growth=1.5)


def test_a_split_that_happened_clears_the_refusal(app: Restartable) -> None:
    """Accepting settles the question the refusal was about, so the record of
    the refusal is spent — keeping it would suppress a later, different one."""
    app.journal.folders.decline("Attention", members=6)
    app.journal.folders.accepted("Attention")

    assert app.journal.folders.load().declined == []


# ------------------------------------------------------------- a refused move


def test_a_refusal_can_be_taken_back(app: Restartable) -> None:
    """The point of showing these at all. A decision you cannot see is bad; one
    you can see and cannot undo is worse, because now you know it is there."""
    app.journal.folders.refuse_move("e1", "Sleep")
    app.journal.folders.allow_move("e1", "Sleep")

    assert app.journal.folders.load().refused == []


def test_taking_one_back_leaves_the_others(app: Restartable) -> None:
    """Keyed on the pair, exactly as the refusal was. "Ask me about Sleep
    again" is not "ask me about everything again"."""
    app.journal.folders.refuse_move("e1", "Sleep")
    app.journal.folders.refuse_move("e1", "Reading")
    app.journal.folders.refuse_move("e2", "Sleep")

    app.journal.folders.allow_move("e1", "Sleep")

    assert {(r.entry, r.to) for r in app.journal.folders.load().refused} == {
        ("e1", "Reading"),
        ("e2", "Sleep"),
    }


def test_deleting_a_folder_drops_refusals_pointing_at_it(app: Restartable) -> None:
    """A refusal names its destination, so one aimed at a folder that no longer
    exists can never match anything again. Left behind it is a line in a file
    you are invited to read, describing a choice about nothing."""
    app.filed("Slept badly.", "Sleep")
    app.journal.folders.refuse_move("e1", "Sleep")

    app.journal.delete_theme(app.theme("Sleep").id)

    assert app.journal.folders.load().refused == []


def test_deleting_the_entry_drops_its_refusals(app: Restartable) -> None:
    """The other half. An id with nothing behind it is the one thing in this
    file nobody can act on — not the keeper, and not a person reading it."""
    entry = app.filed("Slept badly; everything was slower.", "Attention")
    app.journal.folders.refuse_move(entry.id, "Sleep")

    app.journal.delete(entry.id)

    assert app.journal.folders.load().refused == []


def test_a_refusal_about_another_entry_is_untouched(app: Restartable) -> None:
    """The cascade has to be about the entry that went, and nothing else."""
    gone = app.filed("Slept badly.", "Attention")
    kept = app.filed("Also about sleep.", "Attention")
    app.journal.folders.refuse_move(gone.id, "Sleep")
    app.journal.folders.refuse_move(kept.id, "Sleep")

    app.journal.delete(gone.id)

    assert [r.entry for r in app.journal.folders.load().refused] == [kept.id]


# -------------------------------------------------- the file is not load-bearing


def test_a_missing_file_is_not_an_error(app: Restartable) -> None:
    """The common case for every journal that predates this."""
    app.filed("Attention behaves like a filter.", "Attention")

    app.lose_the_index()

    assert app.theme("Attention").count == 1


def test_a_mistyped_file_costs_only_the_decisions(tmp_path: Path) -> None:
    """Refusing to boot over broken YAML would be a worse version of the same
    problem it is here to prevent."""
    path = tmp_path / "folders.md"
    path.write_text("---\npinned: [unclosed\n---\n\nbroken", encoding="utf-8")

    assert FolderStore(path).load().pinned == []


def test_a_decision_about_a_folder_that_is_gone_is_kept(app: Restartable) -> None:
    """Subjects come back. Discarding the name you gave a folder because it is
    empty this month would be the same bug on a longer timer."""
    app.journal.folders.pin("Attention")

    app.lose_the_index()

    assert app.journal.folders.load().pinned == ["Attention"]
