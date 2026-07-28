"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tilt.agents import build_provider
from tilt.agents.ledger import MeteredProvider
from tilt.api.routes import agent, entries, library, system
from tilt.config import Settings, get_settings
from tilt.journal import Journal
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
        app.state.provider = MeteredProvider(
            build_provider(settings), index, settings.monthly_cost_ceiling_usd
        )
        try:
            yield
        finally:
            index.close()

    app = FastAPI(
        title="Tilt",
        version="0.1.0",
        summary="A thinking instrument, not a productivity tool.",
        lifespan=lifespan,
    )

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
    app.include_router(agent.router)
    return app


app = create_app()
