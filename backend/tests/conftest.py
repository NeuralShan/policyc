import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import run_migrations
from app.core.services import Services
from app.main import create_app
from tests.fakes import fake_factory

GOLDEN = Path(__file__).resolve().parents[2] / "golden"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # _env_file=None: tests never pick up a developer's backend/.env (and its API key)
    return Settings(_env_file=None, data_dir=tmp_path / "data", max_upload_mb=1)


@pytest.fixture
def services(settings: Settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(settings.resolved_database_url)
    built = Services.build(settings, fake_factory())
    yield built
    built.engine.dispose()


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings, fake_factory())) as test_client:
        yield test_client


def wait_for_run(
    client: TestClient,
    run_id: str,
    timeout_s: float = 120.0,
    terminal: tuple[str, ...] = ("succeeded", "failed", "paused"),
) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in terminal:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish within {timeout_s}s")
