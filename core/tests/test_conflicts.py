"""Two files claiming one entry.

A sync client's "(conflicted copy)" carries the id of the file it copied, so
both are the same entry as far as the index is concerned. Before this, one of
them silently won on sorted-path order and the other sat on disk looking
perfectly fine while its edits were invisible.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tilt.models import Entry, utcnow
from tilt.store import files
from tilt.store.index import Index


def written(root: Path, name: str, *, entry_id: str, body: str, age: timedelta) -> Path:
    """A journal file placed by hand, so a duplicate id can be arranged.

    Written directly rather than through `files.write`, which derives its own
    filename — a conflicted copy is precisely a file whose name does not match
    the convention.
    """
    when = utcnow() - age
    entry = Entry(id=entry_id, created=when, updated=when, body=body)
    # Written through `files.write` so the frontmatter is exactly what the app
    # produces, then *moved* — leaving the canonical copy in place would add a
    # third file and make the fixture the thing under test.
    canonical = files.write(entry, root)
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical.replace(path)
    return path


def test_a_conflicted_copy_is_reported_rather_than_swallowed(tmp_path: Path) -> None:
    root = tmp_path / "entries"
    original = written(
        root,
        "2026/07/a.md",
        entry_id="01KYVPF3VB2WV8J0PDGTQBKD5M",
        body="The newer thought.",
        age=timedelta(minutes=1),
    )
    copy = written(
        root,
        "2026/07/a (conflicted copy).md",
        entry_id="01KYVPF3VB2WV8J0PDGTQBKD5M",
        body="The older thought.",
        age=timedelta(days=2),
    )

    index = Index(tmp_path / "index.db")
    try:
        indexed = index.rebuild(root)

        # One entry, not two: they are the same id.
        assert indexed == 1
        assert index.count() == 1

        [conflict] = index.conflicts
        assert conflict.entry_id == "01KYVPF3VB2WV8J0PDGTQBKD5M"
        # The newer file is kept — a reason, where sorted-path order is an
        # accident. Both paths are named so it can be settled by hand.
        assert conflict.kept == str(original)
        assert conflict.ignored == str(copy)

        assert index.get("01KYVPF3VB2WV8J0PDGTQBKD5M").body == "The newer thought."
    finally:
        index.close()


def test_the_newer_file_wins_even_when_it_sorts_first(tmp_path: Path) -> None:
    """The rule is `updated`, not filename order.

    Arranged so the two disagree: the newer file is named `a.md` and the older
    `z.md`, so whichever the walk reaches last is the stale one. Without this
    the previous behaviour — last in sorted order — passes the other tests by
    coincidence, because a conflicted copy usually sorts before its original.
    """
    root = tmp_path / "entries"
    newer = written(root, "2026/07/a.md", entry_id="01KYVPF3VB2WV8J0PDGTQBKD5M",
                    body="The newer thought.", age=timedelta(minutes=1))
    written(root, "2026/07/z.md", entry_id="01KYVPF3VB2WV8J0PDGTQBKD5M",
            body="The older thought.", age=timedelta(days=5))

    index = Index(tmp_path / "index.db")
    try:
        index.rebuild(root)

        assert index.get("01KYVPF3VB2WV8J0PDGTQBKD5M").body == "The newer thought."
        assert index.conflicts[0].kept == str(newer)
    finally:
        index.close()


def test_neither_file_is_touched(tmp_path: Path) -> None:
    """Report, do not resolve. Renaming or merging somebody's files without
    asking is not the app's business."""
    root = tmp_path / "entries"
    a = written(root, "2026/07/a.md", entry_id="01KYVPF3VB2WV8J0PDGTQBKD5M",
                body="One.", age=timedelta(minutes=1))
    b = written(root, "2026/07/a-copy.md", entry_id="01KYVPF3VB2WV8J0PDGTQBKD5M",
                body="Two.", age=timedelta(days=1))
    before = (a.read_text(), b.read_text())

    index = Index(tmp_path / "index.db")
    try:
        index.rebuild(root)
    finally:
        index.close()

    assert a.exists() and b.exists()
    assert (a.read_text(), b.read_text()) == before


def test_a_healthy_journal_reports_nothing(tmp_path: Path) -> None:
    """The common case, and it should stay quiet. A conflicts list that is
    never empty is one nobody reads."""
    root = tmp_path / "entries"
    written(root, "2026/07/a.md", entry_id="01KYVPF3VB2WV8J0PDGTQBKD5M",
            body="One.", age=timedelta(minutes=1))
    written(root, "2026/07/b.md", entry_id="01KYVPF3VB2WV8J0PDGTQBKD6N",
            body="Two.", age=timedelta(minutes=2))

    index = Index(tmp_path / "index.db")
    try:
        assert index.rebuild(root) == 2
        assert index.conflicts == []
    finally:
        index.close()


def test_a_later_clean_rebuild_clears_the_report(tmp_path: Path) -> None:
    """Once you have deleted the copy, the warning has to go away by itself —
    a stale conflict would send you looking for a file that is no longer there."""
    root = tmp_path / "entries"
    written(root, "2026/07/a.md", entry_id="01KYVPF3VB2WV8J0PDGTQBKD5M",
            body="One.", age=timedelta(minutes=1))
    copy = written(root, "2026/07/a-copy.md", entry_id="01KYVPF3VB2WV8J0PDGTQBKD5M",
                   body="Two.", age=timedelta(days=1))

    index = Index(tmp_path / "index.db")
    try:
        index.rebuild(root)
        assert len(index.conflicts) == 1

        copy.unlink()
        index.rebuild(root)
        assert index.conflicts == []
    finally:
        index.close()


def test_the_status_route_carries_them(client: TestClient) -> None:
    """Surfaced where `dormant` already is, because it is the same kind of
    thing: something the app noticed that you would otherwise never see."""
    assert client.get("/status").json()["conflicts"] == []
