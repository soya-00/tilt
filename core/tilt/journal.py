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
    LinkedEntry,
    LinkRecord,
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

    def add_card(
        self,
        *,
        source_id: str,
        body: str,
        anchor: str | None = None,
        card_kind: str = "idea",
    ) -> Entry:
        """An atomic idea extracted from a source, nested beneath it.

        Cards are children of the source so the Stream shows one item rather
        than a flood, and they carry ``provenance=source`` so the connector can
        always tell borrowed thinking from your own.
        """
        now = utcnow()
        entry = Entry(
            id=files.new_id(),
            created=now,
            updated=now,
            kind=EntryKind.CARD,
            provenance=Provenance.SOURCE,
            parent=source_id,
            source_id=source_id,
            anchor=anchor,
            reply_kind=ReplyKind.QUESTION if card_kind == "question" else None,
            body=body.strip(),
        )
        path = files.write(entry, self.entries_root)
        self.index.upsert(entry, path)
        return entry

    def write_source_text(self, source_id: str, text: str) -> Path:
        """Keep the untruncated source beside the journal.

        Only a bounded window is ever sent to a model, but the original must
        survive intact — it is the thing the cards are anchored to.
        """
        path = self.data_dir / "sources" / f"{source_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def read_source_text(self, source_id: str) -> str | None:
        path = self.data_dir / "sources" / f"{source_id}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def _from_disk(self, entry_id: str) -> Entry | None:
        """Load an entry from its file rather than the index.

        `theme_labels` and `links` have no SQLite columns — they live only in
        frontmatter — so an entry read from the index carries them empty.
        Rewriting that back to disk would erase whatever a previous agent step
        had just written.
        """
        path = self.index.path_of(entry_id)
        if path and path.exists():
            return files.parse(path)
        return self.index.get(entry_id)

    def _rewrite(self, entry: Entry) -> None:
        """Persist an entry's frontmatter without touching its timestamps."""
        old_path = self.index.path_of(entry.id)
        path = files.write(entry, self.entries_root, preserve_extra_from=old_path)
        self.index.upsert(entry, path)

    def set_themes(self, entry_id: str, labels: list[str]) -> None:
        """Record folder membership in the entry's own Markdown.

        The SQLite row is the queryable copy; this is the durable one.
        """
        entry = self._from_disk(entry_id)
        if entry is None:
            return
        entry.theme_labels = labels
        self._rewrite(entry)

    def record_link(self, entry_id: str, record: LinkRecord) -> None:
        """Append a connection to the source entry's frontmatter."""
        entry = self._from_disk(entry_id)
        if entry is None:
            return
        if any(existing.to == record.to for existing in entry.links):
            return
        entry.links = [*entry.links, record]
        self._rewrite(entry)

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

    def stream(
        self,
        *,
        limit: int = 50,
        before: str | None = None,
        theme_id: str | None = None,
        tag: str | None = None,
        query: str | None = None,
    ) -> list[Thread]:
        if query and query.strip():
            # Search returns whole threads rather than bare hits, so a result
            # arrives with its folders, tags, and connections intact.
            hits = self.search(query, limit=limit)
            roots = [h for h in hits if h.kind is not EntryKind.REPLY]
            return self._hydrate(roots)
        roots = self.index.roots(limit=limit, before=before, theme_id=theme_id, tag=tag)
        return self._hydrate(roots)

    def thread(self, entry_id: str) -> Thread | None:
        entry = self.index.get(entry_id)
        if entry is None:
            return None
        return self._hydrate([entry])[0]

    def _hydrate(self, entries: list[Entry]) -> list[Thread]:
        """Attach replies, themes, and connections in three batched queries
        rather than per-entry lookups."""
        ids = [e.id for e in entries]
        replies = self.index.children(ids)
        themes = self.index.themes_for(ids)
        links = self.index.links_for(ids)
        return [
            Thread(
                entry=e,
                replies=replies.get(e.id, []),
                themes=themes.get(e.id, []),
                links=[
                    LinkedEntry(link=link, entry=other) for link, other in links.get(e.id, [])
                ],
            )
            for e in entries
        ]

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
