"""The weekly look back, and mostly the decision not to have one.

Every journal app eventually grows a weekly review, and most of them are the
same mistake: a summary produced on a schedule is produced on the weeks that
held nothing as well as the weeks that held something. After a month of "here
is what you wrote about" the writer has learned to skip it, and the one week
that mattered goes past unread with the rest.

So this pass does not summarise. It **notices**, and it costs nothing to do —
two queries against what the index and the vector store already hold, no model
call, no charge. Almost every week it finds nothing and says nothing, and the
interface is unchanged.

When it does find something it writes one sentence and stops there. The
synthesis is a button on that sentence: the writer asks, the reflection agent
reads the entries behind it, and *that* is what costs money. The scout's
discipline, turned inward — gather for free, spend once, and only behind
something a person chose.

Two things count as worth noticing, and the shortness of that list is the
design:

1. **You contradicted yourself.** The `contradiction` link kind is already
   reserved for two things *you* wrote, deliberately, so that the word keeps
   its weight. Its existence is the finding; nothing further needs judging.
2. **An old question came back.** A question a source left you with, months
   ago, that this week's writing came near — measured with the same cosine
   floor the connector uses for its candidates.

Everything else a weekly pass might report — how much you wrote, which folder
grew, what you tagged most — is a statistic about activity rather than an
observation about thinking, and this app is not a productivity dashboard.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from tilt.agents.ledger import MeteredProvider
from tilt.journal import NEIGHBOUR_FLOOR, Journal
from tilt.models import Entry, JobSummary, Notice, utcnow
from tilt.store.files import new_id

log = logging.getLogger(__name__)

JOB = "week"

WINDOW = timedelta(days=7)
"""How far back a pass looks. The interval it runs on, so nothing is missed and
nothing is counted twice."""

SETTLED = timedelta(days=30)
"""How old a question must be to count as having come back.

A question asked on Tuesday and circled on Thursday is not a return, it is a
train of thought. A month is long enough that returning to it is a fact about
you rather than about the week."""


def contradiction(journal: Journal, since) -> Notice | None:
    """You wrote two things that pull against each other.

    Costs nothing: the connector already judged this pair and paid for it, and
    the link kind is only ever used between two things the writer wrote. All
    this does is notice that one appeared and that nobody has been told.
    """
    for link in journal.index.links_of_kind("contradiction", since=since.isoformat()):
        left = journal.index.get(link.src_id)
        right = journal.index.get(link.dst_id)
        if left is None or right is None:
            continue
        return Notice(
            id=new_id(),
            kind="contradiction",
            body=(
                "You wrote two things this week that pull against each other: "
                f"{opening(left)} — and — {opening(right)}"
            ),
            entry_ids=[left.id, right.id],
            subject=f"link:{link.id}",
            created=utcnow(),
        )
    return None


def returning_question(journal: Journal, since) -> Notice | None:
    """An old open question this week's writing came near.

    Needs vectors, and does nothing without them rather than falling back to
    shared words — a question and the entry that circles it months later rarely
    use the same vocabulary, which is the whole reason this is measured by
    meaning.
    """
    if journal.vectors is None or journal.embedder is None:
        return None

    recent = {e.id: e for e in journal.index.written_since(since.isoformat())}
    if not recent:
        return None

    signature = journal.embedder.signature
    settled = utcnow() - SETTLED
    for question in journal.index.open_questions(limit=24):
        if question.created > settled:
            continue
        vector = journal.vectors.get(question.id, signature)
        if vector is None:
            continue
        for entry_id, _ in journal.vectors.nearest(
            vector, signature, limit=8, exclude=question.id, floor=NEIGHBOUR_FLOOR
        ):
            entry = recent.get(entry_id)
            if entry is None:
                continue
            return Notice(
                id=new_id(),
                kind="question",
                body=(
                    "Something you read left you with a question "
                    f"{ago(question)}, and this week you came back to it: "
                    f"{opening(question)}"
                ),
                entry_ids=[question.id, entry.id],
                subject=f"question:{question.id}",
                created=utcnow(),
            )
    return None


def opening(entry: Entry) -> str:
    first = next((line.strip() for line in entry.body.splitlines() if line.strip()), "")
    return first[:160]


def ago(entry: Entry) -> str:
    days = max(1, (utcnow() - entry.created).days)
    if days < 60:
        return f"{days} days ago"
    return f"{days // 30} months ago"


async def look_back(journal: Journal, provider: MeteredProvider) -> JobSummary:
    """One pass. Finds nothing, usually, and that is a result rather than a failure.

    ``provider`` is unused and the signature keeps it anyway, which is what lets
    the runner treat every job alike and the interface trigger this one by name.
    Nothing here can spend: that is not an optimisation, it is the reason the
    pass is allowed to run unattended every week.
    """
    since = utcnow() - WINDOW
    summary = JobSummary(job=JOB)

    notice = contradiction(journal, since) or returning_question(journal, since)
    if notice is None:
        summary.detail = "Nothing this week that you would not already know."
        return summary

    if not journal.index.add_notice(notice):
        # Already raised. True again is not new, and a notice repeated every
        # Sunday is one nobody reads by the third time.
        summary.detail = "Nothing new; what turned up has already been said."
        return summary

    summary.proposed = 1
    summary.detail = notice.body
    log.info("weekly notice: %s", notice.kind)
    return summary
