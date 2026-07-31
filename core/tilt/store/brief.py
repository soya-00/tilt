"""The brief on disk — reading that has not happened yet.

Markdown for the same reason diagrams are, and stored the same way: a directory
of files, no schema version, no migration, and nothing that can drift from what
is on disk. A list of things you meant to read is worth as much as a diagram
and is cheaper to keep.

Dismissals are tombstones rather than deletions. The scout has to know what it
has already offered you or it proposes the same paper every morning, and "no"
is a fact about your reading worth keeping.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import frontmatter

from tilt.models import BriefItem, BriefOrigin, utcnow
from tilt.store.files import contained


def _created(value: object) -> datetime:
    """PyYAML turns a bare ISO timestamp into a datetime and leaves a quoted one
    a string, so both shapes turn up in a file a human may have edited."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return utcnow()


def _listed(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return [value] if value else []


def normalise(url: str | None) -> str:
    """The comparison key for "have I seen this already".

    Enough to catch the same thing arriving twice by different routes — a feed
    giving `http://arxiv.org/abs/2401.1v1` and a search giving
    `https://arxiv.org/abs/2401.1v1/` are one paper, and offering both would
    make the brief look broken on its second day.
    """
    if not url:
        return ""
    trimmed = url.strip().lower().rstrip("/")
    for prefix in ("https://", "http://", "www."):
        if trimmed.startswith(prefix):
            trimmed = trimmed[len(prefix) :]
    return trimmed


class BriefStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, item_id: str) -> Path:
        """The file for this id, checked rather than trusted.

        See :func:`tilt.store.files.contained` for why this is a check and not
        an assumption about how the web server parses a path.
        """
        return contained(self.root, item_id)

    def save(self, item: BriefItem) -> BriefItem:
        path = self._path(item.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(
            item.why,
            id=item.id,
            title=item.title,
            origin=item.origin.value,
            created=item.created.isoformat(),
            **({"url": item.url} if item.url else {}),
            **({"tags": item.tags} if item.tags else {}),
            **({"dismissed": True} if item.dismissed else {}),
        )

        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(frontmatter.dumps(post))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

        return item.model_copy(update={"path": str(path)})

    def load(self, item_id: str) -> BriefItem | None:
        """The item, or nothing.

        An id that could never have been minted is reported as absent rather
        than as an error: from the caller's side "no such item" and "not an id"
        want the same 404, and only a crafted request produces the second.
        """
        try:
            path = self._path(item_id)
        except ValueError:
            return None
        return self._parse(path) if path.exists() else None

    def all(self, *, include_dismissed: bool = False) -> list[BriefItem]:
        """Newest first. Dismissed items are hidden but not gone."""
        if not self.root.exists():
            return []
        found = []
        for path in self.root.glob("*.md"):
            try:
                item = self._parse(path)
            except Exception:
                # A file edited into invalid YAML costs that one item, not the
                # whole list.
                continue
            if item.dismissed and not include_dismissed:
                continue
            found.append(item)
        return sorted(found, key=lambda i: i.created, reverse=True)

    def seen(self) -> set[str]:
        """Every URL already offered, dismissed ones included.

        What stops the scout proposing the same thing every morning. Dismissed
        items count precisely because saying no to something once should not
        have to be done twice.
        """
        return {normalise(i.url) for i in self.all(include_dismissed=True) if i.url}

    def dismiss(self, item_id: str) -> BriefItem | None:
        item = self.load(item_id)
        if item is None:
            return None
        return self.save(item.model_copy(update={"dismissed": True}))

    def remove(self, item_id: str) -> bool:
        """Take an item out entirely.

        Used when it has been read: it is an entry in the journal now, and the
        journal remembers its URL, so the tombstone would be redundant. This is
        the one path that leaves no trace here, because it left a better one
        somewhere else.
        """
        try:
            path = self._path(item_id)
        except ValueError:
            return False
        if not path.exists():
            return False
        path.unlink()
        return True

    @staticmethod
    def _parse(path: Path) -> BriefItem:
        post = frontmatter.load(path)
        meta = post.metadata
        origin = str(meta.get("origin") or BriefOrigin.YOU.value)
        return BriefItem(
            id=str(meta.get("id") or path.stem),
            title=str(meta.get("title") or ""),
            url=str(meta["url"]) if meta.get("url") else None,
            why=post.content.strip(),
            origin=(
                BriefOrigin(origin)
                if origin in {o.value for o in BriefOrigin}
                else BriefOrigin.YOU
            ),
            # A hand-edited file may carry one tag as a bare string rather than
            # a list, which is what YAML does with `tags: attention`.
            tags=[str(t) for t in _listed(meta.get("tags"))],
            created=_created(meta.get("created")),
            dismissed=bool(meta.get("dismissed")),
            path=str(path),
        )
