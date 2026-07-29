"""Theme-keeper — the nightly tidy of the folders nobody maintains.

Themes are minted one entry at a time by a model that is shown the existing list
and asked to reuse a name when one fits. Over months that drifts: "Attention"
and "Attention Economy" and "Paying Attention" end up as three folders holding
one subject, and the sidebar slowly stops meaning anything.

Nothing here invents structure. It only repairs what accumulated filing did to
it, in three passes that get progressively more expensive:

1. **Prune** — a theme with no members is nothing but a row. Free.
2. **Dormancy** — mark what has gone quiet, so the sidebar shows which subjects
   are live and which you have set down. Pure SQL, no model call.
3. **Merge** — near-duplicate names, judged by the model and folded together.
   The only step that costs anything, and the only one that changes your files.

The full re-clustering in the plan — every entry embedded, clustered over the
vectors, themes split as well as merged — now has the embedding layer it was
waiting for, and is simply not built yet. Splitting on lexical evidence alone
would be guesswork, and a bad split scatters a subject across two folders with
no way for the user to see why. Merging is the half that was honest without
vectors.
"""

from __future__ import annotations

import re
from datetime import timedelta

from tilt.agents.base import AgentError
from tilt.agents.ledger import BudgetExceeded, MeteredProvider
from tilt.agents.parsing import extract_json
from tilt.journal import Journal
from tilt.models import JobSummary, Theme, ThemeStatus, utcnow

JOB = "themes"

DORMANT_AFTER = timedelta(days=60)
"""Quiet for two months is dormant. Long enough that a fortnight away from a
subject does not grey it out, short enough to be visible within a season."""

MAX_PAIRS = 6
"""Merge candidates judged per run. Bounds the cost of a nightly job, and a
sidebar that reorganises six folders at a time is already at the limit of what
someone can look at in the morning and still recognise."""

STOPWORDS = frozenset({"and", "of", "the", "in", "on", "a", "an", "to", "for", "as"})

SYSTEM = """You maintain the folders of a private journal.

Each pair below is two folder names that might be the same subject. Respond with
JSON only — no prose, no code fence:

{"merges": [{"n": 1, "keep": "Attention"}]}

Rules:
- Merge only when the two names describe ONE subject the writer thinks about.
  "Attention" and "Attention Economy" are one subject. "Deep Work" and "Deep
  Learning" are not, despite the shared word.
- "keep" must be exactly one of the two names in that pair — the one that better
  names the subject as a whole. Prefer the broader name over the narrower one.
- Return an empty list when none of them should be merged. Splitting a subject
  is invisible to the writer; merging two real subjects destroys a distinction
  they were making. When unsure, do not merge."""


def tokens(label: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", label.lower()) if w and w not in STOPWORDS}


def candidates(themes: list[Theme], *, limit: int = MAX_PAIRS) -> list[tuple[Theme, Theme]]:
    """Theme pairs whose names are close enough to be worth asking about.

    Purely lexical, and deliberately so: this is a filter in front of the model,
    not a decision. It has to be cheap enough to run over every pair and strict
    enough that the model is not asked about "Sleep" and "Software".
    """
    pairs: list[tuple[float, Theme, Theme]] = []
    for i, a in enumerate(themes):
        ta = tokens(a.label)
        if not ta:
            continue
        for b in themes[i + 1 :]:
            tb = tokens(b.label)
            if not tb:
                continue
            # Two folders the user has each named by hand are two distinctions
            # they chose to make. Never propose collapsing them.
            if a.pinned_label and b.pinned_label:
                continue
            shared = ta & tb
            if not shared:
                continue
            overlap = len(shared) / len(ta | tb)
            if ta <= tb or tb <= ta or overlap >= 0.5:
                pairs.append((overlap, a, b))

    pairs.sort(key=lambda p: -p[0])
    return [(a, b) for _, a, b in pairs[:limit]]


def build_prompt(pairs: list[tuple[Theme, Theme]]) -> str:
    listed = "\n".join(
        f"[{i + 1}] {a.label} ({a.count} entries) | {b.label} ({b.count} entries)"
        for i, (a, b) in enumerate(pairs)
    )
    return f"TASK: merge folders\n\nPAIRS:\n{listed}"


def survivor(a: Theme, b: Theme, choice: str) -> tuple[Theme, Theme]:
    """Decide which of a pair keeps its name and its identity.

    A name the user typed always wins, whatever the model prefers — renaming a
    folder is the one instruction this app takes literally. Otherwise the
    model's choice stands, and a choice matching neither name falls back to the
    larger folder, which moves the fewest entries.
    """
    if a.pinned_label:
        return a, b
    if b.pinned_label:
        return b, a
    picked = choice.strip().casefold()
    if picked and picked == b.label.casefold():
        return b, a
    if picked and picked == a.label.casefold():
        return a, b
    return (a, b) if a.count >= b.count else (b, a)


def apply_merge(journal: Journal, keep: Theme, drop: Theme) -> int:
    """Fold ``drop`` into ``keep``, in the index and on disk.

    The frontmatter rewrite is not optional bookkeeping. Themes are restored
    from each entry's own Markdown on boot, so a merge that touched only SQLite
    would resurrect the folder it just removed the next time Tilt started.
    """
    moving = journal.index.entries_in_theme(drop.id)
    journal.index.merge_themes(keep.id, drop.id)
    for entry in moving:
        current = journal.index.themes_for([entry.id]).get(entry.id, [])
        journal.set_themes(entry.id, [t.label for t in current])
    return len(moving)


async def keep_themes(
    journal: Journal, provider: MeteredProvider, *, interactive: bool = False
) -> JobSummary:
    index = journal.index
    index.prune_empty_themes()

    themes = index.themes()
    summary = JobSummary(job=JOB, considered=len(themes))

    cutoff = utcnow() - DORMANT_AFTER
    for theme in themes:
        wanted = (
            ThemeStatus.DORMANT
            if theme.last_active is not None and theme.last_active < cutoff
            else ThemeStatus.ACTIVE
        )
        if wanted is not theme.status:
            index.set_theme_status(theme.id, wanted)
        if wanted is ThemeStatus.DORMANT:
            summary.dormant += 1

    pairs = candidates(themes)
    if pairs:
        try:
            summary.merged = await _merge(journal, provider, pairs, interactive=interactive)
        except BudgetExceeded:
            summary.paused = True
        except AgentError:
            # Tidying is never worth failing the run over. Dormancy above has
            # already been applied and costs nothing to have done.
            pass

    summary.detail = _describe(summary)
    return summary


async def _merge(
    journal: Journal,
    provider: MeteredProvider,
    pairs: list[tuple[Theme, Theme]],
    *,
    interactive: bool,
) -> int:
    completion = await provider.complete(
        build_prompt(pairs), job=JOB, system=SYSTEM, interactive=interactive
    )
    payload = extract_json(completion.text)
    proposals = payload.get("merges") if isinstance(payload, dict) else None
    if not isinstance(proposals, list):
        return 0

    merged = 0
    # A theme folded away in one step must not be an endpoint of a later one.
    spent: set[str] = set()
    for item in proposals:
        if not isinstance(item, dict):
            continue
        n = item.get("n")
        if not isinstance(n, int) or not 1 <= n <= len(pairs):
            continue
        a, b = pairs[n - 1]
        if a.id in spent or b.id in spent:
            continue
        keep, drop = survivor(a, b, str(item.get("keep", "")))
        apply_merge(journal, keep, drop)
        spent.update({a.id, b.id})
        merged += 1
    return merged


def _describe(summary: JobSummary) -> str:
    parts = [f"{summary.considered} folders"]
    if summary.merged:
        parts.append(f"{summary.merged} merged")
    if summary.dormant:
        parts.append(f"{summary.dormant} dormant")
    if summary.paused:
        parts.append("paused at the spending ceiling")
    return ", ".join(parts)
