"""Structured-output parsing.

Models wrap JSON in prose and fences no matter how firmly the prompt asks them
not to. Rather than fail a whole categorisation because of a stray ```json, we
recover the first balanced object or array in the response.
"""

from __future__ import annotations

import json
from typing import Any


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
