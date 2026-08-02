"""Entries the filing got wrong, found after the fact.

Filing happens one entry at a time: the model is shown the folders that exist
and asked to reuse a name or mint one. That is the right shape — it is cheap,
it happens as you write, and it never asks you anything — but it is **path
dependent**. The first entries create the vocabulary and everything after gets
bent towards it, so an entry written in a week when a subject had no folder yet
lands in whichever folder was nearest at the time and stays there.

Nothing has ever revisited that. The keeper merges folders that drifted apart
and splits ones that became two, both of which operate on whole folders. This
is the same repair at the other scale: one entry, in the wrong place.

Why this rather than clustering from scratch, which would find the same thing
and more: a from-scratch clustering proposes an entire sidebar at once, with no
way to accept part of it, no way to respect a name you typed, and a `k` nobody
has measured. This proposes one entry moving one folder — small enough to judge
in a sentence, and wrong at a cost of one dismissal.

The evidence is the same evidence the split pass uses, read the other way
round: a folder's centroid is where its subject sits, and an entry far from the
centroid of every folder it is in, but close to another, is one that was filed
before the better folder existed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from tilt.jobs.split import dot, normalise
from tilt.journal import Journal
from tilt.models import Entry, Misfiled, Theme, utcnow
from tilt.store.files import new_id

log = logging.getLogger(__name__)

MIN_MEMBERS = 5
"""Members a folder needs before its centroid means anything.

The average of three entries is not a subject's position, it is three entries.
Folders below this are neither compared against nor moved out of."""

MAX_PROPOSALS = 3
"""Proposals per run.

More than the split pass allows, because a move is reviewable in a sentence and
costs one dismissal if it is wrong. Still small: a stream of these is a queue,
which is the one thing this app refuses to become."""

MARGIN = 0.10
"""How much closer another folder must be before the entry is worth mentioning.

Measured before it was chosen, in ``test_misfiled_margin.py``, and the two
cases separate further apart than any threshold in this app so far — a
correctly filed entry does not merely score low, it scores **negative**, because
being inside a subject and being outside it are different signs of the same
quantity.

    correctly filed, folders 0.0 to 0.65 apart, 5 to 40 members   worst −0.12
    mis-filed, the same range                                    weakest +0.17

Anything between 0 and 0.17 would work on planted data. 0.10 rather than
something nearer zero because real folders overlap in ways planted ones do not:
an entry can genuinely belong to two subjects, and the honest reading of a
small positive margin is "this is on a boundary", which is not worth
interrupting anyone about.

What this does not prove is where a real embedder puts a real journal. Same
limitation as the split threshold, same fix, and it is written down as owed."""


@dataclass
class Move:
    """One entry, and the folder it sits closer to."""

    entry: Entry
    from_theme: Theme
    to_theme: Theme
    margin: float


def summed(vectors: list[list[float]]) -> list[float]:
    total = [0.0] * len(vectors[0])
    for vector in vectors:
        for i, x in enumerate(vector):
            total[i] += x
    return total


def without(total: list[float], vector: list[float]) -> list[float]:
    """The folder's summed vector with one member removed.

    An entry is part of its own folder's average, so it pulls that average
    towards itself — in a folder of six, by a sixth — and a mis-filed entry
    therefore makes its own folder look like a better fit than it is.

    What that costs was measured rather than assumed, because the obvious claim
    is too strong: without leave-one-out the pass still finds 60 of 60 planted
    mis-filings in every case but one. Where it loses is the hard case — a small
    folder whose subject is barely distinct from its neighbour's — and there it
    misses 6 in 60. So this buys recall exactly where the evidence is thinnest,
    for arithmetic that costs nothing, rather than being the difference between
    working and not.

    Subtracting from the sum rather than re-averaging the others: same answer,
    O(1) per comparison instead of O(n).
    """
    return [t - v for t, v in zip(total, vector, strict=True)]


def belonging(vector: list[float], total: list[float], members: int) -> float:
    """How well one entry sits in a folder it is a member of.

    Zero when the folder has nothing else in it — a folder of one has no
    position of its own to compare against, and its only member is neither
    well nor badly filed.
    """
    if members < 2:
        return 0.0
    rest = without(total, vector)
    if not any(rest):
        return 0.0
    return dot(vector, normalise(rest))


def affinity(vector: list[float], total: list[float]) -> float:
    """How well an entry would sit in a folder it is not in."""
    if not any(total):
        return 0.0
    return dot(vector, normalise(total))


# ------------------------------------------------------------------- the pass


def look(journal: Journal, themes: list[Theme]) -> list[Move]:
    """Every entry that sits closer to a folder it is not in. Costs nothing.

    No model call, and that is a decision rather than an omission. The split
    pass buys a veto because a wrong split is unrecoverable — it names two
    halves distinctly and nothing looks at them together again. A wrong move
    here relocates one entry, keeps its other folders, and costs one dismissal.
    The margin was measured to separate the two cases by more than any other
    threshold in this app, so a second opinion would be paying to be told what
    the arithmetic already says.

    If real journals turn out messier than planted ones, the veto goes in here
    and the shape of the pass does not change.
    """
    if journal.vectors is None or journal.embedder is None:
        return []

    signature = journal.embedder.signature
    # Folders too small to have a position are neither compared against nor
    # moved out of: the average of three entries is three entries.
    big = [t for t in themes if t.count >= MIN_MEMBERS]
    if len(big) < 2:
        return []

    placed: dict[str, list[tuple[Entry, list[float]]]] = {}
    sums: dict[str, list[float]] = {}
    for theme in big:
        members = []
        for entry in journal.index.entries_in_theme(theme.id):
            vector = journal.vectors.get(entry.id, signature)
            if vector is not None:
                members.append((entry, normalise(vector)))
        if len(members) >= MIN_MEMBERS:
            placed[theme.id] = members
            sums[theme.id] = summed([v for _, v in members])

    by_id = {t.id: t for t in big if t.id in placed}
    found: list[Move] = []
    for theme_id, members in placed.items():
        for entry, vector in members:
            here = belonging(vector, sums[theme_id], len(members))
            for other_id, other_sum in sums.items():
                if other_id == theme_id:
                    continue
                # An entry can be in several folders at once, and "you would be
                # better off in a folder you are already in" is not a finding.
                if any(entry.id == e.id for e, _ in placed[other_id]):
                    continue
                margin = affinity(vector, other_sum) - here
                if margin >= MARGIN:
                    found.append(
                        Move(
                            entry=entry,
                            from_theme=by_id[theme_id],
                            to_theme=by_id[other_id],
                            margin=margin,
                        )
                    )

    # Strongest first, and at most one per entry: an entry that measures closer
    # to two other folders is one question, not two.
    found.sort(key=lambda m: -m.margin)
    seen: set[str] = set()
    best = []
    for move in found:
        if move.entry.id in seen:
            continue
        seen.add(move.entry.id)
        best.append(move)
    return best


def apply_move(journal: Journal, move: Misfiled) -> bool:
    """Refile one entry, in the index and on disk.

    The frontmatter rewrite is the whole job, exactly as it is for a merge, a
    split, a rename and a delete. Folders are rebuilt from each entry's own
    Markdown on boot, so a move confined to SQLite would be undone by the next
    restart — the entry would reappear in the folder it came from, because its
    file still says so.
    """
    entry = journal.index.get(move.entry_id)
    if entry is None:
        journal.index.clear_move(move.entry_id)
        return False

    current = journal.index.themes_for([move.entry_id]).get(move.entry_id, [])
    ids = [t.id for t in current if t.id != move.from_id]
    if move.to_id not in ids:
        ids.append(move.to_id)
    journal.index.set_entry_themes(move.entry_id, ids)

    labels = journal.index.themes_for([move.entry_id]).get(move.entry_id, [])
    journal.set_themes(move.entry_id, [t.label for t in labels])
    journal.index.clear_move(move.entry_id)
    log.info("moved %s from %s to %s", move.entry_id, move.from_label, move.to_label)
    return True


async def keep_filing(journal: Journal, themes: list[Theme]) -> int:
    """Record what the pass found, for the writer to decide on. Returns how many.

    Async and awaited beside the other keeper passes purely so it reads the same
    way; nothing here waits on anything, because nothing here spends.
    """
    proposals = look(journal, themes)[:MAX_PROPOSALS]
    now = utcnow()
    for move in proposals:
        journal.index.propose_move(
            Misfiled(
                id=new_id(),
                entry_id=move.entry.id,
                opening=opening(move.entry),
                from_id=move.from_theme.id,
                from_label=move.from_theme.label,
                to_id=move.to_theme.id,
                to_label=move.to_theme.label,
                margin=round(move.margin, 4),
                created=now,
            ),
            declined=journal.folders.load(),
        )
    return len(journal.index.pending_moves())


def opening(entry: Entry) -> str:
    """The first line of a thought, which is usually what it is about."""
    first = next((line.strip() for line in entry.body.splitlines() if line.strip()), "")
    return first[:200]
