"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tilt.agents import build_provider
from tilt.agents.ledger import MeteredProvider
from tilt.api.auth import TokenAuthMiddleware
from tilt.api.routes import agent, entries, ingest, library, system
from tilt.api.routes import settings as settings_routes
from tilt.config import Settings, get_settings
from tilt.jobs import Schedule
from tilt.journal import Journal
from tilt.persona import PersonaStore
from tilt.settings_store import SettingsStore
from tilt.store.index import Index


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.ensure_dirs()
        index = Index(settings.index_path)
        journal = Journal(settings.data_dir, index)

        # Files are authoritative; reconcile on boot so entries added by hand
        # (or by another machine syncing the folder) are picked up.
        journal.rebuild()

        app.state.settings = settings
        app.state.index = index
        app.state.journal = journal
        app.state.persona = PersonaStore(settings.internal_dir / "agent.json")

        # Runtime settings win over the environment: a key typed into the app
        # is a more recent intent than one exported in a shell.
        store = SettingsStore(settings.internal_dir / "settings.json")
        app.state.settings_store = store
        runtime = store.load()
        if runtime.has_key:
            settings.gemini_api_key = runtime.gemini_api_key
            settings.gemini_model = runtime.gemini_model
            settings.provider = "auto"
        ceiling = runtime.monthly_cost_ceiling_usd or settings.monthly_cost_ceiling_usd

        provider = MeteredProvider(build_provider(settings), index, ceiling)
        app.state.provider = provider

        # Started after everything it touches exists, and only once the app is
        # actually serving — a job that fired mid-boot would race the rebuild
        # above and file entries the index had not finished reading.
        schedule = Schedule(journal, provider, settings)
        app.state.schedule = schedule
        if settings.schedule_enabled:
            schedule.start()

        try:
            yield
        finally:
            schedule.shutdown()
            index.close()

    app = FastAPI(
        title="Tilt",
        version="0.1.0",
        summary="A thinking instrument, not a productivity tool.",
        lifespan=lifespan,
    )

    # Order matters: middleware added last runs outermost, and a 401 that never
    # passes back through CORS reaches the webview as an unreadable network
    # error instead of a message.
    if settings.auth_token:
        app.add_middleware(TokenAuthMiddleware, token=settings.auth_token)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router)
    app.include_router(entries.router)
    app.include_router(library.router)
    app.include_router(ingest.router)
    app.include_router(settings_routes.router)
    app.include_router(agent.router)
    return app


app = create_app()
