"""Runtime settings — the API key and model, changeable from inside the app."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from tilt.agents import AgentError, build_provider
from tilt.agents.ledger import MeteredProvider
from tilt.api.deps import get_settings_store
from tilt.settings_store import PublicSettings, RuntimeSettingsUpdate, SettingsStore

router = APIRouter(prefix="/settings", tags=["settings"])


def _rebuild_provider(request: Request) -> None:
    """Swap the live provider so a new key takes effect without a restart."""
    app = request.app
    runtime = app.state.settings_store.load()
    boot = app.state.settings

    # Runtime settings win over the environment: the user just typed this.
    boot.gemini_api_key = runtime.gemini_api_key or None
    boot.gemini_model = runtime.gemini_model
    boot.monthly_cost_ceiling_usd = runtime.monthly_cost_ceiling_usd
    boot.provider = "auto"

    app.state.provider = MeteredProvider(
        build_provider(boot), app.state.index, runtime.monthly_cost_ceiling_usd
    )


@router.get("", response_model=PublicSettings)
def read_settings(store: SettingsStore = Depends(get_settings_store)) -> PublicSettings:
    """The key is never returned — only whether one is set, and its last four."""
    return store.public()


@router.patch("", response_model=PublicSettings)
def write_settings(
    payload: RuntimeSettingsUpdate,
    request: Request,
    store: SettingsStore = Depends(get_settings_store),
) -> PublicSettings:
    store.update(payload)
    try:
        _rebuild_provider(request)
    except AgentError as exc:
        # The settings are saved either way; only the swap failed.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return store.public()
