"""The constellation — the journal as one graph rather than one column.

The Stream shows thinking in the order it happened, and the sidebar shows it
grouped. Neither shows its shape: which preoccupations are dense, which sit
alone, and where two areas turned out to touch. That is what this returns.

It is a read of the index and nothing else. No agent runs here, nothing is
written, and asking for the graph costs nothing — which is what lets it be a
thing you open on a whim rather than a thing you budget for.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from tilt.api.deps import get_journal
from tilt.journal import Journal
from tilt.models import Entry, Graph, GraphEdge, GraphNode

router = APIRouter(tags=["graph"])

MAX_NODES = 300
"""Past a few hundred nodes a force layout is a hairball rather than a picture.

The cap is announced rather than applied quietly — see ``Graph.truncated``."""

LABEL_CHARS = 48
"""Enough to recognise a thought you wrote, short enough to read at a glance."""


def _label(entry: Entry) -> str:
    """The first line of the body, trimmed.

    A node is something you have to recognise from across the canvas, and the
    opening line is how people remember what they wrote. Markdown heading and
    quote markers are stripped so a node is never labelled ``##``.
    """
    first = next((ln.strip() for ln in entry.body.splitlines() if ln.strip()), "")
    first = first.lstrip("#>-* ").strip()
    if len(first) <= LABEL_CHARS:
        return first or "(empty)"
    return first[: LABEL_CHARS - 1].rstrip() + "…"


@router.get("/graph", response_model=Graph)
def read_graph(
    since: datetime | None = Query(None, description="Only entries written after this"),
    theme_id: str | None = Query(None, description="Restrict to one folder"),
    include_sources: bool = Query(False, description="Draw what you read as well"),
    include_themes: bool = Query(True, description="Draw folders and membership"),
    limit: int = Query(MAX_NODES, ge=1, le=MAX_NODES),
    journal: Journal = Depends(get_journal),
) -> Graph:
    """Entries and folders as nodes, connections and membership as edges."""
    stamp = since.isoformat() if since else None
    entries = journal.index.graph_entries(
        limit=limit,
        since=stamp,
        theme_id=theme_id,
        include_sources=include_sources,
    )
    total = journal.index.graph_count(
        since=stamp, theme_id=theme_id, include_sources=include_sources
    )
    ids = [e.id for e in entries]

    nodes = [
        GraphNode(
            id=e.id,
            label=_label(e),
            kind=e.kind.value,
            provenance=e.provenance.value,
            created=e.created,
        )
        for e in entries
    ]
    edges = [
        GraphEdge(
            source=link.src_id,
            target=link.dst_id,
            kind=link.kind.value,
            rationale=link.rationale,
        )
        for link in journal.index.links_between(ids)
    ]

    if include_themes:
        memberships = journal.index.themes_for(ids)
        counts: dict[str, int] = {}
        labels: dict[str, str] = {}
        for entry_id, themes in memberships.items():
            for theme in themes:
                counts[theme.id] = counts.get(theme.id, 0) + 1
                labels[theme.id] = theme.label
                edges.append(
                    GraphEdge(source=entry_id, target=theme.id, kind="member")
                )
        # Sized by how many of the *drawn* entries belong to it, not by the
        # folder's total count: a node whose size disagrees with the number of
        # lines touching it reads as a rendering bug.
        nodes.extend(
            GraphNode(
                id=theme_id_,
                label=labels[theme_id_],
                kind="theme",
                weight=count,
            )
            for theme_id_, count in counts.items()
        )

    return Graph(
        nodes=nodes, edges=edges, truncated=len(entries) < total, total=total
    )
