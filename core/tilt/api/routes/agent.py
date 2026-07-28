"""Agent endpoints — where input becomes processed thought."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from tilt.agents import AgentError, BudgetExceeded
from tilt.agents.ledger import MeteredProvider
from tilt.agents.reflect import reflect_on
from tilt.api.deps import get_journal, get_provider
from tilt.journal import Journal
from tilt.models import Entry

router = APIRouter(prefix="/agent", tags=["agent"])


class ReflectRequest(BaseModel):
    entry_id: str


@router.post("/reflect", response_model=Entry)
async def reflect(
    payload: ReflectRequest,
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
) -> Entry:
    """Reflect on one entry and thread the response beneath it."""
    try:
        reply = await reflect_on(journal, provider, payload.entry_id)
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except AgentError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    if reply is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found.")
    return reply


@router.get("/runs")
def list_runs(journal: Journal = Depends(get_journal), limit: int = 50) -> list[dict]:
    """Recent agent activity. The observability surface for silent failures."""
    return journal.index.runs(limit=limit)
