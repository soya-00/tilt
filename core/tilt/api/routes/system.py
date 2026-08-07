"""Health, configuration surface, index maintenance, and erasure."""

from __future__ import annotations

import contextlib
import json
import logging
import shutil

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

# Aliased because the status *route* below is also called `status`, and the
# route is the older name.
from fastapi import status as codes
from pydantic import BaseModel

from tilt import __version__
from tilt.agents.ledger import MeteredProvider
from tilt.api.deps import (
    get_journal,
    get_provider,
    get_settings_dep,
    get_settings_store,
)
from tilt.config import Settings
from tilt.embed import DORMANT_WITHOUT_KEY
from tilt.journal import Journal
from tilt.models import Conflict, RenamedId
from tilt.settings_store import SettingsStore, write_key_file

log = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


class Dormant(BaseModel):
    capability: str
    why: str


class Status(BaseModel):
    ok: bool
    version: str
    """Which build is actually answering.

    Reported by the service rather than the interface, because those are two
    separate processes that can be different versions — a rebuilt app bundle
    still carrying a stale frozen service is the exact confusion this settles."""
    provider: str
    offline: bool
    model: str
    entries: int
    spend_this_month_usd: float
    cost_ceiling_usd: float
    data_dir: str
    key_storage: str = "file"
    """Where the API key is kept: ``keychain``, ``file``, or ``memory``.

    Reported so the interface can say something true about it. A fallback from
    the OS keychain to a plain file is a real downgrade in how a credential is
    protected, and the app should name it rather than let someone assume the
    stronger one."""
    ephemeral: bool = False
    """Whether the key is held in memory rather than written to disk.

    Surfaced so Settings can say where the key goes and be right about it. The
    copy differs completely between the two, and a sentence promising a file
    mode to someone whose key is never filed would be worse than none."""
    conflicts: list[Conflict] = []
    """Two files on disk claiming one entry, seen at the last rebuild.

    Empty on a healthy journal. Not empty means a sync client made a
    "(conflicted copy)" and one of the two is not being indexed — which is
    invisible otherwise, because both files look fine sitting there."""
    renamed_ids: list[RenamedId] = []
    """Entries whose declared id could not be used as a filename.

    Empty on a journal this app wrote every file of. Not empty means something
    else authored one — an imported archive, a synced folder, a hand edit — with
    an id that would have escaped the journal directory, so the entry was indexed
    under its filename instead. The thought is intact; anything pointing at the
    old id is not."""
    dormant: list[Dormant] = []
    """What is asleep for want of a key, and why.

    Empty when a key is present. Said out loud rather than left to be noticed:
    without one the app still writes, files, connects and draws, so nothing
    looks broken — and the capabilities that are missing are exactly the ones
    you would never think to look for."""


@router.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/status", response_model=Status)
def status(
    journal: Journal = Depends(get_journal),
    provider: MeteredProvider = Depends(get_provider),
    settings: Settings = Depends(get_settings_dep),
    store: SettingsStore = Depends(get_settings_store),
) -> Status:
    offline = provider.name == "echo"
    return Status(
        ok=True,
        version=__version__,
        provider=provider.name,
        offline=offline,
        model="offline" if offline else settings.gemini_model,
        entries=journal.index.count(authored_only=True),
        spend_this_month_usd=round(provider.spend_this_month(), 4),
        cost_ceiling_usd=settings.monthly_cost_ceiling_usd,
        data_dir=str(settings.data_dir),
        # Named from the store rather than guessed from configuration: the
        # keychain can be present and still refuse, and the honest answer is
        # what actually happened.
        key_storage=(
            "memory"
            if settings.ephemeral_settings
            else "keychain"
            if store.key_is_in_the_keychain
            else "file"
        ),
        ephemeral=settings.ephemeral_settings,
        conflicts=journal.index.conflicts,
        renamed_ids=journal.index.renamed_ids,
        dormant=(
            [Dormant(capability=name, why=why) for name, why in DORMANT_WITHOUT_KEY]
            if offline
            else []
        ),
    )


@router.post("/index/rebuild")
def rebuild_index(journal: Journal = Depends(get_journal)) -> dict[str, int]:
    """Discard the projection and rebuild it from Markdown on disk."""
    return {"indexed": journal.rebuild()}


CONFIRMATION = "DELETE"
"""The word a caller must send to erase everything.

Not a checkbox and not a second click. This is the only route in the app that
destroys writing, and it should be impossible to reach by a mis-fired request,
a replayed one, or a UI bug that fires a handler twice."""


class Erase(BaseModel):
    confirm: str = ""


@router.post("/erase")
def erase(
    payload: Erase,
    request: Request,
    background: BackgroundTasks,
    settings: Settings = Depends(get_settings_dep),
    journal: Journal = Depends(get_journal),
) -> dict[str, list[str]]:
    """Delete the journal and everything derived from it, then stop.

    Stopping is not tidiness. This process is serving *out of* the directories
    it is deleting, and unlinking a SQLite file that is still open does not
    fail on macOS — the file lives on until the last handle closes, so the app
    would go on answering from a database that no longer exists and recreate it
    on the next write. Closing the stores, deleting, and exiting is the only
    end state with nothing half-alive in it.

    The shutdown runs after the response is sent, so the caller is told what
    was removed rather than seeing the connection drop.
    """
    if payload.confirm != CONFIRMATION:
        raise HTTPException(
            codes.HTTP_400_BAD_REQUEST,
            f"Send {CONFIRMATION!r} to confirm. Nothing has been deleted.",
        )

    journal.index.close()
    if journal.vectors is not None:
        journal.vectors.close()

    # The key is not this button's business — "Forget the API key" is, and the
    # two are separate on purpose. But the fallback key file lives inside the
    # support directory, so erasing took it on a machine with no keychain while
    # a keychain entry survived untouched. The same action deleting your
    # credential or not, depending on a storage detail nobody chose and
    # `/status` does not always report correctly, is not a decision anyone made.
    # Held across the delete so both machines behave the way the button says.
    held_key = ""
    if settings.key_path.exists():
        with contextlib.suppress(OSError, ValueError):
            held_key = str(json.loads(settings.key_path.read_text()).get("gemini_api_key") or "")

    removed = []
    for directory in (settings.data_dir, settings.internal_dir):
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
            removed.append(str(directory))

    if held_key:
        write_key_file(settings.key_path, held_key)
    log.warning("erased %s", ", ".join(removed) or "nothing")

    # Only the thing that owns the server can stop it, and under a test client
    # there is no server at all — so this is inert in tests by construction
    # rather than by anyone remembering to stub it out. Without one the stores
    # are simply closed and the app is deliberately unusable until restart,
    # which is the same end state reached a moment later.
    server = getattr(request.app.state, "server", None)
    if server is not None:
        background.add_task(_stop, server)
    return {"removed": removed}


def _stop(server) -> None:
    """Take the server down in order, after the response has gone out.

    uvicorn's own shutdown flag rather than a signal: a signal would race the
    background task that sets it, and this process may not be the only thing
    the signal reaches.
    """
    server.should_exit = True
