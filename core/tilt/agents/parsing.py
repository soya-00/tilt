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
from collections.abc import Iterable
from difflib import SequenceMatcher
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


def content_words(text: str) -> list[str]:
    """Every word that might be what a passage is about, in order.

    One definition of "content word" for the whole app. The offline embedder
    builds its vocabulary from this, and :func:`keywords` ranks it — if the two
    disagreed, a term could carry weight in a vector and be invisible to every
    other lexical path, which is a hard class of bug to see.
    """
    return [
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z'-]{3,}", text.lower())
        if word not in STOPWORDS and not _ADVERB.search(word)
    ]


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
    for word in content_words(text):
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


# --------------------------------------------------------------- vocabulary
#
# A journal's folders and tags are a vocabulary, and a vocabulary is only worth
# having if it is small enough to recognise. Left alone a model will happily
# mint "Attention", "Attentional Control" and "Attention Economy" across three
# nights, each with one member, and the sidebar becomes a list of things you
# wrote once. The prompt asks for reuse; this is what does not depend on asking.


def _singular(word: str) -> str:
    """Crude, deliberately. Only the endings that are safe without a lexicon."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def canonical(term: str) -> str:
    """The comparison key for a tag or a folder name.

    Case, punctuation and plurality are not distinctions anyone is making on
    purpose: "Attention", "attention" and "attentions" are one subject that
    would otherwise occupy three rows of the sidebar.
    """
    words = re.findall(r"[a-z0-9']+", term.lower())
    return " ".join(_singular(w) for w in words)


def snap(proposed: str, existing: Iterable[str], *, threshold: float = 0.9) -> str | None:
    """The existing term this is really proposing, or ``None`` for a new one.

    Exact match on the canonical form first, then near-match by edit ratio. The
    threshold is high on purpose, and the asymmetry is the reason: a duplicate
    folder is cheap to fix — the nightly keeper merges it and you can delete it
    by hand — while folding two genuinely different subjects together destroys a
    distinction the writer was making and cannot be undone from the interface.
    When unsure, mint the duplicate.
    """
    key = canonical(proposed)
    if not key:
        return None

    best: tuple[float, str] | None = None
    for term in existing:
        other = canonical(term)
        if not other:
            continue
        if other == key:
            return term
        # Never snap a single word onto a phrase or vice versa. "Memory" and
        # "Memory And Attention" score well above the threshold and are not the
        # same folder — the second is a claim about the first meeting something.
        if other.count(" ") != key.count(" "):
            continue
        ratio = SequenceMatcher(None, key, other).ratio()
        if ratio >= threshold and (best is None or ratio > best[0]):
            best = (ratio, term)
    return best[1] if best else None
