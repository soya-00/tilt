"""Diagram this — the agent draws the structure it sees in a set of thoughts.

Distinct from the constellation on purpose. The constellation shows what has
connected to what; a diagram says what the *shape* is — which idea leads to
which, where a position moved, what depends on what. The model picks the form,
because the form is most of the claim.

The output is Mermaid, which means model output is being handed to a parser. It
is sanitised here rather than trusted: a diagram may describe your thinking, but
it has no business opening pages or reconfiguring the renderer.
"""

from __future__ import annotations

import re

from tilt.agents.ledger import MeteredProvider
from tilt.agents.parsing import extract_json
from tilt.journal import Journal
from tilt.models import Artifact, Entry, EntryKind, Provenance, utcnow
from tilt.persona import Persona
from tilt.store.files import new_id

JOB = "diagram"

MAX_ENTRIES = 40
"""Enough for a folder's worth of thinking. Beyond this a diagram stops being a
picture of an argument and becomes a second, worse constellation."""

MAX_CHARS = 600
"""Per entry. A diagram is drawn from claims, not from prose."""

MAX_SOURCE = 20_000
"""How large the returned diagram may be.

Everything else the model sends back here is filtered, and the source itself was
the one part with no ceiling — handed whole to a renderer that has to parse it
and lay it out. Far above any real diagram of forty entries."""

KINDS = (
    "flowchart",
    "graph",
    "mindmap",
    "sequenceDiagram",
    "stateDiagram",
    "stateDiagram-v2",
    "timeline",
)
"""Diagram headers Mermaid understands and this app is willing to render.

An allowlist rather than a denylist: Mermaid keeps adding diagram types, and a
new one arriving in a model's training data should not become a new thing the
renderer will attempt on the strength of nobody having thought about it."""

SYSTEM = """You draw diagrams of someone's thinking for a private journal called Tilt.

{persona}

You are given a set of entries the writer wrote. Respond with JSON only, no
prose, no code fence:

{{"title": "...", "kind": "flowchart", "mermaid": "...", "note": "..."}}

Rules:
- "kind" is one of: flowchart, mindmap, stateDiagram-v2, timeline. Choose the
  one the material actually has the shape of:
  - mindmap when these are facets of one preoccupation with no direction;
  - flowchart when one thing leads to, causes, or depends on another;
  - stateDiagram-v2 when a position moved from one stance to another;
  - timeline when the sequence in time is the point.
- "mermaid" is the complete diagram source, starting with the diagram keyword.
  Use short node labels in double quotes. No styling, no click directives, no
  configuration blocks, no links.
- Draw the STRUCTURE, not a summary. Do not make one node per entry — group,
  and name the relationships. A diagram that is a list of the entries in a box
  each is worthless.
- "title": four words at most, naming what is being drawn.
- "note": one sentence on the structure you saw, in your own voice.
- If these entries genuinely have no structure in common, say so in "note" and
  return the smallest honest diagram rather than inventing a hierarchy."""

REPAIR = """The Mermaid you produced does not parse. The renderer said:

{error}

Return the same JSON shape with the diagram fixed. Change only what is needed to
make it parse — keep the structure you found. Do not explain the error."""


class DiagramError(Exception):
    """The model returned something that is not a diagram this can render."""


def _fence(text: str) -> str:
    """Pull the diagram out of a code fence, if the model added one.

    It is told not to. It sometimes does anyway, and refusing a diagram that is
    otherwise perfectly good over three backticks would be pedantry.
    """
    match = re.search(r"```(?:mermaid)?\s*\n(.*?)```", text, re.S)
    return match.group(1) if match else text


def extract_mermaid(text: str) -> str:
    """Turn model output into diagram source, or refuse it.

    Three things are removed rather than trusted, because each is a way for a
    diagram to reach outside itself:

    - ``click`` binds a node to a URL or a callback;
    - ``href`` does the same inline;
    - ``%%{init …}%%`` rewrites the renderer's configuration, including its
      security level, from inside the document.

    None of them can be part of describing someone's thinking, so none of them
    survives. What is left must still open with a diagram keyword — a response
    that does not is prose, and rendering prose is not a thing to attempt.
    """
    body = _fence(text.strip())
    body = re.sub(r"%%\{.*?\}%%", "", body, flags=re.S)
    kept = [
        line
        for line in body.splitlines()
        if not re.match(r"\s*(click|link)\s", line, re.I)
        and not re.search(r"\bhref\b", line, re.I)
    ]
    body = "\n".join(kept).strip()

    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    if first.split(" ")[0].rstrip(":").strip() not in KINDS:
        raise DiagramError(
            "That did not come back as a diagram. "
            f"It began {first[:40]!r} rather than with a diagram keyword."
        )
    if len(body) > MAX_SOURCE:
        raise DiagramError(
            f"That diagram came back at {len(body):,} characters, past the "
            f"{MAX_SOURCE:,} this will render."
        )
    return body


def build_prompt(label: str, entries: list[Entry]) -> str:
    lines = []
    for entry in entries[:MAX_ENTRIES]:
        body = " ".join(entry.body.split())[:MAX_CHARS]
        voice = "read" if entry.provenance is Provenance.SOURCE else "wrote"
        lines.append(f"- ({voice}) {body}")
    return (
        f"TASK: diagram\n\nSUBJECT:\n{label}\n\n"
        f"ENTRIES:\n" + ("\n".join(lines) or "(none)")
    )


def _artifact(data: dict, entries: list[Entry], *, artifact_id: str | None) -> Artifact:
    mermaid = extract_mermaid(str(data.get("mermaid") or ""))
    kind = str(data.get("kind") or "").strip() or mermaid.split()[0]
    title = " ".join(str(data.get("title") or "").split())[:60]
    return Artifact(
        id=artifact_id or new_id(),
        kind=kind if kind in KINDS else mermaid.split()[0],
        path="",
        title=title or "Untitled diagram",
        body=mermaid,
        note=" ".join(str(data.get("note") or "").split())[:300],
        subject_ids=[e.id for e in entries[:MAX_ENTRIES]],
        created=utcnow(),
    )


async def draw(
    journal: Journal,
    provider: MeteredProvider,
    *,
    label: str,
    entries: list[Entry],
    persona: Persona | None = None,
    interactive: bool = True,
) -> Artifact:
    """Draw one diagram of a set of entries. Raises rather than inventing one."""
    usable = [e for e in entries if e.kind is not EntryKind.REPLY and e.body.strip()]
    if not usable:
        raise DiagramError("There is nothing here to draw yet.")

    completion = await provider.complete(
        build_prompt(label, usable),
        job=JOB,
        system=SYSTEM.format(persona=(persona or Persona()).as_instruction()),
        interactive=interactive,
    )
    payload = extract_json(completion.text)
    if not isinstance(payload, dict):
        raise DiagramError("The model did not return a diagram this could read.")
    return _artifact(payload, usable, artifact_id=None)


async def repair(
    journal: Journal,
    provider: MeteredProvider,
    *,
    artifact: Artifact,
    entries: list[Entry],
    error: str,
    persona: Persona | None = None,
) -> Artifact:
    """One more attempt, with the parser's complaint in hand.

    Exactly one. A repair loop that keeps going spends real money converging on
    nothing, and two failures is enough evidence that this diagram is not one
    the model can draw — at which point the honest move is to show the writer
    the error and the source and let them judge.
    """
    prompt = (
        build_prompt(artifact.title, entries)
        + "\n\nBROKEN DIAGRAM:\n"
        + artifact.body
        + "\n\n"
        + REPAIR.format(error=" ".join(error.split())[:400])
    )
    completion = await provider.complete(
        prompt,
        job=JOB,
        system=SYSTEM.format(persona=(persona or Persona()).as_instruction()),
        interactive=True,
    )
    payload = extract_json(completion.text)
    if not isinstance(payload, dict):
        raise DiagramError("The repair did not come back as a diagram either.")
    return _artifact(payload, entries, artifact_id=artifact.id)
