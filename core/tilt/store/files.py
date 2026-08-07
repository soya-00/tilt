"""Markdown file store — the source of truth.

Every entry is one Markdown file with YAML frontmatter, readable by Obsidian,
greppable, and diffable in git. The SQLite index in :mod:`tilt.store.index` is a
cache that can be thrown away and rebuilt from this directory at any time.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import frontmatter
from ulid import ULID

from tilt.models import Entry, EntryKind, LinkRecord, Provenance, ReplyKind, utcnow

# Frontmatter keys that carry structure. Anything else is passed through
# untouched so hand-edited files never lose data on rewrite.
_KNOWN_KEYS = {
    "id",
    "created",
    "updated",
    "kind",
    "provenance",
    "parent",
    "source_id",
    "anchor",
    "source_url",
    "reply_kind",
    "tags",
    "themes",
    "links",
    "filed",
    "judged",
    "promoted",
}


def new_id() -> str:
    return str(ULID())


def usable_id(raw: str) -> bool:
    """Whether this id can be interpolated into a filename safely.

    An entry's id arrives from frontmatter, which means it arrives from whatever
    wrote the file — an import, a folder sync, a hand edit. :func:`path_for` puts
    it straight into a path, so an id carrying a separator escapes the directory
    and the write lands wherever it points.

    Deliberately a check on the *id* rather than only on the resulting path,
    because the id is also an identity: it keys the index, names source text, and
    is what a link points at. One that cannot be a filename is not one this app
    can carry, whatever the path happens to resolve to today.

    Backslash is rejected alongside ``/`` because ``Path.parts`` does not split
    on it under POSIX, so ``a\\..\\b`` reads as one innocent component here and
    traverses on Windows.
    """
    if not raw or raw in {".", ".."}:
        return False
    if "/" in raw or "\\" in raw or "\x00" in raw:
        return False
    # A leading dot hides the file from the folder the user is invited to read.
    return not raw.startswith(".")


def contained(root: Path, name: str) -> Path:
    """``root/name.md``, or a refusal if that lands outside ``root``.

    The stores turn an id into a filename, so the id has to be checked rather
    than trusted. Traversal is not currently reachable — uvicorn percent-decodes
    the path before Starlette matches it, so a separator cannot be smuggled
    through a path parameter — but that is a property of the server, not of this
    code, and a store should be safe on its own terms.

    Containment rather than a check on the *shape* of the id, which was the
    first attempt and was wrong: these directories are Markdown the user is
    invited to edit, so a file they renamed by hand must still be readable and
    deletable. What actually matters is that the result stays in the directory,
    which is what this asserts.
    """
    target = (root / f"{name}.md").resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"{name!r} does not name a file in {root}.")
    return target


def _slug_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H%M%SZ")


def path_for(entry_id: str, created: datetime, root: Path) -> Path:
    """Where an entry with this id and timestamp belongs.

    Asserts containment rather than trusting the id, for the same reason
    :func:`contained` does and with the same failure mode if it does not: the id
    comes from frontmatter, and a rewrite triggered by unattended work would
    otherwise write wherever that id pointed.

    Not :func:`contained` itself — that composes ``root/name.md`` and this
    composes a dated directory beneath it — but the assertion is the same one.
    """
    if not usable_id(entry_id):
        raise ValueError(f"{entry_id!r} cannot name an entry file.")
    path = root / f"{created:%Y}" / f"{created:%m}" / f"{_slug_time(created)}-{entry_id}.md"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"{entry_id!r} does not name a file in {root}.")
    return path


def _as_datetime(value: object, fallback: datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    return fallback


def parse(path: Path, *, on_anomaly: Callable[[str, Path], None] | None = None) -> Entry:
    """Read one Markdown file into an :class:`Entry`.

    Tolerant by design: a file hand-edited into a partially invalid state still
    loads, because losing a thought to a schema error is unacceptable. That
    tolerance is why the id is checked here rather than being allowed to fail
    later — an id that cannot be a filename is replaced with one derived from the
    filename, so the entry survives and only its identity changes.

    ``on_anomaly`` is called with the rejected id and the path when that happens.
    Rebuilding passes a collector so the substitution is reported rather than
    made silently; a caller that does not care may omit it.
    """
    post = frontmatter.load(path)
    meta = post.metadata
    now = utcnow()
    created = _as_datetime(meta.get("created"), now)

    def _enum(cls, key, default):
        raw = meta.get(key)
        try:
            return cls(raw) if raw is not None else default
        except ValueError:
            return default

    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    themes = meta.get("themes") or []
    if isinstance(themes, str):
        themes = [themes]

    links: list[LinkRecord] = []
    for raw in meta.get("links") or []:
        if isinstance(raw, dict) and raw.get("to"):
            try:
                links.append(LinkRecord(**raw))
            except Exception:  # noqa: BLE001 - one bad link must not lose the entry
                continue

    # The filename already ends in the id it was written with, so it is the
    # natural fallback — and it is a real path component, so it is safe by
    # construction in a way the frontmatter is not.
    from_name = path.stem.split("-")[-1]
    declared = str(meta.get("id") or from_name)
    if usable_id(declared):
        entry_id = declared
    else:
        entry_id = from_name if usable_id(from_name) else new_id()
        if on_anomaly is not None:
            on_anomaly(declared, path)

    return Entry(
        id=entry_id,
        created=created,
        updated=_as_datetime(meta.get("updated"), created),
        kind=_enum(EntryKind, "kind", EntryKind.NOTE),
        provenance=_enum(Provenance, "provenance", Provenance.SELF),
        parent=meta.get("parent") or None,
        source_id=meta.get("source_id") or None,
        anchor=meta.get("anchor") or None,
        source_url=meta.get("source_url") or None,
        reply_kind=_enum(ReplyKind, "reply_kind", None),
        tags=[str(t) for t in tags],
        # Absent means promoted: everything written before the bar existed, and
        # everything the writer typed themselves, belongs in the Stream.
        promoted=meta.get("promoted") is not False,
        theme_labels=[str(t) for t in themes],
        links=links,
        filed=_as_datetime(meta.get("filed"), None) if meta.get("filed") else None,
        judged=_as_datetime(meta.get("judged"), None) if meta.get("judged") else None,
        body=post.content.strip(),
    )


def write(entry: Entry, root: Path, *, preserve_extra_from: Path | None = None) -> Path:
    """Serialise an entry to disk atomically.

    The temp-file-then-rename dance means a crash mid-write can never leave a
    truncated journal entry — the reader either sees the old file or the new one.
    """
    path = path_for(entry.id, entry.created, root)
    path.parent.mkdir(parents=True, exist_ok=True)

    extra: dict = {}
    if preserve_extra_from and preserve_extra_from.exists():
        existing = frontmatter.load(preserve_extra_from).metadata
        extra = {k: v for k, v in existing.items() if k not in _KNOWN_KEYS}

    meta = {
        "id": entry.id,
        "created": entry.created.isoformat(),
        "updated": entry.updated.isoformat(),
        "kind": entry.kind.value,
        "provenance": entry.provenance.value,
        **({"parent": entry.parent} if entry.parent else {}),
        **({"source_id": entry.source_id} if entry.source_id else {}),
        **({"anchor": entry.anchor} if entry.anchor else {}),
        **({"source_url": entry.source_url} if entry.source_url else {}),
        **({"reply_kind": entry.reply_kind.value} if entry.reply_kind else {}),
        "tags": entry.tags,
        # Only written when false. A key on every entry saying "yes, show this"
        # is noise in a file the user is meant to be able to read.
        **({} if entry.promoted else {"promoted": False}),
        **({"themes": entry.theme_labels} if entry.theme_labels else {}),
        **({"links": [link.model_dump() for link in entry.links]} if entry.links else {}),
        **({"filed": entry.filed.isoformat()} if entry.filed else {}),
        **({"judged": entry.judged.isoformat()} if entry.judged else {}),
        **extra,
    }

    post = frontmatter.Post(entry.body, **meta)
    payload = frontmatter.dumps(post)

    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def walk(root: Path) -> Iterator[Path]:
    """Yield every entry file, oldest path first.

    Symlinks are skipped rather than followed. The journal is a folder people are
    invited to edit and sync, so a link in it may point anywhere on the disk, and
    following one would read a file the journal does not contain — indexing its
    contents as though the writer had authored them.
    """
    if not root.exists():
        return
    resolved_root = root.resolve()
    for path in sorted(root.rglob("*.md")):
        if path.is_symlink():
            continue
        if not path.resolve().is_relative_to(resolved_root):
            continue
        yield path
