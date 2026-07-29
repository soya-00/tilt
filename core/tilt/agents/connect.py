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
from tilt.models import Entry, Link, LinkKind, LinkRecord, Provenance, utcnow
from tilt.store.files import new_id

JOB = "connect"

CANDIDATES = 8

SYSTEM = """You find meaningful connections between entries in a private journal.

You are given one entry and a numbered list of earlier candidate entries.
Respond with JSON only — no prose, no code fence:

{"links": [{"n": 2, "kind": "echo", "rationale": "..."}]}

Entries are marked (yours) or (read). That distinction changes what a
disagreement between two of them means.

"kind" is one of:
- "echo": the writer is circling the same idea again
- "elaboration": one develops or sharpens the other
- "contradiction": the two cannot both be true, and BOTH are the writer's own —
  they have changed their mind, or not noticed that they disagree with themself
- "counterpoint": the two pull against each other and at least one is something
  the writer merely read. A source arguing against their position, or two
  sources disagreeing
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
  worth more than noticing a repetition.
- Never call it a contradiction when either side is marked (read). The writer
  did not contradict themself by reading someone who disagrees with them. That
  is a counterpoint, and it is worth having."""


def _voice(entry: Entry) -> str:
    """Whether the writer thought this or merely read it.

    The connector cannot tell a disagreement from a change of mind without
    knowing whose words are whose.
    """
    return "read" if entry.provenance is Provenance.SOURCE else "yours"


def _settle_kind(kind: LinkKind, entry: Entry, other: Entry) -> LinkKind:
    """Keep "contradiction" for the writer's own disagreements with themself.

    The prompt asks for this, and asking is not enough — the label is the part
    the user reads, and telling someone they contradicted themself when they
    merely read an opposing argument is both wrong and discouraging. Anything
    involving borrowed material is a counterpoint instead.
    """
    if kind is not LinkKind.CONTRADICTION:
        return kind
    borrowed = Provenance.SOURCE in (entry.provenance, other.provenance)
    return LinkKind.COUNTERPOINT if borrowed else kind


def build_prompt(entry: Entry, candidates: list[Entry]) -> str:
    listed = "\n\n".join(
        f"[{i + 1}] ({c.created:%Y-%m-%d}, {_voice(c)}) {c.body[:500]}"
        for i, c in enumerate(candidates)
    )
    return (
        f"TASK: connect\n\nENTRY ({_voice(entry)}):\n{entry.body}\n\nCANDIDATES:\n{listed}"
    )


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
        # Nothing to compare against — the first entry in an empty journal, or
        # one whose neighbours have all been judged already. Settled either way.
        journal.mark_considered(entry_id, judged=True)
        return []

    completion = await provider.complete(
        build_prompt(entry, candidates), job=JOB, system=SYSTEM, interactive=interactive
    )

    # Finding nothing is the common and correct outcome, so it has to be
    # recorded as a result. Otherwise every unconnected thought looks unexamined
    # and the nightly sweep judges the whole journal again, forever.
    journal.mark_considered(entry_id, judged=True)

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

        other = candidates[index - 1]
        kind = _settle_kind(kind, entry, other)

        link = Link(
            id=new_id(),
            src_id=entry_id,
            dst_id=other.id,
            kind=kind,
            rationale=" ".join(str(item.get("rationale", "")).split())[:200],
            created=utcnow(),
        )
        if journal.index.add_link(link):
            journal.record_link(
                entry_id, LinkRecord(to=link.dst_id, kind=kind.value, why=link.rationale)
            )
            created.append(link)
    return created
