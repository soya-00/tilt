"""Domain models.

These mirror the Markdown frontmatter exactly. The SQLite index is a derived
cache; every field that matters is reconstructable from the files on disk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class EntryKind(StrEnum):
    NOTE = "note"
    """Something you wrote."""
    CAPTURE = "capture"
    """A quick fragment or a pasted link."""
    SOURCE = "source"
    """An ingested artifact — video, article, transcript."""
    CARD = "card"
    """An atomic idea extracted from a source."""
    REPLY = "reply"
    """Machine output threaded under a parent entry."""


class Provenance(StrEnum):
    SELF = "self"
    """You thought this."""
    SOURCE = "source"
    """Someone else thought this and you ingested it."""


class ReplyKind(StrEnum):
    REFLECTION = "reflection"
    CONNECTION = "connection"
    QUESTION = "question"


class Entry(BaseModel):
    id: str
    created: datetime
    updated: datetime
    kind: EntryKind = EntryKind.NOTE
    provenance: Provenance = Provenance.SELF
    parent: str | None = None
    source_id: str | None = None
    anchor: str | None = None
    source_url: str | None = None
    reply_kind: ReplyKind | None = None
    tags: list[str] = Field(default_factory=list)
    body: str = ""

    @property
    def is_machine(self) -> bool:
        """Drives the monospace 'machine voice' treatment in the UI."""
        return self.kind is EntryKind.REPLY


class EntryCreate(BaseModel):
    body: str
    kind: EntryKind = EntryKind.NOTE
    provenance: Provenance = Provenance.SELF
    parent: str | None = None
    source_url: str | None = None
    tags: list[str] = Field(default_factory=list)


class EntryUpdate(BaseModel):
    body: str | None = None
    tags: list[str] | None = None


class Thread(BaseModel):
    """An entry with its machine replies, which is how the Stream renders."""

    entry: Entry
    replies: list[Entry] = Field(default_factory=list)


class AgentRun(BaseModel):
    id: str
    job: str
    model: str
    status: str
    started: datetime
    finished: datetime | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    error: str | None = None
