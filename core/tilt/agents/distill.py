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

from tilt.agents.base import Reference
from tilt.agents.ledger import MeteredProvider
from tilt.agents.parsing import extract_json, keywords
from tilt.journal import Journal
from tilt.models import Entry, EntryCreate, EntryKind, Provenance
from tilt.persona import Persona

JOB = "distill"

MAX_CHARS = 24_000
"""Roughly 6k tokens. Comfortably inside any model's window, cheap, and enough
to characterise a source. The full text is never lost — it is stored beside the
entry."""

MAX_CARDS = 12

MAX_SUMMARY = 2_000
"""How long a source's description may be.

Generous for the two or three lines this asks for. The point is that there is a
ceiling at all: everything else the model returns here is clipped, and these
fields were the exception — bounded only from below, by a minimum length.

The text being bounded is the model's, and the model has been reading a page
chosen by whoever wrote the feed. An unbounded field is a page's budget for
writing into someone's journal."""

MAX_IDEA = 1_000
"""How long one extracted idea may be. A card is a thought, not a chapter."""

MAX_QUESTION = 500
"""How long an open question may be."""

SYSTEM = """You distil source material for a private journal called Tilt.

{persona}

You are given something the writer read or watched — a transcript, an article,
notes. Respond with JSON only, no prose, no code fence:

{{"summary": "...", "cards": [{{"idea": "...", "anchor": "...", "relevant": true}}],
 "questions": ["..."]}}

Rules:
- "summary": two sentences at most, describing what this source argues.
- "cards": 5 to 12 ATOMIC ideas. One claim each, rewritten in plain language.
  Never a section heading, never "the author discusses X" — state the claim
  itself as a sentence that stands on its own.
- "anchor": a short verbatim quote or timestamp the idea came from, so the
  writer can find it again. Empty string if there is none.
- "relevant": true only when this idea speaks to something under WHAT THEY
  ALREADY THINK — answering it, arguing with it, or sharpening it. Extract
  every idea worth having, but mark only these. A good source can have two.
  Marking everything relevant is the same as marking nothing.
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


def build_prompt(
    title: str,
    text: str,
    context: list[str] | None = None,
    *,
    reference: Reference | None = None,
) -> str:
    """Assemble the one call. The writer's own recent thinking goes in with it.

    Without it the model can extract but cannot judge — every idea in a good
    talk looks worth surfacing in isolation, and the whole point of the bar is
    that relevance is a question about *this* journal.
    """
    theirs = "\n".join(f"- {line}" for line in (context or [])) or "(nothing yet)"
    if text.strip():
        source = _window(text)
    elif reference is not None:
        verb = "Watch" if reference.kind == "video" else "Read"
        source = f"({verb} the attached {reference.kind}: {reference.url})"
    else:
        source = "(empty)"
    return (
        f"TASK: distill\n\nTITLE:\n{title or '(untitled)'}\n\n"
        f"WHAT THEY ALREADY THINK:\n{theirs}\n\n"
        f"SOURCE:\n{source}"
    )


def _context(journal: Journal, title: str, text: str, *, limit: int = 8) -> list[str]:
    """The writer's own writing nearest this source, as one line each.

    Folders first — they are the standing preoccupations — then whatever the
    source's own language finds. Only entries the writer wrote: measuring a
    source's relevance against other sources tells you nothing about them.
    """
    lines = [f"(a folder of theirs) {t.label}" for t in journal.index.themes()[:4]]
    for entry in journal.search(f"{title} {text[:2000]}", limit=limit):
        if entry.provenance is Provenance.SELF and entry.kind is not EntryKind.REPLY:
            lines.append(" ".join(entry.body.split())[:200])
    return lines[:limit]


def _clears_bar(journal: Journal, idea: str, *, verdict: bool | None, has_writing: bool) -> bool:
    """Whether an extracted idea earns a place in the Stream.

    Nothing to be relevant to yet means everything shows: on an empty journal a
    filtered-to-silence ingest is just a broken feature.

    Otherwise the model's judgement stands, because it read both sides. The
    lexical fallback is for when there is no judgement to take — offline, or a
    response the parser could not use — and it is deliberately crude: does this
    idea's language actually meet something the writer wrote?
    """
    if not has_writing:
        return True
    if verdict is not None:
        return verdict

    # Content-word overlap, not a raw search hit. FTS5 does no stopword
    # removal, so "more than most bakers expect" matches a note about memory on
    # the strength of "more" and "most" — which would promote everything and
    # make the bar decorative. Two shared concepts is the same conservative
    # threshold the offline connector uses.
    terms = set(keywords(idea, 8))
    if len(terms) < 2:
        return False
    return any(
        e.provenance is Provenance.SELF and len(terms & set(keywords(e.body, 12))) >= 2
        for e in journal.search(idea, limit=5)
    )


def _has_own_writing(journal: Journal) -> bool:
    """Whether this journal contains anything the writer wrote themselves.

    A journal-level question, deliberately — not "did this source find
    anything to match". A source that meets nothing the writer thinks is the
    exact case the bar exists for, and treating it as an empty journal would
    promote every card in it.
    """
    return bool(journal.index.recent_bodies(limit=1))


async def distill(
    journal: Journal,
    provider: MeteredProvider,
    *,
    title: str,
    text: str,
    origin_url: str | None = None,
    persona: Persona | None = None,
    interactive: bool = True,
    reference: Reference | None = None,
) -> Entry | None:
    """Create a source entry and nest its extracted ideas beneath it.

    Returns the source entry. Cards are children, so the Stream renders the
    whole thing as one item rather than a flood.

    ``reference`` is a page or video the model opens for itself. In that case
    there is no local text at all, and the prompt says so rather than shipping
    an empty SOURCE block that reads as "this source was blank".
    """
    body = text.strip()
    if not body and reference is None:
        return None

    context = _context(journal, title, body)
    has_writing = _has_own_writing(journal)
    completion = await provider.complete(
        build_prompt(title, body, context, reference=reference),
        job=JOB,
        system=SYSTEM.format(persona=(persona or Persona()).as_instruction()),
        interactive=interactive,
        reference=reference,
    )
    payload = extract_json(completion.text)
    data = payload if isinstance(payload, dict) else {}

    summary = str(data.get("summary") or "").strip()[:MAX_SUMMARY]
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

    # A source entry is a container, not a thought: its body is a title and a
    # two-line description of what the thing argues. Judging that pays for a
    # connection between two summaries — found live, where two unrelated
    # sources linked on the word "extract" in their own boilerplate. The ideas
    # inside are the atoms, and each of those is judged on its own.
    journal.mark_considered(source.id, judged=True)

    # The full text lives beside the journal, never truncated. A reference
    # has no local copy to keep — the page or video is the original.
    if body:
        journal.write_source_text(source.id, body)

    cards = data.get("cards")
    if isinstance(cards, list):
        for card in cards[:MAX_CARDS]:
            if not isinstance(card, dict):
                continue
            idea = " ".join(str(card.get("idea", "")).split()).strip()[:MAX_IDEA]
            if len(idea) < 8:
                continue
            verdict = card.get("relevant")
            journal.add_card(
                source_id=source.id,
                body=idea,
                anchor=" ".join(str(card.get("anchor", "")).split())[:200] or None,
                promoted=_clears_bar(
                    journal,
                    idea,
                    verdict=verdict if isinstance(verdict, bool) else None,
                    has_writing=has_writing,
                ),
            )

    # Questions always surface. A question the source leaves open is not a
    # claim competing for space — it is the thing most likely to become
    # something the writer takes up themselves.
    questions = data.get("questions")
    if isinstance(questions, list):
        for question in questions[:3]:
            text_q = " ".join(str(question).split()).strip()[:MAX_QUESTION]
            if len(text_q) > 8:
                journal.add_card(source_id=source.id, body=text_q, card_kind="question")

    return journal.get(source.id)
