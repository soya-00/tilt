"""The file store is the source of truth, so these are the load-bearing tests."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from tilt.models import Entry, EntryKind, Provenance, utcnow
from tilt.store import files
from tilt.store.index import Index


def _entry(body: str = "A thought about attention.") -> Entry:
    now = utcnow()
    return Entry(id=files.new_id(), created=now, updated=now, body=body, tags=["attention"])


def test_write_then_parse_roundtrips(tmp_path: Path) -> None:
    entry = _entry()
    path = files.write(entry, tmp_path)
    loaded = files.parse(path)

    assert loaded.id == entry.id
    assert loaded.body == entry.body
    assert loaded.tags == ["attention"]
    assert loaded.kind is EntryKind.NOTE
    assert loaded.provenance is Provenance.SELF


def test_files_are_organised_by_year_and_month(tmp_path: Path) -> None:
    entry = _entry()
    path = files.write(entry, tmp_path)
    assert path.parent == tmp_path / f"{entry.created:%Y}" / f"{entry.created:%m}"
    assert path.suffix == ".md"


def test_parse_tolerates_unknown_and_invalid_frontmatter(tmp_path: Path) -> None:
    """A hand-edited file must still load. Losing a thought to a schema error
    is not an acceptable failure mode."""
    path = tmp_path / "hand-written.md"
    path.write_text(
        "---\nid: abc123\nkind: not-a-real-kind\ntags: alpha, beta\nmood: restless\n---\nBody.\n",
        encoding="utf-8",
    )
    entry = files.parse(path)

    assert entry.id == "abc123"
    assert entry.kind is EntryKind.NOTE  # fell back rather than raising
    assert entry.tags == ["alpha", "beta"]
    assert entry.body == "Body."


def test_write_preserves_unknown_frontmatter_keys(tmp_path: Path) -> None:
    entry = _entry()
    path = files.write(entry, tmp_path)

    post = frontmatter.load(path)
    post["mood"] = "restless"
    path.write_text(frontmatter.dumps(post), encoding="utf-8")

    entry.body = "Revised."
    files.write(entry, tmp_path, preserve_extra_from=path)

    assert frontmatter.load(path)["mood"] == "restless"


def test_no_temp_files_survive_a_write(tmp_path: Path) -> None:
    files.write(_entry(), tmp_path)
    assert list(tmp_path.rglob("*.tmp")) == []


def test_rebuild_reconstructs_index_from_disk(tmp_path: Path) -> None:
    """Delete the database entirely; the journal must come back intact.
    This is the guarantee the whole file-as-truth design rests on."""
    entries_root = tmp_path / "entries"
    db_path = tmp_path / ".tilt" / "index.db"

    index = Index(db_path)
    written = [_entry(f"Thought number {i} about memory.") for i in range(25)]
    for entry in written:
        index.upsert(entry, files.write(entry, entries_root))
    assert index.count() == 25
    index.close()

    db_path.unlink()

    rebuilt = Index(db_path)
    assert rebuilt.count() == 0
    assert rebuilt.rebuild(entries_root) == 25
    assert rebuilt.count() == 25
    assert len(rebuilt.search_fts('"memory"', limit=50)) == 25
    rebuilt.close()


def test_fts_index_does_not_drift_on_update(tmp_path: Path) -> None:
    """External-content FTS5 tables corrupt silently if the old row is not
    deleted with its original values before reindexing."""
    index = Index(tmp_path / "index.db")
    entry = _entry("The original wording mentions kestrels.")
    index.upsert(entry, files.write(entry, tmp_path / "entries"))

    entry.body = "The revised wording mentions albatrosses."
    index.upsert(entry, files.write(entry, tmp_path / "entries"))

    assert index.search_fts('"kestrels"') == []
    assert len(index.search_fts('"albatrosses"')) == 1
    index.close()
