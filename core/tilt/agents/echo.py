"""Offline provider.

Runs when no API key is configured. It is deliberately useful rather than a
stub: the UI, the threading model, categorisation, connection, and the cost
ledger all exercise their real paths, so the app is fully explorable — and the
whole test suite runs — without a network call or a cent of spend.

Its output is derived from the prompt by keyword overlap, never invented, and
reflections say plainly that no model is configured. It is a lexical stand-in
for judgement, not a substitute for it.
"""

from __future__ import annotations

import json
import re

from tilt.agents.base import Completion, Pricing, Reference, estimate_tokens
from tilt.agents.parsing import keywords

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


class EchoProvider:
    """Deterministic, dependency-free, and honest about being offline."""

    name = "echo"
    pricing = Pricing(input_per_m=0.0, output_per_m=0.0)

    # No network, so no page to open and no video to watch. Declared rather
    # than discovered: the ingest route checks this and says plainly that a
    # link needs a key, instead of storing an empty source that looks read.
    follows_references = False

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        reference: Reference | None = None,
    ) -> Completion:
        task = _task_of(prompt)
        if task == "categorize":
            text = _categorize(prompt)
        elif task == "connect":
            text = _connect(prompt)
        elif task == "merge":
            text = _merge()
        elif task == "distill":
            text = _distill(prompt)
        elif task == "diagram":
            text = _diagram(prompt)
        elif task == "scout":
            text = _scout(prompt)
        else:
            text = _reflect(prompt, _persona_name(system))

        return Completion(
            text=text,
            model="echo/offline",
            tokens_in=estimate_tokens(prompt),
            tokens_out=estimate_tokens(text),
        )


def _task_of(prompt: str) -> str:
    match = re.match(r"\s*TASK:\s*(\w+)", prompt)
    return match.group(1).lower() if match else "reflect"


# ------------------------------------------------------------------- reflect


def _persona_name(system: str | None) -> str:
    """Pull the configured agent name out of the system prompt.

    Offline mode cannot embody a personality — it has no model to do it with —
    but it can at least sign with the name you chose, so renaming the agent is
    visibly real before you add a key.
    """
    if not system:
        return "Tilt"
    match = re.search(r'Your name is "([^"]{1,32})"', system)
    return match.group(1) if match else "Tilt"


def _reflect(prompt: str, name: str = "Tilt") -> str:
    subject = _section(prompt, "ENTRY")
    context = _section(prompt, "EARLIER ENTRIES")

    terms = keywords(subject)
    sentences = [s.strip() for s in _SENTENCE.split(subject) if s.strip()]
    opening = sentences[0] if sentences else subject.strip()

    lines: list[str] = []
    if terms:
        lines.append(
            f"You keep returning to {_join(terms[:2])} here — that pairing is doing the work."
        )
    if len(opening) > 12:
        trimmed = opening if len(opening) <= 120 else opening[:117].rstrip() + "..."
        lines.append(f'The claim underneath this looks like: "{trimmed}"')

    overlap = sorted(set(terms) & set(keywords(context, 12))) if context else []
    if overlap:
        lines.append(f"This echoes earlier writing on {_join(overlap[:3])}.")

    lines.append(
        f"What would change your mind about {terms[0]}?"
        if terms
        else "What would have to be true for this to be wrong?"
    )
    lines.append(
        f"[{name} is offline — add a Gemini key in Settings for real reflection; "
        "offline replies match keywords and cannot follow a personality]"
    )
    return "\n\n".join(lines)


# ---------------------------------------------------------------- categorize


def _categorize(prompt: str) -> str:
    entry = _section(prompt, "ENTRY")
    existing = _section(prompt, "EXISTING THEMES")
    terms = keywords(entry, 4)

    # Reuse an existing theme when its label appears in the entry, mirroring
    # the reuse-before-invent rule the real prompt asks for.
    theme = ""
    for line in existing.splitlines():
        label = line.lstrip("- ").split(" (")[0].strip()
        if label and label.lower() in entry.lower():
            theme = label
            break
    if not theme and terms:
        theme = terms[0].title()

    return json.dumps(
        {
            "tags": terms[:3],
            "theme": theme or "Unfiled",
            "reason": "matched offline by keyword",
        }
    )


# ------------------------------------------------------------------- connect


def _merge() -> str:
    """Never fold two folders together offline.

    The candidates reaching this point already share a word — that is what
    selected them — so keyword overlap has no opinion left to give, and the
    question being asked is whether two names describe one subject. Merging
    destroys a distinction the writer was making, and it cannot be undone from
    the interface. Declining is the honest answer, and it matches the
    instruction the real model is given: when unsure, do not merge.
    """
    return json.dumps({"merges": []})


def _connect(prompt: str) -> str:
    entry_terms = set(keywords(_section(prompt, "ENTRY"), 8))
    candidates = _section(prompt, "CANDIDATES")

    best_n, best_shared = 0, set()
    for block in re.split(r"\n\n(?=\[\d+\])", candidates):
        match = re.match(r"\[(\d+)\]", block.strip())
        if not match:
            continue
        shared = entry_terms & set(keywords(block, 10))
        if len(shared) > len(best_shared):
            best_n, best_shared = int(match.group(1)), shared

    # Two shared concepts is a deliberately conservative bar. Offline mode must
    # not invent connections it cannot actually judge.
    if best_n and len(best_shared) >= 2:
        links = [
            {
                "n": best_n,
                "kind": "echo",
                "rationale": f"both turn on {_join(sorted(best_shared)[:2])}",
            }
        ]
    else:
        links = []
    return json.dumps({"links": links})


# ------------------------------------------------------------------- helpers


def _join(words: list[str]) -> str:
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + f" and {words[-1]}"


def _section(prompt: str, header: str) -> str:
    """Pull one labelled block out of the structured prompt.

    A header may carry a parenthetical — ``ENTRY (yours):`` tells the connector
    whose words these are — so the annotation is skipped rather than treated as
    part of the name.
    """
    match = re.search(
        rf"^{header}(?:\s*\([^)]*\))?:?\s*\n(.*?)(?=\n[A-Z][A-Z ]{{2,}}[ (]*:|\Z)",
        prompt,
        re.S | re.M,
    )
    return match.group(1).strip() if match else ""


# ------------------------------------------------------------------- distill


def _distill(prompt: str) -> str:
    """Offline distillation: the most repeated sentences, not comprehension.

    Honest about its limits — these are extracted verbatim, not understood.
    """
    source = _section(prompt, "SOURCE")
    title = _section(prompt, "TITLE")
    sentences = [s.strip() for s in _SENTENCE.split(source) if 40 <= len(s.strip()) <= 300]

    terms = set(keywords(source, 12))
    scored = sorted(
        sentences,
        key=lambda s: -len(terms & set(keywords(s, 8))),
    )

    seen: list[str] = []
    for sentence in scored:
        if len(seen) >= 6:
            break
        if not any(sentence[:40] == s[:40] for s in seen):
            seen.append(sentence)

    # No verdict on relevance. Offline this is sentence-ranking, not reading,
    # and it has no basis for saying which of these speaks to the writer —
    # omitting the field hands that back to the caller's lexical fallback
    # rather than guessing "yes" and promoting the lot.
    return json.dumps(
        {
            "summary": f"Offline extract of {title or 'this source'}: "
            f"{len(sentences)} candidate sentences, ranked by keyword overlap.",
            "cards": [{"idea": s, "anchor": ""} for s in seen],
            "questions": [],
        }
    )


# ------------------------------------------------------------------- diagram


def _clip(text: str, limit: int) -> str:
    """Cut at a word boundary. A node reading "a filter rather than a" looks
    like the renderer broke rather than like a label that was too long."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _mermaid_safe(text: str) -> str:
    """Mermaid node text cannot carry quotes or brackets, and offline labels are
    lifted straight out of the writer's sentences."""
    return re.sub(r'["\[\]{}()<>|]', "", text).strip()


def _diagram(prompt: str) -> str:
    """Offline diagramming: grouping by shared words, and honest about it.

    A mindmap, always. The other diagram types assert a direction — this causes
    that, this became that — and keyword overlap has no way to know a direction.
    Drawing a flowchart from it would be inventing an argument the writer never
    made, which is a worse failure than drawing something plain.
    """
    label = _mermaid_safe(_section(prompt, "SUBJECT")) or "This journal"
    # The "(wrote)" / "(read)" marker is the prompt talking, not the writer.
    # Left in, it is the most repeated word in the block and every entry groups
    # under a branch called "wrote" — scaffolding presented as a finding.
    lines = [
        re.sub(r"^\(\w+\)\s*", "", ln.strip(" -"))
        for ln in _section(prompt, "ENTRIES").splitlines()
        if ln.strip(" -")
    ]
    body = "\n".join(lines)

    # The words that recur across entries are the only structure available here.
    common = keywords(body, 5)
    grouped: dict[str, list[str]] = {term: [] for term in common}
    loose: list[str] = []
    for line in lines:
        terms = set(keywords(line, 10))
        hit = next((term for term in common if term in terms), None)
        opening = _clip(_mermaid_safe(line.split(".")[0]), 52)
        if not opening:
            continue
        if hit:
            grouped[hit].append(opening)
        else:
            loose.append(opening)

    out = ["mindmap", f"  root(({label}))"]
    for term, members in grouped.items():
        if not members:
            continue
        out.append(f"    {term}")
        for member in members[:4]:
            out.append(f"      {member}")
    for member in loose[:3]:
        out.append(f"    {member}")

    return json.dumps(
        {
            "title": f"{label} by shared words"[:60],
            "kind": "mindmap",
            "mermaid": "\n".join(out),
            "note": (
                "Offline: grouped by words that recur across these entries, "
                "not by anything understood about them. Add a Gemini key in "
                "Settings for a diagram that reads the argument."
            ),
        }
    )


# --------------------------------------------------------------------- scout


def _scout(prompt: str) -> str:
    """Offline triage: word overlap between a candidate and what you have asked.

    Deliberately stingy, and for the same reason the real prompt is. Offline
    this cannot read either the question or the paper — it can only notice that
    they use some of the same words, which is a far weaker claim than "this
    might answer that". One pick at most, and only on a real overlap.
    """
    asked = set(keywords(_section(prompt, "OPEN QUESTIONS"), 12))
    asked |= set(keywords(_section(prompt, "SUBJECTS"), 8))
    candidates = _section(prompt, "TURNED UP TODAY")

    best_n, best_shared = None, set()
    for block in re.split(r"\n\n(?=\[\d+\])", candidates):
        match = re.match(r"\[(\d+)\]", block.strip())
        if not match:
            continue
        shared = asked & set(keywords(block, 12))
        if len(shared) > len(best_shared):
            best_n, best_shared = int(match.group(1)), shared

    # Three shared words rather than the connector's two: proposing something
    # to read costs the reader an afternoon, where proposing a link costs them
    # a glance.
    if best_n is None or len(best_shared) < 3:
        return json.dumps({"picks": []})
    return json.dumps(
        {
            "picks": [
                {
                    "n": best_n,
                    "why": f"shares {_join(sorted(best_shared)[:3])} with what you have asked"
                    " — matched offline by keyword, not by reading either",
                }
            ]
        }
    )
