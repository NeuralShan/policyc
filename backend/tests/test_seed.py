"""A fresh deployment (empty database, empty disk) opens with the precomputed sample runs."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.seed import SEED_FILE
from tests.fakes import fake_factory

pytestmark = pytest.mark.skipif(not SEED_FILE.is_file(), reason="no bundled seed")


def test_cold_start_loads_samples_that_open_instantly(tmp_path: Path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", seed_demo=True)
    with TestClient(create_app(settings, fake_factory())) as client:
        samples = {s["id"]: s for s in client.get("/api/samples").json()}
        assert len(samples) == 9 and all(s["precomputed"] for s in samples.values())

        started = client.post("/api/samples/expense/run").json()
        assert started["cached"] is True
        run = started["run_id"]
        assert client.get(f"/api/runs/{run}").json()["status"] == "succeeded"

        health = client.get(f"/api/runs/{run}/health").json()
        assert health["errors"] >= 4 and health["tests"]["total"] > 0
        flow = client.get(f"/api/runs/{run}/flow").json()
        assert flow["entry"] and any(n["kind"] == "decision" for n in flow["nodes"])
        codes = {f["code"] for f in client.get(f"/api/runs/{run}/findings").json()["findings"]}
        assert {"ST004", "ST005", "RS004", "ST001", "TM002"} <= codes

        # the source PDF and its parsed AST came along
        doc = client.get(f"/api/runs/{run}").json()["document_ids"][0]
        assert client.get(f"/api/documents/{doc}/ast").status_code == 200
        assert client.get(f"/api/documents/{doc}/file").status_code == 200

        # public demo data is not duplicated by a second start
    with TestClient(create_app(settings, fake_factory())) as client:
        assert len(client.get("/api/projects").json()) == 9
