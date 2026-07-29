from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tilt.agents.echo import EchoProvider
from tilt.agents.ledger import MeteredProvider
from tilt.api.app import create_app
from tilt.config import Settings
from tilt.journal import Journal
from tilt.store.index import Index


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "journal",
        provider="echo",
        monthly_cost_ceiling_usd=1.0,
        # Tests drive the jobs directly. A live scheduler would fire the sweep
        # underneath them and make assertions about what the agent has touched
        # depend on how long the suite took to run.
        schedule_enabled=False,
    )


@pytest.fixture
def index(settings: Settings) -> Index:
    settings.ensure_dirs()
    idx = Index(settings.index_path)
    yield idx
    idx.close()


@pytest.fixture
def journal(settings: Settings, index: Index) -> Journal:
    return Journal(settings.data_dir, index)


@pytest.fixture
def provider(index: Index) -> MeteredProvider:
    return MeteredProvider(EchoProvider(), index, ceiling_usd=1.0)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    with TestClient(create_app(settings)) as c:
        yield c
