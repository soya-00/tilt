"""Structured-output parsing, and the vocabulary work that goes with it.

Models wrap JSON in prose and fences no matter how firmly the prompt asks them
not to. Rather than fail a whole categorisation because of a stray ```json, we
recover the first balanced object or array in the response.

:func:`keywords` sits here rather than in the offline provider because two
things now need to ask "what is this text actually about" without spending a
model call: the offline provider, and the promotion bar's fallback when no
model verdict is available.
"""

from __future__ import annotations

import json
import re
from typing import Any

# A wrapped string reads far better here than sixty quoted list items.
STOPWORDS = frozenset(
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


def keywords(text: str, n: int = 4) -> list[str]:
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
        if word in STOPWORDS or _ADVERB.search(word):
            continue
        counts[word] = counts.get(word, 0) + 1

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    return [w for w, _ in ranked[:n]]


def extract_json(text: str) -> Any | None:
    """Best-effort recovery of the first JSON value in a model response."""
    stripped = text.strip()
    if not stripped:
        return None

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(stripped)):
            ch = stripped[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stripped[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def clean_tags(raw: Any, *, limit: int = 5) -> list[str]:
    """Normalise model-proposed tags into something stable enough to group by.

    Lowercased and deduplicated, because "Attention" and "attention" arriving on
    different days would otherwise split one idea across two sidebar entries.
    """
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        tag = item.strip().lstrip("#").lower()
        tag = " ".join(tag.split())
        if tag and len(tag) <= 32 and tag not in seen:
            seen.append(tag)
    return seen[:limit]


def clean_label(raw: Any, *, limit: int = 40) -> str:
    """Normalise a theme label to Title Case, trimmed."""
    if not isinstance(raw, str):
        return ""
    label = " ".join(raw.strip().strip("#\"'").split())
    if not label:
        return ""
    if label.islower() or label.isupper():
        label = label.title()
    return label[:limit]
