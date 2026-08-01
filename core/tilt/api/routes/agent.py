"""Agent endpoints — where input becomes processed thought."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from tilt.agents import AgentError, BudgetExceeded
from tilt.agents.categorize import categorize
from tilt.agents.connect import connect
from tilt.agents.ledger import MeteredProvider
from tilt.agents.reflect import reflect_on
from tilt.api.deps import get_journal, get_persona_store, get_provider
from tilt.jobs import JOBS, run_job
from tilt.journal import Journal
from tilt.models import Activity, AgentRun, Entry, JobSummary, Notice, Thread
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


@router.get("/notices", response_model=list[Notice])
def list_notices(journal: Journal = Depends(get_journal)) -> list[Notice]:
    """What the weekly pass noticed and has not been answered on.

    Usually empty, which is the design rather than a lull: a pass that finds
    something every week is one whose findings stop being worth reading.
    """
    return journal.index.open_notices()


@router.delete("/notices/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_notice(notice_id: str, journal: Journal = Depends(get_journal)) -> None:
    if not journal.index.dismiss_notice(notice_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notice not found.")


@router.post("/notices/{notice_id}/reflect", response_model=Entry)
async def reflect_on_notice(
    notice_id: str,
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
    store: PersonaStore = Depends(get_persona_store),
) -> Entry:
    """The synthesis, and the only part of the weekly pass that costs anything.

    Noticing is free and happens on a schedule; this happens because somebody
    asked. It reflects on the most recent entry the notice names, with the other
    one already in that entry's context — so the answer arrives threaded where
    machine replies already live, rather than in a weekly digest of its own that
    would need its own place to be read and its own reason to be trusted.

    The notice is dismissed by the same call. It has been answered; leaving it
    up would invite the same question to be paid for twice.
    """
    notice = journal.index.get_notice(notice_id)
    if notice is None or not notice.entry_ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notice not found.")

    entries = [e for e in (journal.get(i) for i in notice.entry_ids) if e is not None]
    if not entries:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The entries behind it are gone.")
    subject = max(entries, key=lambda e: e.created)

    try:
        reply = await reflect_on(journal, provider, subject.id, persona=store.load())
    except (BudgetExceeded, AgentError) as exc:
        raise _surface(exc) from exc

    journal.index.dismiss_notice(notice_id)
    return reply


@router.get("/runs", response_model=list[AgentRun])
def list_runs(journal: Journal = Depends(get_journal), limit: int = 50) -> list[dict]:
    """Recent agent activity. The observability surface for silent failures."""
    return journal.index.runs(limit=limit)


@router.post("/jobs/{name}", response_model=JobSummary)
async def trigger_job(
    name: str,
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
) -> JobSummary:
    """Run a scheduled job now.

    Every unattended job is reachable by hand. Waiting until 3am to find out
    whether a job works is not a way to build one, and a user who suspects the
    agent has fallen behind should be able to settle it in one click rather than
    by leaving the app open overnight.
    """
    if name not in JOBS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No such job: {name}.")
    try:
        return await run_job(name, journal, provider)
    except (BudgetExceeded, AgentError) as exc:
        raise _surface(exc) from exc


@router.get("/activity", response_model=Activity)
def activity(
    since: datetime = Query(..., description="Return what has happened since this moment"),
    journal: Journal = Depends(get_journal),
) -> Activity:
    """What the agent did while you were not looking.

    Counts only. The connections themselves are already threaded under the
    entries they belong to, which is where they mean something — this exists to
    tell you there is a reason to scroll, not to become a second inbox.
    """
    stamp = since.isoformat()
    return Activity(
        since=since,
        filed=journal.index.filed_since(stamp),
        connected=journal.index.links_since(stamp),
    )
