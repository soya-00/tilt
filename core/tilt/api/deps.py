"""Shared request dependencies.

Singletons live on ``app.state`` and are handed to routes through these
accessors, which keeps route modules free of import-time globals and lets tests
swap in a temporary journal and an offline provider.
"""

from __future__ import annotations

from fastapi import Request

from tilt.agents.ledger import MeteredProvider
from tilt.config import Settings
from tilt.journal import Journal
from tilt.persona import PersonaStore
from tilt.settings_store import SettingsStore
from tilt.store.artifacts import ArtifactStore
from tilt.store.brief import BriefStore


def get_journal(request: Request) -> Journal:
    return request.app.state.journal


def get_provider(request: Request) -> MeteredProvider:
    return request.app.state.provider


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_artifacts(request: Request) -> ArtifactStore:
    return request.app.state.artifacts


def get_brief(request: Request) -> BriefStore:
    return request.app.state.brief


def get_persona_store(request: Request) -> PersonaStore:
    return request.app.state.persona


def get_settings_store(request: Request) -> SettingsStore:
    return request.app.state.settings_store
