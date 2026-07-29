"""Diagram this — draw the structure of a folder, a tag, or a search.

Deliberately scoped. Diagramming "everything" is not a request anyone means:
a diagram is an argument about how a particular set of thoughts hangs together,
and a set that includes every thought you have ever had has no shape to find.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from tilt.agents import AgentError, BudgetExceeded
from tilt.agents.diagram import DiagramError, draw, repair
from tilt.agents.ledger import MeteredProvider
from tilt.api.deps import get_artifacts, get_journal, get_persona_store, get_provider
from tilt.journal import Journal
from tilt.models import Artifact, Entry
from tilt.persona import PersonaStore
from tilt.store.artifacts import ArtifactStore

router = APIRouter(tags=["diagram"])

SCOPE_LIMIT = 40


class DiagramRequest(BaseModel):
    theme_id: str | None = None
    tag: str | None = None
    q: str | None = None


class RepairRequest(BaseModel):
    error: str = Field(min_length=1, max_length=2000)
    """What the renderer said. Sent back verbatim — a paraphrase of a parser
    error is worth nothing to the model trying to fix it."""


def _surface(exc: Exception) -> HTTPException:
    if isinstance(exc, BudgetExceeded):
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))
    if isinstance(exc, DiagramError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


def _scope(journal: Journal, payload: DiagramRequest) -> tuple[str, list[Entry]]:
    """The entries to draw, and what to call them."""
    if payload.theme_id:
        theme = journal.index.get_theme(payload.theme_id)
        if theme is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found.")
        return theme.label, journal.index.entries_in_theme(theme.id)[:SCOPE_LIMIT]
    if payload.tag:
        threads = journal.stream(limit=SCOPE_LIMIT, tag=payload.tag)
        return f"#{payload.tag}", [t.entry for t in threads]
    if payload.q:
        return payload.q, journal.search(payload.q, limit=SCOPE_LIMIT)
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "Choose a folder, a tag, or a search to draw. "
        "A diagram of everything has no shape to find.",
    )


@router.post("/diagram", response_model=Artifact)
async def make_diagram(
    payload: DiagramRequest,
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
    store: ArtifactStore = Depends(get_artifacts),
    persona: PersonaStore = Depends(get_persona_store),
) -> Artifact:
    label, entries = _scope(journal, payload)
    try:
        artifact = await draw(
            journal, provider, label=label, entries=entries, persona=persona.load()
        )
    except (BudgetExceeded, AgentError, DiagramError) as exc:
        raise _surface(exc) from exc
    return store.save(artifact)


@router.post("/diagram/{artifact_id}/repair", response_model=Artifact)
async def repair_diagram(
    artifact_id: str,
    payload: RepairRequest,
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
    store: ArtifactStore = Depends(get_artifacts),
    persona: PersonaStore = Depends(get_persona_store),
) -> Artifact:
    """One more attempt, with the renderer's complaint in hand.

    Only the client can run this check — Mermaid's parser is JavaScript — so the
    failure has to come back from the view that tried to draw it. There is no
    second repair: the route will happily be called again, but the view does not
    do so, because two failures means the model cannot draw this one and a third
    paid attempt is a loop rather than a fix.
    """
    existing = store.load(artifact_id)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diagram not found.")

    entries = [e for e in (journal.get(i) for i in existing.subject_ids) if e]
    try:
        fixed = await repair(
            journal,
            provider,
            artifact=existing,
            entries=entries,
            error=payload.error,
            persona=persona.load(),
        )
    except (BudgetExceeded, AgentError, DiagramError) as exc:
        raise _surface(exc) from exc
    # Same id, same file: a draft that did not render is not worth keeping
    # beside the one that replaced it.
    return store.save(fixed)


@router.get("/diagrams", response_model=list[Artifact])
def list_diagrams(store: ArtifactStore = Depends(get_artifacts)) -> list[Artifact]:
    """Every diagram, newest first.

    Without this the save is write-only, and a diagram you cannot find again is
    a file the app is quietly accumulating on your behalf.
    """
    return store.all()


@router.delete("/diagrams/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_diagram(
    artifact_id: str, store: ArtifactStore = Depends(get_artifacts)
) -> None:
    if not store.delete(artifact_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diagram not found.")
