"""Ingesting long source material — transcripts, articles, pasted notes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from tilt.agents import AgentError, BudgetExceeded
from tilt.agents.distill import distill
from tilt.agents.ledger import MeteredProvider
from tilt.api.deps import get_journal, get_persona_store, get_provider
from tilt.journal import Journal
from tilt.models import Thread
from tilt.persona import PersonaStore

router = APIRouter(prefix="/ingest", tags=["ingest"])

MAX_BYTES = 2_000_000
"""~2MB of text. Well past any realistic transcript, short of a memory problem."""


class IngestRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    text: str = Field(min_length=1)
    url: str | None = None


@router.post("", response_model=Thread)
async def ingest_source(
    payload: IngestRequest,
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
    personas: PersonaStore = Depends(get_persona_store),
) -> Thread:
    """Distil a long source into one entry plus its atomic ideas.

    The source becomes a single item in the Stream with its cards nested
    beneath, so ingesting a transcript never floods the journal.
    """
    if len(payload.text.encode("utf-8")) > MAX_BYTES:
        # Literal 413: the starlette constant is mid deprecation rename.
        raise HTTPException(
            413,
            "That source is larger than 2MB. Split it into parts.",
        )

    try:
        source = await distill(
            journal,
            provider,
            title=payload.title,
            text=payload.text,
            origin_url=payload.url,
            persona=personas.load(),
        )
    except (BudgetExceeded, AgentError) as exc:
        code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if isinstance(exc, BudgetExceeded)
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(code, str(exc)) from exc

    if source is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That source is empty.")
    return journal.thread(source.id)
