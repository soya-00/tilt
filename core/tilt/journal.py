"""The journal service — the one place files and index are kept in step.

Routes and agents talk to this, never to the store directly. Every mutation
writes Markdown first and updates the index second, so a crash between the two
loses an index row (rebuildable) rather than a thought (not).
"""

from __future__ import annotations

from pathlib import Path

from tilt.embed import Embedder
from tilt.models import (
    Entry,
    EntryCreate,
    EntryKind,
    EntryUpdate,
    LinkedEntry,
    LinkRecord,
    Provenance,
    ReplyKind,
    Theme,
    Thread,
    utcnow,
)
from tilt.store import files, search
from tilt.store.index import Index
from tilt.store.vectors import VectorStore

NEIGHBOUR_FLOOR = 0.55
"""How alike two entries must be before one is offered as context for the other.

A nearest-neighbour query always returns something. On a journal circling one
subject the sixth-nearest entry may have nothing to do with the fifth, and
handing it to the connector spends a model call proposing a link between two
unrelated thoughts. Cosine on a normalised embedding is comparable across
journals, so a fixed floor is meaningful here in a way a fixed rank is not."""


class Journal:
    def __init__(
        self,
        data_dir: Path,
        index: Index,
        vectors: VectorStore | None = None,
        embedder: Embedder | None = None,
        support_dir: Path | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.entries_root = data_dir / "entries"
        # Where the machine's own files are, as against the ones you wrote.
        # Carried here because the unattended jobs get a journal and nothing
        # else, and one of them needs to read the settings the app wrote. It
        # used to rebuild that path by hand and had been reading a directory
        # that stopped existing when the support folder was split out.
        self.support_dir = support_dir or index.path.parent
        self.index = index
        # Both optional and both absent without a key. Every use is guarded, so
        # the journal is the same object with or without them — retrieval is
        # simply narrower.
        self.vectors = vectors
        self.embedder = embedder

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
        """Edit an entry's body or tags, keeping everything else it carries.

        Read from disk, not from the index. Folders, connections and the agent's
        considered-marks have no SQLite columns and live only in frontmatter, so
        an entry loaded from the index carries them empty — and writing that back
        would erase them. Fixing a typo would quietly cost the entry its filing
        and every connection anyone had found for it.
        """
        entry = self._from_disk(entry_id)
        if entry is None:
            return None
        if payload.body is not None:
            entry.body = payload.body.strip()
        if payload.tags is not None:
            entry.tags = payload.tags
        entry.updated = utcnow()
        self._rewrite(entry)
        return entry

    def add_card(
        self,
        *,
        source_id: str,
        body: str,
        anchor: str | None = None,
        card_kind: str = "idea",
        promoted: bool = True,
    ) -> Entry:
        """An atomic idea extracted from a source, nested beneath it.

        Cards are children of the source so the Stream shows one item rather
        than a flood, and they carry ``provenance=source`` so the connector can
        always tell borrowed thinking from your own.

        Born already filed. A card belongs to the source it came out of, not to
        a folder of your preoccupations — filing borrowed material into those
        would dilute every one of them. It still gets judged, because meeting
        your earlier thinking is the entire point of pulling it out.
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
            filed=now,
            promoted=promoted,
            body=body.strip(),
        )
        path = files.write(entry, self.entries_root)
        self.index.upsert(entry, path)
        self.index.mark_considered(entry.id, filed=True)
        return entry

    def source_text_path(self, source_id: str) -> Path:
        return self.data_dir / "sources" / f"{source_id}.txt"

    def write_source_text(self, source_id: str, text: str) -> Path:
        """Keep the untruncated source beside the journal.

        Only a bounded window is ever sent to a model, but the original must
        survive intact — it is the thing the cards are anchored to.
        """
        path = self.source_text_path(source_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def read_source_text(self, source_id: str) -> str | None:
        path = self.source_text_path(source_id)
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

    def rename_theme(self, theme_id: str, label: str) -> Theme | None:
        """Rename a folder, in the index and in every entry filed under it.

        The rewrite is the whole job, exactly as it is for a delete. Folders are
        rebuilt from each entry's own Markdown on boot, so a rename confined to
        SQLite survives only until the next restart — at which point the old
        name is recreated from the frontmatter that still carries it, the
        entries follow it there, and the renamed folder is left standing empty
        beside it. Renaming twice would leave three.
        """
        theme = self.index.rename_theme(theme_id, label)
        if theme is None:
            return None
        for entry in self.index.entries_in_theme(theme_id):
            current = self.index.themes_for([entry.id]).get(entry.id, [])
            self.set_themes(entry.id, [t.label for t in current])
        return theme

    def delete_theme(self, theme_id: str) -> bool:
        """Drop a folder, keeping every entry that was in it.

        The agent's guess about how a body of writing divides up is sometimes
        just wrong, and this is the only way to say so. What is removed is the
        categorisation, never the thought: each affected entry is rewritten with
        the folder struck from its frontmatter and is otherwise untouched.

        The rewrite is the whole job, not bookkeeping around it. Themes are
        rebuilt from each entry's own Markdown on boot, so a delete confined to
        SQLite would resurrect the folder the next time Tilt started.
        """
        members = self.index.entries_in_theme(theme_id)
        if not self.index.delete_theme(theme_id):
            return False
        for entry in members:
            remaining = self.index.themes_for([entry.id]).get(entry.id, [])
            self.set_themes(entry.id, [t.label for t in remaining])
        return True

    def mark_considered(self, entry_id: str, *, filed: bool = False, judged: bool = False) -> None:
        """Record that an agent has finished with this entry, on disk and in the index.

        "Looked, found nothing" is the only agent result that leaves no other
        trace — no folder, no connection — and it is not free to reach. Keeping
        it in SQLite alone meant that throwing away the index, which the design
        explicitly invites, silently re-billed the whole journal.

        So it goes in the entry's own frontmatter alongside the folders and
        connections, which are agent output for the same reason.
        """
        self.index.mark_considered(entry_id, filed=filed, judged=judged)
        entry = self._from_disk(entry_id)
        if entry is None:
            return
        now = utcnow()
        stamped = entry.model_copy(
            update={
                "filed": entry.filed or now if filed else entry.filed,
                "judged": entry.judged or now if judged else entry.judged,
            }
        )
        if (stamped.filed, stamped.judged) != (entry.filed, entry.judged):
            self._rewrite(stamped)

    def record_link(self, entry_id: str, record: LinkRecord) -> None:
        """Append a connection to the source entry's frontmatter."""
        entry = self._from_disk(entry_id)
        if entry is None:
            return
        if any(existing.to == record.to for existing in entry.links):
            return
        entry.links = [*entry.links, record]
        self._rewrite(entry)

    def dismiss_link(self, link_id: str) -> bool:
        """Reject a connection, on disk as well as in the index.

        The index keeps the row as a tombstone so the pair is never proposed
        again. That promise only holds as long as the index does, and the index
        is explicitly disposable — so the dismissal has to reach Markdown too,
        or rebuilding from disk would restore the link and the connector would
        pay to judge the same pair a second time.

        Both endpoints are rewritten. A link is undirected and either entry may
        be the one carrying the record.
        """
        link = self.index.get_link(link_id)
        if link is None or not self.index.dismiss_link(link_id):
            return False
        for entry_id, other_id in ((link.src_id, link.dst_id), (link.dst_id, link.src_id)):
            entry = self._from_disk(entry_id)
            if entry is None:
                continue
            records = [
                r.model_copy(update={"dismissed": True}) if r.to == other_id else r
                for r in entry.links
            ]
            if records != entry.links:
                entry.links = records
                self._rewrite(entry)
        return True

    def delete(self, entry_id: str) -> bool:
        entry = self.index.get(entry_id)
        path = self.index.path_of(entry_id)
        # Cascade to replies so deleting a thought does not orphan its replies.
        for child in self.index.children([entry_id]).get(entry_id, []):
            self.delete(child.id)
        if not self.index.delete(entry_id):
            return False
        if path and path.exists():
            path.unlink()
        # A source keeps its untruncated text in a second file. Leaving that
        # behind would hoard a transcript nothing can reach or show again.
        if entry is not None and entry.kind is EntryKind.SOURCE:
            self.source_text_path(entry_id).unlink(missing_ok=True)
        # Otherwise the store accumulates vectors for thoughts that no longer
        # exist, and they keep turning up as neighbours of the ones that do.
        if self.vectors is not None:
            self.vectors.forget(entry_id)
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

        threads = []
        for e in entries:
            children = replies.get(e.id, [])
            shown = [c for c in children if c.promoted]
            threads.append(
                Thread(
                    entry=e,
                    replies=shown,
                    quiet=len(children) - len(shown),
                    themes=themes.get(e.id, []),
                    links=[
                        LinkedEntry(link=link, entry=other)
                        for link, other in links.get(e.id, [])
                    ],
                )
            )
        return threads

    def search(self, query: str, *, limit: int = 20) -> list[Entry]:
        return search.search(
            self.index, query, limit=limit, vectors=self.vectors, embedder=self.embedder
        )

    def neighbours(self, entry_id: str, *, limit: int = 6) -> list[Entry]:
        """Entries nearest this one by meaning, or nothing without a key.

        The one path to a candidate that does not require shared vocabulary.
        Everything else here finds entries that use the same words or were
        written at the same time, which is why `bridges to` — the link kind that
        by definition spans two vocabularies — could not fire on anything older
        than the recency window before this existed.

        Reads a stored vector rather than embedding the entry again: the text
        has not changed since the job embedded it, and paying to ask the same
        question twice is the sort of thing that makes a feature expensive for
        no reason.
        """
        if self.vectors is None or self.embedder is None:
            return []
        vector = self.vectors.get(entry_id, self.embedder.signature)
        if vector is None:
            return []
        near = self.vectors.nearest(
            vector,
            self.embedder.signature,
            limit=limit,
            exclude=entry_id,
            floor=NEIGHBOUR_FLOOR,
        )
        found = [self.index.get(eid) for eid, _ in near]
        return [e for e in found if e is not None]

    def context_for(self, entry_id: str, *, limit: int = 12) -> list[Entry]:
        """Prior entries an agent should consider when responding to this one.

        Three sources, each covering a failure of the other two. Lexical
        neighbours find the same words; recency finds what you are working on
        now; vector neighbours find what is *about* the same thing while sharing
        no words, which neither of the others can reach.

        The total stays bounded rather than growing by a third. Every candidate
        is prompt tokens on every connect call, and the vector slice is taken
        out of the budget rather than added to it — a more expensive connector
        that ran less often would be a worse trade than a sharper one.
        """
        entry = self.index.get(entry_id)
        if entry is None:
            return []
        near = self.neighbours(entry_id, limit=max(1, limit // 3))
        related = [e for e in self.search(entry.body, limit=limit) if e.id != entry_id]
        recent = self.index.recent_bodies(limit=limit, exclude=entry_id)
        merged: dict[str, Entry] = {}
        for candidate in [*near, *related, *recent]:
            if candidate.kind is EntryKind.REPLY:
                continue
            # Two ideas lifted out of the same document are not a discovery.
            # They were adjacent in one argument before Tilt ever saw them.
            if entry.source_id and candidate.source_id == entry.source_id:
                continue
            if candidate.id == entry.source_id or candidate.source_id == entry.id:
                continue
            merged.setdefault(candidate.id, candidate)

        ranked = sorted(merged.values(), key=lambda c: self._pairing(entry, c))
        return ranked[:limit]

    @staticmethod
    def _pairing(entry: Entry, candidate: Entry) -> int:
        """How much a pairing is worth looking at, lowest first.

        Your own thinking meeting itself is the thing this app is for. Your
        thinking meeting something you read comes next — that is the payoff of
        ingesting anything. Two sources agreeing with each other is not your
        insight, so it goes last and is only judged when nothing better is
        waiting.
        """
        borrowed = sum(
            e.provenance is Provenance.SOURCE for e in (entry, candidate)
        )
        return borrowed

    # --------------------------------------------------------------- lifecycle

    def rebuild(self) -> int:
        return self.index.rebuild(self.entries_root)
