"""Ingesting long source material — transcripts, articles, PDFs, pasted notes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from tilt.agents import AgentError, BudgetExceeded
from tilt.agents.base import Reference
from tilt.agents.distill import distill
from tilt.agents.ledger import MeteredProvider
from tilt.api.deps import get_journal, get_persona_store, get_provider
from tilt.ingest import ExtractionError, Medium, classify, extract
from tilt.journal import Journal
from tilt.models import Entry, Thread
from tilt.persona import PersonaStore

router = APIRouter(prefix="/ingest", tags=["ingest"])

MAX_BYTES = 2_000_000
"""~2MB of text. Well past any realistic transcript, short of a memory problem."""


class IngestRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    # Bounded in the handler rather than here: the limit is in bytes, a
    # max_length is in characters, and the handler's 413 says what to do about
    # it where a validation error would only say the shape was wrong.
    text: str = ""
    url: str | None = None


async def _distil(
    journal: Journal,
    provider: MeteredProvider,
    personas: PersonaStore,
    *,
    title: str,
    text: str,
    url: str | None,
    reference: Reference | None = None,
) -> Entry:
    """The one path everything converges on, whatever arrived.

    Failure modes are mapped to status codes here rather than in each caller,
    so a budget stop reads as a budget stop no matter which door it came in by.
    """
    if len(text.encode("utf-8")) > MAX_BYTES:
        # Literal 413: the starlette constant is mid deprecation rename.
        raise HTTPException(413, "That source is larger than 2MB. Split it into parts.")

    try:
        source = await distill(
            journal,
            provider,
            title=title,
            text=text,
            origin_url=url,
            persona=personas.load(),
            reference=reference,
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
    return source


@router.post("", response_model=Thread)
async def ingest_source(
    payload: IngestRequest,
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
    personas: PersonaStore = Depends(get_persona_store),
) -> Thread:
    """Distil a long source into one entry plus its atomic ideas.

    Text can arrive pasted, or as a link the model opens itself. The source
    becomes a single item in the Stream with its cards nested beneath, so
    ingesting a transcript never floods the journal.
    """
    route = classify(url=payload.url or "", text=payload.text)
    reference = None

    if not payload.text.strip():
        # No text means the link *is* the source, and only a model that can
        # follow it will do. Saying so beats storing an empty entry that looks
        # like something was read.
        if route.medium not in (Medium.VIDEO, Medium.ARTICLE):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That source is empty.")
        if not provider.follows_references:
            raise HTTPException(
                status.HTTP_501_NOT_IMPLEMENTED,
                "Reading a link needs a Gemini key. Add one in Settings, or paste the text.",
            )
        reference = Reference(url=route.url or "", kind=route.medium.value)

    source = await _distil(
        journal,
        provider,
        personas,
        title=payload.title or route.title,
        text=payload.text,
        url=payload.url,
        reference=reference,
    )
    return journal.thread(source.id)


@router.post("/file", response_model=Thread)
async def ingest_file(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
    personas: PersonaStore = Depends(get_persona_store),
) -> Thread:
    """Distil an uploaded file — a PDF, a subtitle track, a text document.

    The browser cannot read a PDF, and asking someone to convert one before
    Tilt will look at it is the kind of chore the app exists to remove.
    """
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "That file is larger than 2MB. Split it into parts.")

    route = classify(filename=file.filename or "", content_type=file.content_type or "")
    try:
        text = extract(route, data)
    except ExtractionError as exc:
        # 415: the file arrived intact and was understood well enough to be
        # declined. That is a media-type problem, not a malformed request.
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    source = await _distil(
        journal,
        provider,
        personas,
        title=title or route.title,
        text=text,
        url=None,
    )
    return journal.thread(source.id)
