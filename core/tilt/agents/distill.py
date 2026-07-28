"""Source distillation.

Takes a long text — a transcript, an article, pasted notes — and turns it into
a handful of atomic ideas that can join the same connection graph as your own
thoughts.

Two rules keep this from swamping the journal:

1. The source becomes ONE entry, not thirty. Its cards nest beneath it.
2. Cards are marked ``provenance=source``, so the Stream and the connector can
   always tell your thinking apart from material you merely read.

Long input is bounded before it reaches the model. A two-hour transcript would
otherwise blow the context window, cost a fortune, or both — the full text is
always kept on disk, but only a windowed excerpt is sent.
"""

from __future__ import annotations

import re

from tilt.agents.ledger import MeteredProvider
from tilt.agents.parsing import extract_json
from tilt.journal import Journal
from tilt.models import Entry, EntryCreate, EntryKind, Provenance
from tilt.persona import Persona

JOB = "distill"

MAX_CHARS = 24_000
"""Roughly 6k tokens. Comfortably inside any model's window, cheap, and enough
to characterise a source. The full text is never lost — it is stored beside the
entry."""

MAX_CARDS = 12

SYSTEM = """You distil source material for a private journal called Tilt.

{persona}

You are given something the writer read or watched — a transcript, an article,
notes. Respond with JSON only, no prose, no code fence:

{{"summary": "...", "cards": [{{"idea": "...", "anchor": "..."}}], "questions": ["..."]}}

Rules:
- "summary": two sentences at most, describing what this source argues.
- "cards": 5 to 12 ATOMIC ideas. One claim each, rewritten in plain language.
  Never a section heading, never "the author discusses X" — state the claim
  itself as a sentence that stands on its own.
- "anchor": a short verbatim quote or timestamp the idea came from, so the
  writer can find it again. Empty string if there is none.
- "questions": 0 to 3 things the source leaves genuinely unresolved.
- Extract ideas, not an outline. If the source says little, return few cards.
  A short honest list beats a padded one."""


def _window(text: str, limit: int = MAX_CHARS) -> str:
    """Bound the text sent to the model, keeping both ends.

    The opening states the thesis and the close usually states the conclusion;
    the middle is the most expendable part of a long transcript.
    """
    clean = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(clean) <= limit:
        return clean
    head = clean[: int(limit * 0.6)]
    tail = clean[-int(limit * 0.4) :]
    return f"{head}\n\n[… {len(clean) - limit:,} characters omitted …]\n\n{tail}"


def build_prompt(title: str, text: str) -> str:
    return f"TASK: distill\n\nTITLE:\n{title or '(untitled)'}\n\nSOURCE:\n{_window(text)}"


async def distill(
    journal: Journal,
    provider: MeteredProvider,
    *,
    title: str,
    text: str,
    origin_url: str | None = None,
    persona: Persona | None = None,
    interactive: bool = True,
) -> Entry | None:
    """Create a source entry and nest its extracted ideas beneath it.

    Returns the source entry. Cards are children, so the Stream renders the
    whole thing as one item rather than a flood.
    """
    body = text.strip()
    if not body:
        return None

    completion = await provider.complete(
        build_prompt(title, body),
        job=JOB,
        system=SYSTEM.format(persona=(persona or Persona()).as_instruction()),
        interactive=interactive,
    )
    payload = extract_json(completion.text)
    data = payload if isinstance(payload, dict) else {}

    summary = str(data.get("summary") or "").strip()
    label = title.strip() or "Untitled source"
    header = label + (f"\n\n{origin_url}" if origin_url else "")
    source = journal.create(
        EntryCreate(
            body=f"{header}\n\n{summary}".strip(),
            kind=EntryKind.SOURCE,
            provenance=Provenance.SOURCE,
            source_url=origin_url,
        )
    )

    # The full text lives beside the journal, never truncated.
    journal.write_source_text(source.id, body)

    cards = data.get("cards")
    if isinstance(cards, list):
        for card in cards[:MAX_CARDS]:
            if not isinstance(card, dict):
                continue
            idea = " ".join(str(card.get("idea", "")).split()).strip()
            if len(idea) < 8:
                continue
            journal.add_card(
                source_id=source.id,
                body=idea,
                anchor=" ".join(str(card.get("anchor", "")).split())[:200] or None,
            )

    questions = data.get("questions")
    if isinstance(questions, list):
        for question in questions[:3]:
            text_q = " ".join(str(question).split()).strip()
            if len(text_q) > 8:
                journal.add_card(source_id=source.id, body=text_q, card_kind="question")

    return journal.get(source.id)
