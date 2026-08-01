"""Splitting a folder that turned into two subjects.

The keeper merges folders whose names have drifted apart and retires the ones
that have gone quiet. It has never split one, and the reason was written into
its docstring rather than into a ticket: splitting on lexical evidence alone is
guesswork, and a bad split scatters a subject across two folders with no way for
the writer to see why.

Vectors supply the evidence that was missing. They do not resolve the asymmetry
that made splitting the harder half. Merging has a safety rule — when unsure,
mint the duplicate — because a duplicate folder is visible in the sidebar and
the next pass can still fold it away. A split has no equivalent. It names its
two halves distinctly, so the merge pass will never look at them again, and
nothing else in the app puts a subject back together.

So nothing here changes a file. Every pass ends at a proposal, and the split
happens when someone clicks. That is the same bargain a proposed connection
strikes, for the same reason: the machine is allowed to notice, and the writer
decides what their own folders mean.

The order of the gates is the design. Counting members is free, reading vectors
is nearly free, arithmetic over them is cheap, and only a candidate that has
survived all three is worth a model call — the same shape as the scout, where
gathering is free and only a triaged handful costs anything.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from tilt.agents.ledger import MeteredProvider
from tilt.agents.parsing import extract_json
from tilt.journal import Journal
from tilt.models import Entry, Theme, ThemeSplit, utcnow
from tilt.store.files import new_id

log = logging.getLogger(__name__)

JOB = "themes"
"""The keeper's job name. This is one of its passes, not a job of its own —
it runs on the same nightly schedule, from the same folder list, and its cost
belongs on the same run."""

MIN_MEMBERS = 12
"""Entries a folder needs before a split is even considered.

A folder of six is not two subjects, it is six thoughts. The number is low
enough that a real division shows up within a season of writing and high enough
that the arithmetic below has something to work with."""

MIN_HALF = 5
"""Entries each half needs.

Without this the pass proposes 40/2 splits, which are not subjects — they are
the two entries that were furthest from the middle. Peeling those off would
leave the writer with a folder of two and no idea what it was for."""

MAX_MEMBERS = 500
"""Members considered, newest first.

Everything below is linear in the member count, so this is not about protecting
the run — it is that a folder of a thousand entries is not a folder anyone is
about to reorganise from a sidebar row, and the recent half is the part whose
shape the writer would recognise."""

ITERATIONS = 12
"""Lloyd iterations. Two clusters over a few hundred points converge well
inside this; the cap is there so an oscillating pair cannot spin."""

COVERAGE = 0.9
"""Fraction of a folder's members that must already be embedded.

A folder judged on two thirds of its entries is a folder judged on whichever
two thirds the hourly embed job happened to have reached, and the third it
could not see is exactly where a second subject would be hiding. Skipping is
free — the job runs again tomorrow, by which time the vectors exist."""

REGROWTH = 1.5
"""How much a folder must grow before a dismissed split is raised again.

Half as many entries again is arguably a different folder. Anything short of
that and asking a second time is not a new observation, it is nagging."""

SAMPLE = 6
"""Entries shown to the model from each half.

Enough to recognise a subject, few enough that the veto costs about what a
merge judgement costs. It reads openings rather than whole entries for the same
reason — what a thought is about is in its first line far more often than not."""

SEPARATION = 0.15
"""How much more alike each half must be than the halves are to each other.

Measured before it was chosen, in ``test_split_separation.py``, because the
number that matters is not what a real division scores — it is what a folder
about *one* subject scores. Two-means always returns two clusters, so a single
subject always produces some positive value, and the threshold has to clear
every one of them.

    one subject, 12 to 240 entries, tight or broad     worst 0.06
    one subject drifting along an axis, up to 4×       worst 0.11
    two subjects, centres only 0.65 apart              weakest 0.23
    two subjects, lopsided 22 and 8                    weakest 0.30

0.15 sits in the gap. It is also where the statistic stops: a single subject
stretched *eight* times along one axis scores 0.19, over the line, and no
threshold fixes that — at some point "one subject that moved a long way" and
"two subjects" are the same arrangement of points, and telling them apart is a
question about meaning rather than geometry. That case is pinned in the test
rather than left to be discovered, and it is the reason the model gets a veto
and the writer gets the click.

What none of this proves is where a real embedder puts a real journal. The
corpus is planted; the honest version needs a key and somebody's actual
writing, and it is written down as owed."""


def normalise(vector: list[float]) -> list[float]:
    """Unit length, so every dot product below is a cosine.

    The store keeps vectors normalised already and ``nearest`` relies on it.
    This repeats the work because the arithmetic here is only meaningful on unit
    vectors, and a silently unnormalised one would not fail — it would return a
    number that looks like a cosine and is not.
    """
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        return vector
    return [x / norm for x in vector]


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _add(into: list[float], vector: list[float]) -> None:
    for i, x in enumerate(vector):
        into[i] += x


def seeds(vectors: list[list[float]]) -> tuple[list[float], list[float]]:
    """Two starting centroids, chosen rather than drawn.

    Furthest-first: the member least like the folder's average, then the member
    least like *that*. Deterministic, which matters more here than the quality
    of the seed — a nightly job that proposed a different split each time it ran
    over an unchanged folder would be indistinguishable from noise, and no one
    would ever accept one.
    """
    dims = len(vectors[0])
    centre = [0.0] * dims
    for vector in vectors:
        _add(centre, vector)
    centre = normalise(centre)

    first = min(vectors, key=lambda v: dot(v, centre))
    second = min(vectors, key=lambda v: dot(v, first))
    return first, second


def two_means(vectors: list[list[float]]) -> list[int]:
    """Assign each member to one of two clusters. Returns 0/1 per member.

    Plain Lloyd's algorithm on unit vectors, which is spherical k-means: the
    assignment step is a dot product and the update step is a normalised sum.
    Written out rather than imported because the alternative is a numpy
    dependency for thirty lines of arithmetic that runs once a night.
    """
    dims = len(vectors[0])
    left, right = seeds(vectors)
    assignment = [0] * len(vectors)

    for _ in range(ITERATIONS):
        moved = False
        for i, vector in enumerate(vectors):
            side = 0 if dot(vector, left) >= dot(vector, right) else 1
            if side != assignment[i]:
                assignment[i] = side
                moved = True

        sums = ([0.0] * dims, [0.0] * dims)
        counts = [0, 0]
        for i, vector in enumerate(vectors):
            _add(sums[assignment[i]], vector)
            counts[assignment[i]] += 1

        # An empty cluster means the seeds were both inside one lobe. Nothing to
        # recover: the caller's balance gate will reject this anyway.
        if not counts[0] or not counts[1]:
            return assignment

        left, right = normalise(sums[0]), normalise(sums[1])
        if not moved:
            break

    return assignment


def separation(vectors: list[list[float]], assignment: list[int]) -> float:
    """How much more alike each half is than the two halves are to each other.

    ``mean cosine within a half − mean cosine across the halves``. Zero means
    the division is arbitrary; the larger it is, the more the folder is behaving
    like two things.

    Computed from the two cluster sums rather than from every pair. On unit
    vectors the sum of all pairwise dot products inside a set is
    ``|Σv|² − |S|`` — the square of the summed vector, less the diagonal terms
    each vector contributes with itself. That turns an O(n²) statistic into an
    O(n) one, exactly, with no sampling.
    """
    dims = len(vectors[0])
    sums = ([0.0] * dims, [0.0] * dims)
    counts = [0, 0]
    for i, vector in enumerate(vectors):
        _add(sums[assignment[i]], vector)
        counts[assignment[i]] += 1

    if counts[0] < 2 or counts[1] < 2:
        return 0.0

    pairs = 0
    total = 0.0
    for side in (0, 1):
        n = counts[side]
        total += dot(sums[side], sums[side]) - n
        pairs += n * (n - 1)
    within = total / pairs

    between = dot(sums[0], sums[1]) / (counts[0] * counts[1])
    return within - between


# ------------------------------------------------------------------ the veto

SYSTEM = """You maintain the folders of a private journal.

One folder has been measured as possibly holding two subjects rather than one.
Below are the folder's name and a sample of the entries on each side of the
proposed division. Respond with JSON only — no prose, no code fence:

{"split": true, "keep": "Attention", "move": "Sleep"}

or, when it should stay one folder:

{"split": false}

Rules:
- Split only when the two groups are about DIFFERENT subjects the writer thinks
  about separately. One subject approached from two angles is still one subject,
  and so is a subject the writer's view of has moved over time.
- "keep" names group A, "move" names group B. Use the writer's own vocabulary,
  and name what the entries are about rather than what they have in common.
- A wrong merge is visible in the sidebar and the next pass can still undo it. A
  wrong split scatters one subject across two folders and nothing ever puts it
  back together. When unsure, do not split."""


@dataclass
class Candidate:
    """A folder that measured as two, before anyone has judged whether it is."""

    theme: Theme
    keep: list[Entry]
    move: list[Entry]
    score: float


def build_prompt(candidate: Candidate) -> str:
    def sample(entries: list[Entry]) -> str:
        return "\n".join(f"- {opening(e)}" for e in entries[:SAMPLE])

    return (
        f"TASK: split a folder\n\nFOLDER: {candidate.theme.label} "
        f"({candidate.theme.count} entries)\n\n"
        f"GROUP A ({len(candidate.keep)} entries):\n{sample(candidate.keep)}\n\n"
        f"GROUP B ({len(candidate.move)} entries):\n{sample(candidate.move)}"
    )


def opening(entry: Entry) -> str:
    """The first line of a thought, which is usually what it is about."""
    first = next((line.strip() for line in entry.body.splitlines() if line.strip()), "")
    return first[:200]


# ------------------------------------------------------------- the free pass


def measure(journal: Journal, theme: Theme) -> Candidate | None:
    """Whether this folder looks like two, on evidence that costs nothing.

    Returns ``None`` at the first gate it fails, which is the common case and
    the intended one — this runs over every folder every night and is expected
    to find nothing almost always.
    """
    if journal.vectors is None or journal.embedder is None:
        return None

    members = journal.index.entries_in_theme(theme.id)[:MAX_MEMBERS]
    if len(members) < MIN_MEMBERS:
        return None

    signature = journal.embedder.signature
    placed: list[tuple[Entry, list[float]]] = []
    for entry in members:
        vector = journal.vectors.get(entry.id, signature)
        if vector is not None:
            placed.append((entry, normalise(vector)))

    if len(placed) < len(members) * COVERAGE or len(placed) < MIN_MEMBERS:
        return None

    vectors = [v for _, v in placed]
    assignment = two_means(vectors)
    sides = ([e for (e, _), a in zip(placed, assignment, strict=True) if a == 0],
             [e for (e, _), a in zip(placed, assignment, strict=True) if a == 1])
    if min(len(sides[0]), len(sides[1])) < MIN_HALF:
        return None

    score = separation(vectors, assignment)
    if score < SEPARATION:
        return None

    keep, move = sorted(sides, key=len, reverse=True)
    return Candidate(theme=theme, keep=keep, move=move, score=score)


def candidates(journal: Journal, themes: list[Theme]) -> list[Candidate]:
    """Every folder that measured as two, best-separated first.

    Folders already ruled on are not measured again until they have grown —
    a proposal you turned down is an answer, and asking nightly would make it
    one you have to keep giving.
    """
    found = []
    for theme in themes:
        if journal.index.split_settled(theme.id, members=theme.count, growth=REGROWTH):
            continue
        candidate = measure(journal, theme)
        if candidate is not None:
            found.append(candidate)
    return sorted(found, key=lambda c: -c.score)


# ------------------------------------------------------------------ the pass


async def propose_split(
    journal: Journal,
    provider: MeteredProvider,
    themes: list[Theme],
    *,
    interactive: bool = False,
) -> ThemeSplit | None:
    """One proposal at a time, and nothing on disk changes.

    The merge pass judges six pairs a run because six merges is still a sidebar
    you can recognise in the morning. One split is the limit here for a
    different reason: the merge pass can undo its own mistakes and this cannot,
    so the number of unreviewed splits in flight should be the smallest number
    that is not zero.
    """
    ranked = candidates(journal, themes)
    if not ranked:
        return None

    candidate = ranked[0]
    completion = await provider.complete(
        build_prompt(candidate), job=JOB, system=SYSTEM, interactive=interactive
    )
    payload = extract_json(completion.text)
    if not isinstance(payload, dict) or not payload.get("split"):
        log.info("split declined for %s at %.3f", candidate.theme.label, candidate.score)
        return None

    keep_label = str(payload.get("keep") or "").strip()
    move_label = str(payload.get("move") or "").strip()
    if not move_label or move_label.casefold() == keep_label.casefold():
        # Half a verdict is not one. A split with only one name would leave the
        # smaller folder called something the model did not choose.
        return None
    if move_label.casefold() == candidate.theme.label.casefold():
        # The model has decided the *smaller* half is the real subject and the
        # larger one is something else. That is a rename and a split at once,
        # and applying it would move the entries into the folder they are
        # already in. Refuse rather than half-do it.
        log.info("split of %s named the smaller half after the folder", candidate.theme.label)
        return None

    # A name the writer typed is never overwritten, exactly as in a merge. The
    # larger half keeps the folder, so it keeps the pinned name too.
    if candidate.theme.pinned_label or not keep_label:
        keep_label = candidate.theme.label

    split = ThemeSplit(
        id=new_id(),
        theme_id=candidate.theme.id,
        theme_label=candidate.theme.label,
        keep_label=keep_label[:80],
        move_label=move_label[:80],
        keep_ids=[e.id for e in candidate.keep],
        move_ids=[e.id for e in candidate.move],
        separation=round(candidate.score, 4),
        created=utcnow(),
    )
    return journal.index.propose_split(split, members=candidate.theme.count)


# ------------------------------------------------------------- the acceptance


def apply_split(journal: Journal, split: ThemeSplit) -> int:
    """Carry out a proposal the writer accepted. Returns entries moved.

    The mirror of :func:`tilt.jobs.themes.apply_merge`, and it inherits that
    function's one hard lesson: folders are rebuilt from each entry's own
    Markdown on boot, so membership that moved only in SQLite is undone by the
    next restart — the old folder is recreated from frontmatter that still names
    it and the entries follow it back.

    Only entries still filed under the folder are moved. A proposal made at 3am
    can be accepted at noon, by which time an entry may have been deleted or
    filed elsewhere, and neither is a reason to fail.
    """
    theme = journal.index.get_theme(split.theme_id)
    if theme is None:
        journal.index.clear_split(split.theme_id)
        return 0

    still_here = {e.id for e in journal.index.entries_in_theme(theme.id)}
    moving = [entry_id for entry_id in split.move_ids if entry_id in still_here]
    if not moving:
        journal.index.clear_split(theme.id)
        return 0

    now = utcnow()
    minted = journal.index.upsert_theme(
        Theme(id=new_id(), label=split.move_label, created=now, updated=now)
    )

    for entry_id in moving:
        current = journal.index.themes_for([entry_id]).get(entry_id, [])
        ids = [t.id for t in current if t.id != theme.id]
        ids.append(minted.id)
        journal.index.set_entry_themes(entry_id, ids)
        labels = journal.index.themes_for([entry_id]).get(entry_id, [])
        journal.set_themes(entry_id, [t.label for t in labels])

    # Renaming the larger half is part of the same decision, and goes through
    # the journal so it reaches the frontmatter too. It pins the label, which is
    # right: a name that arrived by way of a click is one the writer chose.
    if split.keep_label and split.keep_label != theme.label:
        journal.rename_theme(theme.id, split.keep_label)

    journal.index.clear_split(theme.id)
    log.info("split %s into %s and %s", theme.label, split.keep_label, split.move_label)
    return len(moving)
