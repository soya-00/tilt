"""The journal service — the one place files and index are kept in step.

Routes and agents talk to this, never to the store directly. Every mutation
writes Markdown first and updates the index second, so a crash between the two
loses an index row (rebuildable) rather than a thought (not).
"""

from __future__ import annotations

from pathlib import Path

from tilt.models import (
    Entry,
    EntryCreate,
    EntryKind,
    EntryUpdate,
    Provenance,
    ReplyKind,
    Thread,
    utcnow,
)
from tilt.store import files, search
from tilt.store.index import Index


class Journal:
    def __init__(self, data_dir: Path, index: Index) -> None:
        self.data_dir = data_dir
        self.entries_root = data_dir / "entries"
        self.index = index

    # ---------------------------------------------------------------- writing

    def create(self, payload: EntryCreate) -> Entry:
        now = utcnow()
        entry = Entry(
            id=files.new_id(),
            created=now,
            updated=now,
            kind=payload.kind,
            provenance=payload.provenance,
            parent=payload.parent,
            source_url=payload.source_url,
            tags=payload.tags,
            body=payload.body.strip(),
        )
        path = files.write(entry, self.entries_root)
        self.index.upsert(entry, path)
        return entry

    def add_reply(self, parent_id: str, body: str, reply_kind: ReplyKind) -> Entry:
        """Machine output lands as a real entry threaded under its parent.

        Replies are entries rather than a separate table so they are searchable,
        survive in Markdown, and can themselves be connected later.
        """
        now = utcnow()
        entry = Entry(
            id=files.new_id(),
            created=now,
            updated=now,
            kind=EntryKind.REPLY,
            provenance=Provenance.SELF,
            parent=parent_id,
            reply_kind=reply_kind,
            body=body.strip(),
        )
        path = files.write(entry, self.entries_root)
        self.index.upsert(entry, path)
        return entry

    def update(self, entry_id: str, payload: EntryUpdate) -> Entry | None:
        entry = self.index.get(entry_id)
        if entry is None:
            return None
        if payload.body is not None:
            entry.body = payload.body.strip()
        if payload.tags is not None:
            entry.tags = payload.tags
        entry.updated = utcnow()
        old_path = self.index.path_of(entry_id)
        path = files.write(entry, self.entries_root, preserve_extra_from=old_path)
        self.index.upsert(entry, path)
        return entry

    def delete(self, entry_id: str) -> bool:
        path = self.index.path_of(entry_id)
        # Cascade to replies so deleting a thought does not orphan its replies.
        for child in self.index.children([entry_id]).get(entry_id, []):
            self.delete(child.id)
        if not self.index.delete(entry_id):
            return False
        if path and path.exists():
            path.unlink()
        return True

    # ---------------------------------------------------------------- reading

    def get(self, entry_id: str) -> Entry | None:
        return self.index.get(entry_id)

    def stream(self, *, limit: int = 50, before: str | None = None) -> list[Thread]:
        roots = self.index.roots(limit=limit, before=before)
        replies = self.index.children([r.id for r in roots])
        return [Thread(entry=r, replies=replies.get(r.id, [])) for r in roots]

    def thread(self, entry_id: str) -> Thread | None:
        entry = self.index.get(entry_id)
        if entry is None:
            return None
        return Thread(entry=entry, replies=self.index.children([entry_id]).get(entry_id, []))

    def search(self, query: str, *, limit: int = 20) -> list[Entry]:
        return search.search(self.index, query, limit=limit)

    def context_for(self, entry_id: str, *, limit: int = 12) -> list[Entry]:
        """Prior entries an agent should consider when responding to this one.

        Blends lexical neighbours of the entry with plain recency, so an agent
        reply is grounded in related history rather than the last thing typed.
        """
        entry = self.index.get(entry_id)
        if entry is None:
            return []
        related = [e for e in self.search(entry.body, limit=limit) if e.id != entry_id]
        recent = self.index.recent_bodies(limit=limit, exclude=entry_id)
        merged: dict[str, Entry] = {}
        for candidate in [*related, *recent]:
            if candidate.kind is not EntryKind.REPLY:
                merged.setdefault(candidate.id, candidate)
        return list(merged.values())[:limit]

    # --------------------------------------------------------------- lifecycle

    def rebuild(self) -> int:
        return self.index.rebuild(self.entries_root)
