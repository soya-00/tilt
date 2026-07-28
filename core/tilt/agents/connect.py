"""Connection — finding where a thought meets an earlier one.

Candidates come from local search; the model only judges. That split matters:
retrieval is cheap and deterministic, judgement is the expensive part worth
spending a model call on.

The tuning target is precision, not recall. Three real connections a week beat
forty plausible ones — a noisy connector is the fastest way to make someone
stop trusting the app.
"""

from __future__ import annotations

from tilt.agents.ledger import MeteredProvider
from tilt.agents.parsing import extract_json
from tilt.journal import Journal
from tilt.models import Entry, Link, LinkKind, utcnow
from tilt.store.files import new_id

JOB = "connect"

CANDIDATES = 8

SYSTEM = """You find meaningful connections between entries in a private journal.

You are given one entry and a numbered list of earlier candidate entries.
Respond with JSON only — no prose, no code fence:

{"links": [{"n": 2, "kind": "echo", "rationale": "..."}]}

"kind" is one of:
- "echo": the writer is circling the same idea again
- "elaboration": one develops or sharpens the other
- "contradiction": the two cannot both be true, or the writer changed their mind
- "bridge": two unrelated areas that turn out to touch

Rules:
- Be strict. Shared vocabulary is NOT a connection. Two entries about "work" or
  both using the word "system" are unrelated unless the underlying idea is the
  same.
- Return an empty list when nothing genuinely connects. That is the common case
  and it is the correct answer.
- At most 2 links. Choose the strongest.
- "rationale" is one sentence, under 20 words, in the writer's own vocabulary,
  naming the specific shared idea rather than asserting that they are similar.
- Prefer contradiction over echo when both apply: noticing a changed mind is
  worth more than noticing a repetition."""


def build_prompt(entry: Entry, candidates: list[Entry]) -> str:
    listed = "\n\n".join(
        f"[{i + 1}] ({c.created:%Y-%m-%d}) {c.body[:500]}" for i, c in enumerate(candidates)
    )
    return f"TASK: connect\n\nENTRY:\n{entry.body}\n\nCANDIDATES:\n{listed}"


async def connect(
    journal: Journal,
    provider: MeteredProvider,
    entry_id: str,
    *,
    interactive: bool = True,
) -> list[Link]:
    """Judge and store connections for one entry. Returns the links created."""
    entry = journal.get(entry_id)
    if entry is None:
        return []

    already = journal.index.judged_pairs(entry_id)
    candidates = [
        c
        for c in journal.context_for(entry_id, limit=CANDIDATES * 2)
        if c.id not in already
    ][:CANDIDATES]
    if not candidates:
        return []

    completion = await provider.complete(
        build_prompt(entry, candidates), job=JOB, system=SYSTEM, interactive=interactive
    )

    payload = extract_json(completion.text)
    proposals = payload.get("links") if isinstance(payload, dict) else None
    if not isinstance(proposals, list):
        return []

    created: list[Link] = []
    for item in proposals[:2]:
        if not isinstance(item, dict):
            continue
        index = item.get("n")
        if not isinstance(index, int) or not 1 <= index <= len(candidates):
            continue
        try:
            kind = LinkKind(str(item.get("kind", "")).strip().lower())
        except ValueError:
            continue

        link = Link(
            id=new_id(),
            src_id=entry_id,
            dst_id=candidates[index - 1].id,
            kind=kind,
            rationale=" ".join(str(item.get("rationale", "")).split())[:200],
            created=utcnow(),
        )
        if journal.index.add_link(link):
            created.append(link)
    return created
