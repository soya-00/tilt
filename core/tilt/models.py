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


MAX_BODY = 100_000
"""An entry is something a person typed, and this is far past the longest
anyone types in one. Long source material goes through ``/ingest``, which has
its own limit and its own explanation for exceeding it. Bounded at all because
the alternative is an unbounded read into memory from anyone who can reach the
service."""

MAX_TAGS = 32
"""More than the categoriser ever proposes. A bound rather than a rule."""


class EntryCreate(BaseModel):
    body: str = Field(max_length=MAX_BODY)
    kind: EntryKind = EntryKind.NOTE
    provenance: Provenance = Provenance.SELF
    parent: str | None = Field(default=None, max_length=64)
    source_url: str | None = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)


class EntryUpdate(BaseModel):
    body: str | None = Field(default=None, max_length=MAX_BODY)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)


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


class Conflict(BaseModel):
    """Two files on disk claiming the same entry.

    A sync client's "(conflicted copy)" carries the id of the file it copied,
    so both are the same entry as far as the index is concerned and one of them
    silently loses. Reported rather than resolved: the app has no business
    renaming or merging somebody's files, and a conflict you can see is one you
    can settle.
    """

    entry_id: str
    kept: str
    """The file that was indexed — the one with the newer ``updated``."""
    ignored: str
    """The file that was not. Still on disk, untouched."""


class ThemeSplit(BaseModel):
    """A folder that has turned into two subjects, offered rather than applied.

    The keeper merges folders on its own because a wrong merge is visible and
    the next pass can still undo it. A split has no such recovery: it names its
    halves distinctly, so nothing will ever look at them as a pair again. So
    this is where the machine's part ends — it says what it found, names both
    halves, and waits.

    Kept in the index rather than in Markdown, which means a deleted index
    forgets a dismissal. The same is already true of a folder name you typed by
    hand, and the fix for both is the same durable theme record nobody has built
    yet.
    """

    id: str
    theme_id: str
    theme_label: str = ""
    """The folder as it is named now, carried so the proposal reads on its own."""
    keep_label: str
    """What the larger half would be called — usually the existing name."""
    move_label: str
    """What the smaller half would be called, once it is its own folder."""
    keep_ids: list[str] = Field(default_factory=list)
    move_ids: list[str] = Field(default_factory=list)
    separation: float = 0.0
    """How far apart the two halves measured. Kept so a proposal can be argued
    with rather than only accepted or refused."""
    created: datetime


class Misfiled(BaseModel):
    """An entry that sits closer to a folder it is not in.

    Filing happens one entry at a time and is therefore path dependent: an entry
    written before a subject had a folder lands in whichever folder was nearest
    that week and stays there. This is the repair, and like every other repair
    in this app that changes what you wrote, it is offered rather than done.

    Cheaper to be wrong about than a split — it relocates one entry, keeps its
    other folders, and costs one dismissal — which is why it does not buy a
    model call to check itself.
    """

    id: str
    entry_id: str
    opening: str = ""
    """The entry's first line, so the proposal reads without a second query."""
    from_id: str
    from_label: str
    to_id: str
    to_label: str
    margin: float = 0.0
    """How much closer the other folder measured. Kept so a proposal can be
    argued with rather than only accepted or refused."""
    created: datetime


class Notice(BaseModel):
    """Something worth a second look, found without spending anything.

    The weekly pass writes at most one of these and usually writes none. That
    is the whole design: a weekly review that arrives every week regardless of
    whether the week held anything teaches you to stop reading it, and then the
    one week that mattered goes past unread too.

    A notice is not the synthesis. It is the observation that there might be one
    worth paying for, and the paying happens when the writer asks.
    """

    id: str
    kind: str
    """``contradiction`` — two things you wrote that pull against each other —
    or ``question``, an old open question this week's writing came near."""
    body: str
    """One sentence, in the machine's own voice."""
    entry_ids: list[str] = Field(default_factory=list)
    """What the notice is about, and what a synthesis would read."""
    subject: str = ""
    """A stable identity for the finding — the link or the question behind it —
    so the same observation is never raised twice."""
    created: datetime
    dismissed: bool = False


class JobSummary(BaseModel):
    """The outcome of one scheduled pass, returned when it is triggered by hand."""

    job: str
    considered: int = 0
    """Entries or themes the job looked at."""
    filed: int = 0
    connected: int = 0
    merged: int = 0
    dormant: int = 0
    proposed: int = 0
    """Suggestions left for the writer rather than changes made.

    Separate from the counters above, and the distinction is the point: those
    say what the run did, this says what it is waiting on. A split is never
    applied by a job."""
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


class GraphNode(BaseModel):
    """One point in the constellation.

    Entries and themes share a list rather than living in two, because the
    thing being drawn is one graph — a thought belonging to a subject is the
    same kind of relation as a thought meeting another thought.
    """

    id: str
    label: str
    kind: str
    """``entry``, ``card``, ``source``, or ``theme``."""
    provenance: str = "self"
    created: datetime | None = None
    weight: int = 1
    """Members, for a theme. Always 1 for an entry — a graph that sizes nodes by
    how much you wrote would reward length rather than significance."""


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: str
    """A link kind, or ``member`` for an entry's place in a theme."""
    rationale: str = ""


class Graph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    truncated: bool = False
    """Set when the node cap was reached.

    Said rather than hidden: an unfiltered graph past a few hundred nodes is an
    unreadable hairball, and quietly drawing half of one is worse than drawing
    a bounded one and admitting it."""
    total: int = 0
    """Entries the filter matched before the cap, so the view can name the
    number it is not showing instead of implying there is nothing more."""


class Artifact(BaseModel):
    """Something the agent made that is not an entry — a diagram, for now.

    Deliberately not an ``Entry``. A diagram is a reading of your thoughts, not
    a thought: putting it in the Stream would mean the agent could write into
    the record you keep, and having it filed into folders and connected to other
    entries would let a machine drawing start showing up as evidence of what you
    think. It lives beside the journal instead.
    """

    id: str
    kind: str
    """The Mermaid diagram type — ``flowchart``, ``mindmap``, and so on."""
    path: str = ""
    """Where it sits on disk. Empty until it has been saved."""
    title: str = ""
    body: str = ""
    """The Mermaid source."""
    note: str = ""
    """One sentence from the agent on the structure it saw."""
    subject_ids: list[str] = Field(default_factory=list)
    created: datetime


class BriefOrigin(StrEnum):
    SCOUT = "scout"
    """The agent went looking and found it."""
    YOU = "you"
    """You put it here yourself, which is what stops this being the machine's
    list rather than yours."""


class BriefItem(BaseModel):
    """Reading that has not happened yet.

    Not an entry, and deliberately so. Nothing here is a thought — it is
    something that might become one. An item leaves this list by being read,
    at which point the usual distil path turns it into a source entry and the
    promotion bar decides what any of it contributes.

    Not a task list either, whatever it looks like from outside. Nothing in it
    is completed; the only way out is to become journal content or to be
    dismissed as not worth it, and an item that simply sits here is in no way
    a failure.
    """

    id: str
    title: str = ""
    url: str | None = None
    why: str = ""
    """What made this worth proposing — the question it might answer, or your
    own note to yourself. Without it a list of links is unreadable a week
    later, because the reason you saved something is the first thing to go."""
    origin: BriefOrigin = BriefOrigin.YOU
    tags: list[str] = Field(default_factory=list)
    """The same vocabulary entries use, not a second one growing beside it.

    Snapped against the tags already in the journal before being stored, so a
    proposed "Attention" lands on the "attention" you have been using. What it
    buys is that a candidate can be recognised at a glance as belonging to
    something you already think about."""
    created: datetime
    dismissed: bool = False
    """Kept rather than deleted, so the scout never proposes it again. The same
    bargain a dismissed connection strikes."""
    path: str = ""
