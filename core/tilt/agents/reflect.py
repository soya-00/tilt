"""The reflection job — Tilt's one agent call in the MVP.

Given an entry, it reads back what the entry is actually claiming, notes where
it echoes earlier writing, and asks one question. It never suggests an action:
the output is understanding, not a task.

Prompt sections are uppercase-labelled blocks so that both hosted and offline
providers can parse the same structure.
"""

from __future__ import annotations

from tilt.agents.ledger import MeteredProvider
from tilt.journal import Journal
from tilt.models import Entry, ReplyKind
from tilt.persona import Persona

JOB = "reflect"

SYSTEM = """You are the reflective faculty of a private journal called Tilt.

{persona}

Your purpose is to help the writer understand their own thinking. You are not an
assistant, a coach, or a productivity tool.

Rules:
- Never suggest tasks, next steps, action items, or things to do.
- Never praise, congratulate, or encourage. No "great insight", no "you've got this".
- Address the writer as "you". Use their own vocabulary, not yours.
- Name the claim underneath what they wrote, especially if they did not state it.
- If earlier entries are supplied and genuinely relate, say how — concretely,
  referencing the specific idea rather than gesturing at similarity.
- If they contradict something they wrote earlier, say so plainly.
- End with exactly one question that opens the thought further.
- Under 120 words. Plain prose, no headings, no bullet lists, no emoji.
- If the entry is too thin to say anything real about, say only that, briefly."""


def build_prompt(entry: Entry, context: list[Entry]) -> str:
    parts = [f"ENTRY:\n{entry.body}"]
    if context:
        rendered = "\n\n".join(
            f"[{e.created:%Y-%m-%d}] {e.body[:400]}" for e in context if e.body.strip()
        )
        if rendered:
            parts.append(f"EARLIER ENTRIES:\n{rendered}")
    return "\n\n".join(parts)


def system_prompt(persona: Persona | None = None) -> str:
    """The reflection instruction, carrying the agent's chosen identity."""
    return SYSTEM.format(persona=(persona or Persona()).as_instruction())


async def reflect_on(
    journal: Journal,
    provider: MeteredProvider,
    entry_id: str,
    *,
    persona: Persona | None = None,
    interactive: bool = True,
) -> Entry | None:
    """Generate a reflection and thread it under the entry.

    Returns ``None`` when the entry does not exist. Provider failures propagate:
    the caller decides how to surface them, and the ledger has already recorded
    the failed run.
    """
    entry = journal.get(entry_id)
    if entry is None:
        return None

    context = journal.context_for(entry_id)
    prompt = build_prompt(entry, context)
    completion = await provider.complete(
        prompt, job=JOB, system=system_prompt(persona), interactive=interactive
    )
    return journal.add_reply(entry_id, completion.text, ReplyKind.REFLECTION)
