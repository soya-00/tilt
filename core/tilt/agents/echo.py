"""Offline provider.

Runs when no API key is configured. It is deliberately useful rather than a
stub: the UI, the threading model, and the cost ledger all exercise their real
paths, so the app is fully explorable — and the whole test suite runs — without
a network call or a cent of spend.

Its output is derived from the prompt, never invented, so it can never be
mistaken for a real model's insight.
"""

from __future__ import annotations

import re

from tilt.agents.base import Completion, Pricing, estimate_tokens

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
# A wrapped string reads far better here than sixty quoted list items.
_STOPWORDS = frozenset(
    """
    a an and are as at be but by for from has have how i if in is it its of on or that the
    their them then there these they this to was were what when where which who why will with
    you your my me we our not no so just about like really very can could would should
    """.split()  # noqa: SIM905
)


def _keywords(text: str, n: int = 4) -> list[str]:
    counts: dict[str, int] = {}
    for word in re.findall(r"[a-zA-Z][a-zA-Z'-]{3,}", text.lower()):
        if word not in _STOPWORDS:
            counts[word] = counts.get(word, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


class EchoProvider:
    """Deterministic, dependency-free, and honest about being offline."""

    name = "echo"
    pricing = Pricing(input_per_m=0.0, output_per_m=0.0)

    async def complete(self, prompt: str, *, system: str | None = None) -> Completion:
        subject = _extract_section(prompt, "ENTRY")
        context = _extract_section(prompt, "EARLIER ENTRIES")

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

        lines.append(_question(terms))
        lines.append("[offline mode — no model configured; add a key in Settings]")

        text = "\n\n".join(lines)
        return Completion(
            text=text,
            model="echo/offline",
            tokens_in=estimate_tokens(prompt),
            tokens_out=estimate_tokens(text),
        )


def _question(terms: list[str]) -> str:
    if not terms:
        return "What would have to be true for this to be wrong?"
    return f"What would change your mind about {terms[0]}?"


def _join(words: list[str]) -> str:
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + f" and {words[-1]}"


def _extract_section(prompt: str, header: str) -> str:
    """Pull one labelled block out of the structured prompt."""
    match = re.search(rf"^{header}:?\s*\n(.*?)(?=\n[A-Z][A-Z ]{{2,}}:|\Z)", prompt, re.S | re.M)
    return match.group(1).strip() if match else ""
