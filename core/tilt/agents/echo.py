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

from tilt.agents.base import Completion, Pricing, estimate_tokens

_SENTENCE = re.compile(r"(?<=[.!?])\s+")

# A wrapped string reads far better here than sixty quoted list items.
_STOPWORDS = frozenset(
    """
    a an and are as at be but by for from has have how i if in is it its of on or that the
    their them then there these they this to was were what when where which who why will with
    you your my me we our not no so just about like really very can could would should
    been being was were does did done make makes made get gets got take takes took
    thing things something anything nothing everything way ways much more most less least
    again also even still yet ever never always often sometimes perhaps maybe
    because since while during before after between through into onto over under
    keeps keep kept feels feel felt seems seem seemed looks look looked
    than such each both upon unto whom whose shall must might rather instead
    however though although unless whether toward towards across among beyond
    within without many some thus hence therefore else other others another
    either neither here itself himself herself themselves myself ourselves
    yourself everyone anyone someone nobody having
    """.split()  # noqa: SIM905
)

# Adverbs are almost never the subject of a thought; they inflate the keyword
# list with words like "accidentally" and "deliberately".
_ADVERB = re.compile(r"ly$")


def _keywords(text: str, n: int = 4) -> list[str]:
    """Rank terms by repetition, then by length.

    Repetition is the only signal available without a model, and it is a
    surprisingly good one: a word used twice in a short entry is usually what
    the entry is about. Single-use words are kept but rank below it, with
    longer words preferred — an alphabetical tiebreak is what produced tags
    like "again" and "being".

    Ranking rather than filtering matters: discarding every single-use word
    would leave too few terms for the connector to find overlap with.
    """
    counts: dict[str, int] = {}
    for word in re.findall(r"[a-zA-Z][a-zA-Z'-]{3,}", text.lower()):
        if word in _STOPWORDS or _ADVERB.search(word):
            continue
        counts[word] = counts.get(word, 0) + 1

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    return [w for w, _ in ranked[:n]]


class EchoProvider:
    """Deterministic, dependency-free, and honest about being offline."""

    name = "echo"
    pricing = Pricing(input_per_m=0.0, output_per_m=0.0)

    async def complete(self, prompt: str, *, system: str | None = None) -> Completion:
        task = _task_of(prompt)
        if task == "categorize":
            text = _categorize(prompt)
        elif task == "connect":
            text = _connect(prompt)
        elif task == "merge":
            text = _merge()
        elif task == "distill":
            text = _distill(prompt)
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

    terms = _keywords(subject)
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

    overlap = sorted(set(terms) & set(_keywords(context, 12))) if context else []
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
    terms = _keywords(entry, 4)

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
    entry_terms = set(_keywords(_section(prompt, "ENTRY"), 8))
    candidates = _section(prompt, "CANDIDATES")

    best_n, best_shared = 0, set()
    for block in re.split(r"\n\n(?=\[\d+\])", candidates):
        match = re.match(r"\[(\d+)\]", block.strip())
        if not match:
            continue
        shared = entry_terms & set(_keywords(block, 10))
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
    """Pull one labelled block out of the structured prompt."""
    match = re.search(rf"^{header}:?\s*\n(.*?)(?=\n[A-Z][A-Z ]{{2,}}:|\Z)", prompt, re.S | re.M)
    return match.group(1).strip() if match else ""


# ------------------------------------------------------------------- distill


def _distill(prompt: str) -> str:
    """Offline distillation: the most repeated sentences, not comprehension.

    Honest about its limits — these are extracted verbatim, not understood.
    """
    source = _section(prompt, "SOURCE")
    title = _section(prompt, "TITLE")
    sentences = [s.strip() for s in _SENTENCE.split(source) if 40 <= len(s.strip()) <= 300]

    terms = set(_keywords(source, 12))
    scored = sorted(
        sentences,
        key=lambda s: -len(terms & set(_keywords(s, 8))),
    )

    seen: list[str] = []
    for sentence in scored:
        if len(seen) >= 6:
            break
        if not any(sentence[:40] == s[:40] for s in seen):
            seen.append(sentence)

    return json.dumps(
        {
            "summary": f"Offline extract of {title or 'this source'}: "
            f"{len(sentences)} candidate sentences, ranked by keyword overlap.",
            "cards": [{"idea": s, "anchor": ""} for s in seen],
            "questions": [],
        }
    )
