"""Carrying a journal to another machine, and back.

Export is a convenience over something that already works — the journal is a
folder, and copying it is the operation. Import is not: replacing a running
app's files needs the same care erasing them does, and it is the half that
turns "you can copy the folder" into something a person can actually do.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel

from tilt import archive
from tilt.api.deps import get_journal, get_settings_dep
from tilt.config import Settings
from tilt.journal import Journal

log = logging.getLogger(__name__)

router = APIRouter(tags=["portability"])

CONFIRMATION = "REPLACE"
"""Import overwrites a journal. It gets the same shape of gate as erasing one,
because from the point of view of what is currently on disk it is the same
thing with a copy afterwards."""


class Exported(BaseModel):
    path: str
    entries: int


class Import(BaseModel):
    path: str
    confirm: str = ""


class Imported(BaseModel):
    path: str
    entries: int
    written_by: str


@router.post("/export", response_model=Exported)
def export(
    settings: Settings = Depends(get_settings_dep),
    journal: Journal = Depends(get_journal),
) -> Exported:
    """Write one file holding the journal and the vectors. Never the key."""
    entries = journal.index.count(authored_only=True)
    written = archive.build(
        data_dir=settings.data_dir,
        vectors=settings.vectors_path,
        destination=settings.internal_dir / archive.name_for(),
        entries=entries,
    )
    return Exported(path=str(written), entries=entries)


@router.post("/import", response_model=Imported)
def restore(
    payload: Import,
    request: Request,
    background: BackgroundTasks,
    settings: Settings = Depends(get_settings_dep),
    journal: Journal = Depends(get_journal),
) -> Imported:
    """Replace this journal with the one in an archive, then stop.

    Stopping for the same reason erasing does: the process holds these files
    open, and on macOS overwriting one it holds does not fail — it goes on
    reading the copy that is no longer there. Everything, vectors included,
    loads clean on the next start.

    Replaces rather than merges. Two journals both written to is sync by another
    name, and that was decided against; what this app does about the same entry
    existing twice is notice and report it, which is a better answer than a
    merge that guesses.
    """
    if payload.confirm != CONFIRMATION:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Send {CONFIRMATION!r} to confirm. This replaces everything in "
            f"{settings.data_dir} and nothing has been touched.",
        )

    source = Path(payload.path).expanduser()
    try:
        # Checked before anything is closed or deleted, so a refusal costs
        # nothing — a bad path must not leave the app in pieces.
        manifest = archive.check(source)
    except archive.ArchiveError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    journal.index.close()
    if journal.vectors is not None:
        journal.vectors.close()

    try:
        archive.restore(source, data_dir=settings.data_dir, vectors=settings.vectors_path)
    except archive.ArchiveError as exc:
        # The stores are shut either way, so this is not a state to keep
        # serving from. Say what happened and stop, rather than pretend.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    server = getattr(request.app.state, "server", None)
    if server is not None:
        background.add_task(_stop, server)

    return Imported(
        path=str(source),
        entries=int(manifest.get("entries") or 0),
        written_by=str(manifest.get("tilt") or "an unknown version"),
    )


def _stop(server) -> None:
    server.should_exit = True
