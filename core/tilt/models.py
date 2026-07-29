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


class LinkRecord(BaseModel):
    """A connection as stored in the entry's own Markdown frontmatter.

    Links live with the entry rather than only in SQLite, so the connective
    tissue between thoughts survives losing the index.
    """

    to: str
    kind: str
    why: str = ""
    dismissed: bool = False


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

    # Whether this earned a place in the Stream. Only extracted cards are ever
    # demoted: ingesting is meant to be filtering, not accumulation, and a
    # thirty-card video that shows you thirty cards has filtered nothing. A
    # demoted card is quiet, never gone — still indexed, still searchable.
    promoted: bool = True

    # Agent-derived structure, persisted to frontmatter so a full index rebuild
    # restores it. Without this, deleting index.db would silently discard every
    # folder assignment and connection the agent ever made.
    theme_labels: list[str] = Field(default_factory=list)
    links: list[LinkRecord] = Field(default_factory=list)

    # When each agent last finished with this entry. Also frontmatter, and for
    # the same reason: "examined, found nothing" is a result that cost money to
    # reach, and it is the one result that leaves no other trace. An entry
    # missing these looks untouched, and the sweep would judge it again.
    filed: datetime | None = None
    judged: datetime | None = None

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


class LinkKind(StrEnum):
    """How two thoughts relate. Ordered loosely by how much it earns a mention."""

    ECHO = "echo"
    """You are circling the same idea again."""
    ELABORATION = "elaboration"
    """One develops the other."""
    CONTRADICTION = "contradiction"
    """You have changed your mind, or not noticed that you disagree.

    Only ever between two things *you* wrote. Reserved deliberately: the word
    should keep its weight, and it only means anything when both sides are
    yours."""
    COUNTERPOINT = "counterpoint"
    """Something you read pulls against something you think.

    Distinct from a contradiction, and the distinction is the point. Reading an
    argument you disagree with is not changing your mind and should not be
    logged as though it were — holding two opposed views at once is how you
    work out what you actually believe."""
    BRIDGE = "bridge"
    """Two unrelated areas that turn out to touch."""


class Link(BaseModel):
    """A judged connection between two entries."""

    id: str
    src_id: str
    dst_id: str
    kind: LinkKind
    rationale: str
    created: datetime
    dismissed: bool = False


class ThemeStatus(StrEnum):
    ACTIVE = "active"
    DORMANT = "dormant"
    """Nothing new has fallen into it for a long time.

    Not deleted and not hidden. A preoccupation you have set down is part of the
    record of how your thinking moved, and losing it would flatten the timeline
    into a picture of only this month.
    """


class Theme(BaseModel):
    """A category the agent discovered and named. Browsed like a folder.

    Themes are emergent: you never create one. They are named from the thoughts
    that fall into them, and they can be renamed by you — at which point the
    name is sticky and the agent stops overwriting it.
    """

    id: str
    label: str
    description: str = ""
    created: datetime
    updated: datetime
    pinned_label: bool = False
    """Set when the user renames it, so the agent never renames it back."""
    count: int = 0
    status: ThemeStatus = ThemeStatus.ACTIVE
    last_active: datetime | None = None
    """When its most recent member was written. Derived, never stored — the
    entries are the truth and a cached copy of this would drift from them."""


class TagCount(BaseModel):
    tag: str
    count: int


class LinkedEntry(BaseModel):
    """A connection as the Stream renders it: the link plus what it points at."""

    link: Link
    entry: Entry


class Thread(BaseModel):
    """An entry with its machine replies, which is how the Stream renders."""

    entry: Entry
    replies: list[Entry] = Field(default_factory=list)
    themes: list[Theme] = Field(default_factory=list)
    links: list[LinkedEntry] = Field(default_factory=list)

    quiet: int = 0
    """Ideas from this source that did not clear the bar.

    Reported rather than hidden. They are still indexed and still turn up in
    search — the writer should know the rest of the source is there, without
    the Stream handing them thirty cards to read."""


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
    detail: str = ""
    """What the run actually did, in one human sentence.

    Only unattended work fills this in. A scheduled job that finished with
    status ``ok`` and no further explanation is indistinguishable from one that
    silently did nothing, and the whole point of watching a 3am job is to be
    able to tell those apart the next morning."""


class JobSummary(BaseModel):
    """The outcome of one scheduled pass, returned when it is triggered by hand."""

    job: str
    considered: int = 0
    """Entries or themes the job looked at."""
    filed: int = 0
    connected: int = 0
    merged: int = 0
    dormant: int = 0
    detail: str = ""
    paused: bool = False
    """Set when the budget ceiling stopped the run partway.

    Distinct from an error: the work is unfinished but nothing is broken, and
    the next run picks up exactly where this one stopped."""


class Activity(BaseModel):
    """What the agent did while you were not looking."""

    since: datetime
    filed: int = 0
    connected: int = 0
