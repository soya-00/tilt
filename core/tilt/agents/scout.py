"""The scout — the first thing in Tilt that goes and looks.

Everything else in the journal originates with the writer. That makes this the
feature most at risk of becoming the thing the app exists not to be, so two
rules hold it in shape:

**It never writes to the journal.** It proposes; you decide. A finding lands in
the brief and stays there until you read it, at which point the ordinary distil
path runs and the promotion bar judges what any of it contributes. Nothing
arrives in the Stream because a machine thought it might be interesting.

**The cheap pass filters for the expensive one.** Gathering costs nothing —
feeds are XML and search is a tool call the model makes anyway. Triage is one
model call over titles and abstracts for everything gathered, and it is asked
for at most two. Reading the thing is the expensive step, and it is never taken
without you. A scout that finds something every day is not being selective, so
returning nothing is the expected outcome rather than a failure.
"""

from __future__ import annotations

import logging

import httpx

from tilt.agents.ledger import MeteredProvider
from tilt.agents.parsing import extract_json
from tilt.feeds import Finding, arxiv_query, fetch, parse
from tilt.journal import Journal
from tilt.store.brief import normalise

log = logging.getLogger(__name__)

JOB = "scout"

MAX_PICKS = 2
"""The most the triage pass may choose from one run.

A ceiling rather than a target. The brief is a place you look when you have
time, and three arrivals a day makes it a backlog inside a week."""

MAX_CANDIDATES = 40
"""How many findings triage will read at once. Bounds the prompt, and past this
the model is skimming rather than judging."""

SYSTEM = """You choose what is worth someone's reading time.

{persona}

You are given what a writer has left unresolved, the subjects they keep
returning to, and a list of things that turned up today. Respond with JSON only,
no prose, no code fence:

{{"picks": [{{"n": 3, "why": "one clause on what this answers"}}]}}

Rules:
- At most {max_picks}. Usually zero. Most of what turns up on any given day
  answers nothing anybody asked, and proposing it anyway is how a useful list
  becomes one nobody opens.
- Pick only what speaks to a specific OPEN QUESTION or SUBJECT below. "Related
  to something they care about" is not enough — it has to look like it might
  actually resolve, complicate, or sharpen one of them.
- "why" names the question or subject it speaks to. Not a summary of the item:
  the writer can read the title themselves, and what they cannot see is why you
  thought of them.
- Prefer something that argues against what they think over something that
  agrees. Agreement adds nothing they do not already have.
- An empty list is a good answer and needs no apology."""


def build_prompt(
    questions: list[str], subjects: list[str], candidates: list[Finding]
) -> str:
    asked = "\n".join(f"- {q}" for q in questions) or "(none yet)"
    areas = ", ".join(subjects) or "(none yet)"
    listed = "\n\n".join(
        f"[{n}] {c.title}\n{c.summary[:400]}" for n, c in enumerate(candidates)
    )
    return (
        f"TASK: scout\n\nOPEN QUESTIONS:\n{asked}\n\n"
        f"SUBJECTS:\n{areas}\n\nTURNED UP TODAY:\n{listed}"
    )


def interests(journal: Journal, *, limit: int = 8) -> tuple[list[str], list[str]]:
    """What to go looking on behalf of.

    Questions first, because a question is a gap and a subject is only a topic.
    Folders are the fallback that keeps this working on a journal which has
    ingested nothing yet and therefore has no questions on record.
    """
    questions = [
        " ".join(e.body.split())[:200] for e in journal.index.open_questions(limit=limit)
    ]
    subjects = [t.label for t in journal.index.themes()[:limit]]
    return questions, subjects


async def gather(
    journal: Journal, feeds: list[str], *, client: httpx.AsyncClient | None = None
) -> list[Finding]:
    """Everything that turned up, from every configured source. No model call.

    A feed that is down, slow, or serving malformed XML costs itself and
    nothing else — the pass continues with whatever the others returned.
    """
    questions, subjects = interests(journal)
    terms = subjects or [w for q in questions for w in q.split()[:3]]

    urls = list(feeds)
    if terms:
        query = arxiv_query(terms)
        if query:
            urls.append(query)

    seen: set[str] = set()
    out: list[Finding] = []
    for url in urls:
        try:
            body = await fetch(url, client=client)
        except Exception as exc:  # noqa: BLE001 - one feed, not the pass
            log.warning("feed unreachable %s: %s", url, exc)
            continue
        for finding in parse(body, source=url):
            key = normalise(finding.url)
            if key and key not in seen:
                seen.add(key)
                out.append(finding)
    return out


def unseen(candidates: list[Finding], known: set[str]) -> list[Finding]:
    """Drop anything already read or already refused.

    Without this the scout offers the same paper every morning, which is the
    fastest way to teach someone to stop opening a list.
    """
    return [c for c in candidates if normalise(c.url) not in known]


async def triage(
    journal: Journal,
    provider: MeteredProvider,
    candidates: list[Finding],
    *,
    persona_instruction: str = "",
    interactive: bool = False,
) -> list[tuple[Finding, str]]:
    """One model call over everything gathered. Returns what to propose, and why.

    Non-interactive by default: this runs unattended, so it stops at 80% of the
    monthly ceiling and leaves the rest for work you are present for.
    """
    if not candidates:
        return []

    window = candidates[:MAX_CANDIDATES]
    questions, subjects = interests(journal)
    if not questions and not subjects:
        # Nothing written yet to go looking on behalf of. Proposing anything
        # here would be proposing it at random.
        return []

    completion = await provider.complete(
        build_prompt(questions, subjects, window),
        job=JOB,
        system=SYSTEM.format(persona=persona_instruction, max_picks=MAX_PICKS),
        interactive=interactive,
    )

    payload = extract_json(completion.text)
    if not isinstance(payload, dict):
        return []

    picks = payload.get("picks")
    if not isinstance(picks, list):
        return []

    chosen: list[tuple[Finding, str]] = []
    for pick in picks[:MAX_PICKS]:
        if not isinstance(pick, dict):
            continue
        index = pick.get("n")
        if not isinstance(index, int) or not 0 <= index < len(window):
            continue
        why = " ".join(str(pick.get("why") or "").split())[:300]
        chosen.append((window[index], why))
    return chosen
