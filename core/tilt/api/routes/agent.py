"""Agent endpoints — where input becomes processed thought."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from tilt.agents import AgentError, BudgetExceeded
from tilt.agents.categorize import categorize
from tilt.agents.connect import connect
from tilt.agents.ledger import MeteredProvider
from tilt.agents.reflect import reflect_on
from tilt.api.deps import get_journal, get_persona_store, get_provider
from tilt.journal import Journal
from tilt.models import Entry, Thread
from tilt.persona import Persona, PersonaStore, PersonaUpdate

router = APIRouter(prefix="/agent", tags=["agent"])


class EntryRequest(BaseModel):
    entry_id: str


def _surface(exc: Exception) -> HTTPException:
    if isinstance(exc, BudgetExceeded):
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.post("/reflect", response_model=Entry)
async def reflect(
    payload: EntryRequest,
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
    store: PersonaStore = Depends(get_persona_store),
) -> Entry:
    """Reflect on one entry and thread the response beneath it."""
    try:
        reply = await reflect_on(journal, provider, payload.entry_id, persona=store.load())
    except (BudgetExceeded, AgentError) as exc:
        raise _surface(exc) from exc

    if reply is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found.")
    return reply


@router.post("/categorize", response_model=Thread)
async def categorize_entry(
    payload: EntryRequest,
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
) -> Thread:
    """Tag an entry and file it under a theme."""
    try:
        entry = await categorize(journal, provider, payload.entry_id)
    except (BudgetExceeded, AgentError) as exc:
        raise _surface(exc) from exc

    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found.")
    return journal.thread(payload.entry_id)


@router.post("/connect", response_model=Thread)
async def connect_entry(
    payload: EntryRequest,
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
) -> Thread:
    """Find connections between this entry and earlier ones."""
    if journal.get(payload.entry_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found.")
    try:
        await connect(journal, provider, payload.entry_id)
    except (BudgetExceeded, AgentError) as exc:
        raise _surface(exc) from exc
    return journal.thread(payload.entry_id)


@router.post("/process", response_model=Thread)
async def process_entry(
    payload: EntryRequest,
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
) -> Thread:
    """Categorise then connect, in one call.

    This is what runs after you keep an entry. Categorisation goes first so the
    connector can see a fully filed corpus.
    """
    if journal.get(payload.entry_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found.")
    try:
        await categorize(journal, provider, payload.entry_id)
        await connect(journal, provider, payload.entry_id)
    except (BudgetExceeded, AgentError) as exc:
        raise _surface(exc) from exc
    return journal.thread(payload.entry_id)


@router.get("/persona", response_model=Persona)
def read_persona(store: PersonaStore = Depends(get_persona_store)) -> Persona:
    """The one agent's name and manner. There is no roster."""
    return store.load()


@router.patch("/persona", response_model=Persona)
def write_persona(
    payload: PersonaUpdate, store: PersonaStore = Depends(get_persona_store)
) -> Persona:
    return store.update(payload)


@router.get("/runs")
def list_runs(journal: Journal = Depends(get_journal), limit: int = 50) -> list[dict]:
    """Recent agent activity. The observability surface for silent failures."""
    return journal.index.runs(limit=limit)
