"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from tilt import __version__
from tilt.agents import build_provider
from tilt.agents.ledger import MeteredProvider
from tilt.api.auth import TokenAuthMiddleware
from tilt.api.limits import BodyLimitMiddleware, check_exposure
from tilt.api.routes import (
    agent,
    brief,
    diagram,
    entries,
    graph,
    ingest,
    library,
    system,
)
from tilt.api.routes import settings as settings_routes
from tilt.config import Settings, get_settings
from tilt.embed import build_embedder
from tilt.jobs import Schedule
from tilt.journal import Journal
from tilt.persona import PersonaStore
from tilt.settings_store import SettingsStore
from tilt.store.artifacts import ArtifactStore
from tilt.store.brief import BriefStore
from tilt.store.index import Index
from tilt.store.vectors import VectorStore


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    # Before anything is built. Constructing the app and *then* discovering it
    # is open would leave a window where it is serving.
    check_exposure(settings.host, settings.auth_token)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.ensure_dirs()

        # Read before anything is constructed. A key typed into the app is a
        # more recent intent than one exported in a shell, and both the provider
        # and the embedder are chosen by whether one exists — so the settings
        # file has to be consulted before either is built.
        store = SettingsStore(
            settings.internal_dir / "settings.json",
            ephemeral=settings.ephemeral_settings,
        )
        runtime = store.load()
        if runtime.has_key:
            settings.gemini_api_key = runtime.gemini_api_key
            settings.gemini_model = runtime.gemini_model
            settings.provider = "auto"
        ceiling = runtime.monthly_cost_ceiling_usd or settings.monthly_cost_ceiling_usd

        index = Index(settings.index_path)
        # Its own file, so the disposable cache and the vectors that cost money
        # can be thrown away independently.
        vectors = VectorStore(settings.vectors_path)
        journal = Journal(
            settings.data_dir,
            index,
            vectors,
            build_embedder(settings),
            support_dir=settings.internal_dir,
        )

        # Files are authoritative; reconcile on boot so entries added by hand
        # (or by another machine syncing the folder) are picked up.
        journal.rebuild()

        app.state.settings = settings
        app.state.index = index
        app.state.vectors = vectors
        app.state.journal = journal
        app.state.settings_store = store
        app.state.persona = PersonaStore(settings.persona_path)
        app.state.artifacts = ArtifactStore(settings.diagrams_dir)
        # Not hung off the journal, and not indexed. Nothing in the brief is
        # part of the journal until it is read, and giving it a place inside
        # would blur the line the whole feature depends on.
        app.state.brief = BriefStore(settings.brief_dir)

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
            vectors.close()

    app = FastAPI(
        title="Tilt",
        version=__version__,
        summary="A thinking instrument, not a productivity tool.",
        lifespan=lifespan,
    )

    # Order matters: middleware added last runs outermost, and a 401 that never
    # passes back through CORS reaches the webview as an unreadable network
    # error instead of a message.
    if settings.auth_token:
        app.add_middleware(
            TokenAuthMiddleware,
            token=settings.auth_token,
            serving_interface=bool(settings.static_dir),
        )

    # Inside the auth gate: an unauthenticated caller should be turned away by
    # the token check rather than told how large a body this accepts.
    app.add_middleware(BodyLimitMiddleware)

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
    app.include_router(graph.router)
    app.include_router(diagram.router)
    app.include_router(brief.router)
    app.include_router(settings_routes.router)
    app.include_router(agent.router)

    # Last, so it never shadows an API route: mounted at "/" it would otherwise
    # answer for everything.
    if settings.static_dir and settings.static_dir.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=settings.static_dir, html=True),
            name="interface",
        )
    return app


app = create_app()
