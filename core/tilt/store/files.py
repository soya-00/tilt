"""Markdown file store — the source of truth.

Every entry is one Markdown file with YAML frontmatter, readable by Obsidian,
greppable, and diffable in git. The SQLite index in :mod:`tilt.store.index` is a
cache that can be thrown away and rebuilt from this directory at any time.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
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


def _slug_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H%M%SZ")


def path_for(entry_id: str, created: datetime, root: Path) -> Path:
    return root / f"{created:%Y}" / f"{created:%m}" / f"{_slug_time(created)}-{entry_id}.md"


def _as_datetime(value: object, fallback: datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    return fallback


def parse(path: Path) -> Entry:
    """Read one Markdown file into an :class:`Entry`.

    Tolerant by design: a file hand-edited into a partially invalid state still
    loads, because losing a thought to a schema error is unacceptable.
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

    return Entry(
        id=str(meta.get("id") or path.stem.split("-")[-1]),
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
    """Yield every entry file, oldest path first."""
    if not root.exists():
        return
    yield from sorted(root.rglob("*.md"))
