"""Optional Firebase auth: disabled = unchanged behaviour; enabled = guests read-only."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.core.config import Settings
from app.main import create_app
from app.models import Project
from tests.fakes import fake_factory

PROJECT_ID = "test-fb"


@pytest.fixture
def fake_tokens(monkeypatch):
    table = {
        "tok-a": {"sub": "uid-a", "email": "a@x.com", "name": "Alice", "picture": "p"},
        "tok-b": {"sub": "uid-b", "email": "b@x.com"},
    }
    monkeypatch.setattr(auth, "verify_token", lambda token, pid: table.get(token))


@pytest.fixture
def auth_client(tmp_path: Path, fake_tokens):
    settings = Settings(
        _env_file=None, data_dir=tmp_path / "data", firebase_project_id=PROJECT_ID, max_upload_mb=1,
        seed_demo=False
    )
    with TestClient(create_app(settings, fake_factory())) as c:
        # a bundled public demo project (owner_uid NULL)
        with c.app.state.services.sessions() as s:
            s.add(Project(id="prj_demo", name="Demo", description=""))
            s.commit()
        yield c


def bearer(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def test_auth_disabled_is_unchanged(client):
    me = client.get("/api/me").json()
    assert me["auth_enabled"] is False and me["uid"] is None
    pid = client.post("/api/projects", json={"name": "P", "description": ""}).json()["id"]
    assert [p["id"] for p in client.get("/api/projects").json()] == [pid]
    assert client.get(f"/api/projects/{pid}").status_code == 200
    # a token is ignored entirely
    assert client.get("/api/projects", headers=bearer("whatever")).status_code == 200


def test_guest_cannot_write(auth_client):
    r = auth_client.post("/api/projects", json={"name": "P", "description": ""})
    assert r.status_code == 401 and r.json() == {"detail": "Sign in required"}
    r = auth_client.post("/api/projects", json={"name": "P"}, headers=bearer("garbage"))
    assert r.status_code == 401
    r = auth_client.post("/api/projects/prj_demo/runs", json={})
    assert r.status_code == 401


def test_guest_reads_public_project(auth_client):
    assert [p["id"] for p in auth_client.get("/api/projects").json()] == ["prj_demo"]
    assert auth_client.get("/api/projects/prj_demo").status_code == 200
    assert auth_client.get("/api/projects/prj_demo/documents").status_code == 200
    assert auth_client.get("/api/projects/prj_demo/runs").status_code == 200
    me = auth_client.get("/api/me").json()
    assert me["auth_enabled"] is True and me["uid"] is None


def test_user_ownership_isolation(auth_client):
    r = auth_client.post(
        "/api/projects", json={"name": "A's", "description": ""}, headers=bearer("tok-a")
    )
    assert r.status_code == 201
    pid = r.json()["id"]

    ids_a = {p["id"] for p in auth_client.get("/api/projects", headers=bearer("tok-a")).json()}
    ids_b = {p["id"] for p in auth_client.get("/api/projects", headers=bearer("tok-b")).json()}
    ids_guest = {p["id"] for p in auth_client.get("/api/projects").json()}
    assert ids_a == {"prj_demo", pid}
    assert ids_b == ids_guest == {"prj_demo"}

    assert auth_client.get(f"/api/projects/{pid}", headers=bearer("tok-a")).status_code == 200
    assert auth_client.get(f"/api/projects/{pid}", headers=bearer("tok-b")).status_code == 404
    assert auth_client.get(f"/api/projects/{pid}").status_code == 404
    assert auth_client.get(f"/api/projects/{pid}/runs", headers=bearer("tok-b")).status_code == 404
    # signed-in users cannot modify the public demo either
    r = auth_client.post("/api/projects/prj_demo/runs", json={}, headers=bearer("tok-a"))
    assert r.status_code == 403


def test_run_and_document_ownership(auth_client):
    pid = auth_client.post(
        "/api/projects", json={"name": "A's", "description": ""}, headers=bearer("tok-a")
    ).json()["id"]
    assert auth_client.get("/api/runs/run_nope", headers=bearer("tok-a")).status_code == 404
    with auth_client.app.state.services.sessions() as s:
        from app.models import CompileRun, Document

        run = CompileRun(project_id=pid)
        s.add(run)
        s.flush()
        doc = Document(
            project_id=pid,
            filename="f.txt",
            media_type="text/plain",
            sha256="0" * 64,
            size_bytes=1,
            storage_key="k",
        )
        s.add(doc)
        s.commit()
        run_id, doc_id = run.id, doc.id
    for url in (f"/api/runs/{run_id}", f"/api/documents/{doc_id}"):
        assert auth_client.get(url, headers=bearer("tok-a")).status_code == 200
        assert auth_client.get(url, headers=bearer("tok-b")).status_code == 404
        assert auth_client.get(url).status_code == 404
    # SSE endpoint is guarded too (404 before streaming starts)
    assert auth_client.get(f"/api/runs/{run_id}/events", headers=bearer("tok-b")).status_code == 404


def test_access_token_query_param(auth_client):
    pid = auth_client.post(
        "/api/projects", json={"name": "A's", "description": ""}, headers=bearer("tok-a")
    ).json()["id"]
    assert auth_client.get(f"/api/projects/{pid}?access_token=tok-a").status_code == 200
    assert auth_client.get(f"/api/projects/{pid}?access_token=tok-b").status_code == 404
    assert auth_client.get("/api/me?access_token=tok-a").json()["uid"] == "uid-a"


def test_me_signed_in(auth_client):
    me = auth_client.get("/api/me", headers=bearer("tok-a")).json()
    assert me.pop("parsing") in {"full", "lite"}
    assert me == {
        "auth_enabled": True,
        "uid": "uid-a",
        "email": "a@x.com",
        "name": "Alice",
        "picture": "p",
    }


def test_cors_env_parsing_and_preflight(tmp_path, monkeypatch):
    monkeypatch.setenv("PC_CORS_ORIGINS", "https://x.web.app, https://x.firebaseapp.com/")
    assert Settings(_env_file=None).cors_origins == [
        "https://x.web.app",
        "https://x.firebaseapp.com",
    ]
    monkeypatch.setenv("PC_CORS_ORIGINS", '["https://y.web.app"]')
    assert Settings(_env_file=None).cors_origins == ["https://y.web.app"]
    monkeypatch.delenv("PC_CORS_ORIGINS")
    assert Settings(_env_file=None).cors_origins == ["http://localhost:5173"]

    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "d",
        cors_origins=["https://x.web.app"],
        cors_origin_regex=r"https://x--pr-\d+\.web\.app",
    )
    with TestClient(create_app(settings, fake_factory())) as c:
        for origin in ("https://x.web.app", "https://x--pr-3.web.app"):
            r = c.options(
                "/api/projects",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            assert r.status_code == 200
            assert r.headers["access-control-allow-origin"] == origin
            assert "access-control-allow-credentials" not in r.headers
        r = c.options(
            "/api/projects",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in r.headers
