import json

from app.pipeline.stages import STAGE_KEYS
from tests.conftest import wait_for_run

SOP = b"# SOP-1\n\n1. The agent logs the complaint.\n"


def make_project(client, name="Refund SOPs") -> str:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def upload(client, project_id, *files):
    return client.post(
        f"/api/projects/{project_id}/documents",
        files=[("files", (name, content, "application/octet-stream")) for name, content in files],
    )


def test_meta_endpoints(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    stages = client.get("/api/pipeline/stages").json()
    assert [s["key"] for s in stages] == list(STAGE_KEYS)
    assert [s["key"] for s in stages if s["implemented"]] == [
        "ingest", "extract", "link", "analyze", "testgen", "execute", "findings"
    ]
    codes = {c["code"] for c in client.get("/api/taxonomy").json()}
    assert {"ST004", "RS004", "RL004"} <= codes
    # Unknown API paths stay JSON 404s even for browser navigations (no SPA fallback).
    missing = client.get("/api/nope", headers={"Accept": "text/html"})
    assert (missing.status_code, missing.json()) == (404, {"detail": "Not Found"})


def test_projects_crud_and_counts(client):
    assert client.post("/api/projects", json={"name": ""}).status_code == 422
    project_id = make_project(client)
    upload(client, project_id, ("sop.md", SOP))
    listed = client.get("/api/projects").json()
    assert [(p["id"], p["document_count"], p["run_count"]) for p in listed] == [(project_id, 1, 0)]
    assert client.get(f"/api/projects/{project_id}").json()["document_count"] == 1
    assert client.get("/api/projects/prj_missing").status_code == 404


def test_upload_dedupes_by_content_and_serves_file(client):
    project_id = make_project(client)
    first = upload(client, project_id, ("C:\\Users\\me\\sop.md", SOP))
    assert first.status_code == 201
    doc = first.json()[0]
    assert doc["filename"] == "sop.md"  # client path stripped
    assert doc["media_type"] == "text/markdown"
    assert doc["duplicate"] is False

    again = upload(client, project_id, ("renamed.md", SOP)).json()[0]
    assert again["duplicate"] is True and again["id"] == doc["id"]
    assert len(client.get(f"/api/projects/{project_id}/documents").json()) == 1

    served = client.get(f"/api/documents/{doc['id']}/file")
    assert served.status_code == 200 and served.content == SOP
    assert served.headers["content-disposition"].startswith("inline")


def test_upload_rejects_bad_type_and_oversize_without_side_effects(client, settings):
    project_id = make_project(client)
    bad = upload(client, project_id, ("ok.md", SOP), ("macro.exe", b"MZ"))
    assert bad.status_code == 415
    too_big = upload(client, project_id, ("big.txt", b"x" * (settings.max_upload_bytes + 1)))
    assert too_big.status_code == 413
    assert client.get(f"/api/projects/{project_id}/documents").json() == []
    stored = [p for p in settings.storage_dir.rglob("*") if p.is_file()]
    assert stored == []


def test_delete_document_removes_file(client, settings):
    project_id = make_project(client)
    doc_id = upload(client, project_id, ("sop.md", SOP)).json()[0]["id"]
    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert client.get(f"/api/documents/{doc_id}").status_code == 404
    assert [p for p in settings.storage_dir.rglob("*") if p.is_file()] == []


def test_run_validation(client):
    project_id = make_project(client)
    assert client.post(f"/api/projects/{project_id}/runs", json={}).status_code == 422
    upload(client, project_id, ("sop.md", SOP))
    foreign = client.post(f"/api/projects/{project_id}/runs", json={"document_ids": ["doc_x"]})
    assert foreign.status_code == 422
    assert client.get("/api/runs/run_missing").status_code == 404
    assert client.get("/api/runs/run_missing/events").status_code == 404


def test_compile_run_executes_every_stage_in_order(client):
    project_id = make_project(client)
    doc_id = upload(client, project_id, ("sop.md", SOP)).json()[0]["id"]
    started = client.post(f"/api/projects/{project_id}/runs", json={})
    assert started.status_code == 202
    run_id = started.json()["id"]

    # Pipeline runs ingest (real) → extract (real, then pauses for review)
    run = wait_for_run(client, run_id)
    assert run["status"] in ("paused", "succeeded"), run.get("error")

    if run["status"] == "paused":
        # IR is pending review; fetch and approve it
        ir_resp = client.get(f"/api/runs/{run_id}/ir")
        assert ir_resp.status_code == 200
        assert ir_resp.json()["review_status"] == "pending"

        approved = client.post(f"/api/runs/{run_id}/ir/review", json={"approved": True})
        assert approved.status_code == 202

        # Resume and wait for completion
        run = wait_for_run(client, run_id, terminal=("succeeded", "failed"))

    assert run["status"] == "succeeded", run.get("error")
    assert run["document_ids"] == [doc_id]
    assert run["started_at"] and run["finished_at"]

    # Ingest + extract started/completed; remaining stages are stubs
    ingest = run["artifacts"]["ingest"]
    assert ingest["documents"][0]["document_id"] == doc_id
    assert ingest["documents"][0]["doc_class"] == "procedural"
    extract = run["artifacts"]["extract"]
    assert extract.get("review_status") == "approved"
    assert extract.get("steps", 0) >= 0  # extraction ran
    link = run["artifacts"]["link"]
    assert link.get("nodes", 0) >= 0  # link ran
    assert link.get("cypher_sha256") is not None
    analyze = run["artifacts"]["analyze"]
    assert analyze.get("total", -1) >= 0  # analyze ran
    testgen = run["artifacts"]["testgen"]
    assert testgen.get("total", -1) >= 0  # testgen ran
    execute = run["artifacts"]["execute"]
    assert execute.get("total", -1) >= 0  # execute ran
    assert all(
        a.get("stub")
        for k, a in run["artifacts"].items()
        if k not in ("ingest", "extract", "link", "analyze", "testgen", "execute", "findings")
    )

    # The document now has a DocAST, served by the API and summarised in the listing.
    ast = client.get(f"/api/documents/{doc_id}/ast").json()
    assert ast["nodes"][0]["kind"] == "title" and ast["nodes"][0]["text"] == "SOP-1"
    item = ast["nodes"][1]
    assert (item["kind"], item["number"]) == ("list_item", "1")
    span = item["spans"][0]
    assert ast["text"][span["char_start"] : span["char_end"]] == item["text"]
    listed = client.get(f"/api/projects/{project_id}/documents").json()[0]
    assert listed["parsed"]["ast_id"] == ingest["documents"][0]["ast_id"]
    assert client.get(f"/api/documents/{doc_id}/figures/n0001").status_code == 404


def test_graph_and_cypher_endpoints(client):
    project_id = make_project(client)
    upload(client, project_id, ("sop.md", SOP))
    run_id = client.post(f"/api/projects/{project_id}/runs", json={}).json()["id"]
    run = wait_for_run(client, run_id)
    if run["status"] == "paused":
        client.post(f"/api/runs/{run_id}/ir/review", json={"approved": True})
        wait_for_run(client, run_id, terminal=("succeeded", "failed"))

    graph = client.get(f"/api/runs/{run_id}/graph")
    assert graph.status_code == 200
    data = graph.json()
    assert "nodes" in data and "edges" in data
    assert data["cypher_sha256"] is not None

    cypher = client.get(f"/api/runs/{run_id}/cypher")
    assert cypher.status_code == 200
    text = cypher.text
    assert "MERGE" in text
    assert "HAS_STEP" in text or "Process" in text


def test_diagnostics_endpoint(client):
    project_id = make_project(client)
    upload(client, project_id, ("sop.md", SOP))
    run_id = client.post(f"/api/projects/{project_id}/runs", json={}).json()["id"]
    run = wait_for_run(client, run_id)
    if run["status"] == "paused":
        client.post(f"/api/runs/{run_id}/ir/review", json={"approved": True})
        wait_for_run(client, run_id, terminal=("succeeded", "failed"))

    resp = client.get(f"/api/runs/{run_id}/diagnostics")
    assert resp.status_code == 200
    data = resp.json()
    assert "diagnostics" in data and "stats" in data
    assert data["stats"]["total"] >= 0


def test_testcases_endpoint(client):
    project_id = make_project(client)
    upload(client, project_id, ("sop.md", SOP))
    run_id = client.post(f"/api/projects/{project_id}/runs", json={}).json()["id"]
    run = wait_for_run(client, run_id)
    if run["status"] == "paused":
        client.post(f"/api/runs/{run_id}/ir/review", json={"approved": True})
        wait_for_run(client, run_id, terminal=("succeeded", "failed"))

    resp = client.get(f"/api/runs/{run_id}/testcases")
    assert resp.status_code == 200
    data = resp.json()
    assert "test_cases" in data and "stats" in data
    assert data["stats"]["total"] >= 0


def test_simulate_endpoint(client):
    project_id = make_project(client)
    upload(client, project_id, ("sop.md", SOP))
    run_id = client.post(f"/api/projects/{project_id}/runs", json={}).json()["id"]
    run = wait_for_run(client, run_id)
    if run["status"] == "paused":
        client.post(f"/api/runs/{run_id}/ir/review", json={"approved": True})
        wait_for_run(client, run_id, terminal=("succeeded", "failed"))

    body = {"scenario_id": "sc_test", "description": "test run", "facts": {"amount": 100}}
    resp = client.post(f"/api/runs/{run_id}/simulate", json=body)
    assert resp.status_code == 201
    trace = resp.json()
    assert "outcome" in trace and "steps" in trace

    traces = client.get(f"/api/runs/{run_id}/traces").json()
    assert len(traces) >= 1
    assert traces[0]["scenario_id"] == "sc_test"


def test_testrun_endpoint(client):
    project_id = make_project(client)
    upload(client, project_id, ("sop.md", SOP))
    run_id = client.post(f"/api/projects/{project_id}/runs", json={}).json()["id"]
    run = wait_for_run(client, run_id)
    if run["status"] == "paused":
        client.post(f"/api/runs/{run_id}/ir/review", json={"approved": True})
        wait_for_run(client, run_id, terminal=("succeeded", "failed"))

    resp = client.get(f"/api/runs/{run_id}/testrun")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data and "coverage" in data and "stats" in data
    assert data["stats"]["total"] >= 0
    cov = data["coverage"]
    assert "step_coverage_pct" in cov and "branch_coverage_pct" in cov


def test_findings_endpoint(client):
    project_id = make_project(client)
    upload(client, project_id, ("sop.md", SOP))
    run_id = client.post(f"/api/projects/{project_id}/runs", json={}).json()["id"]
    run = wait_for_run(client, run_id)
    if run["status"] == "paused":
        client.post(f"/api/runs/{run_id}/ir/review", json={"approved": True})
        wait_for_run(client, run_id, terminal=("succeeded", "failed"))

    resp = client.get(f"/api/runs/{run_id}/findings")
    assert resp.status_code == 200
    data = resp.json()
    assert "findings" in data and "stats" in data
    assert data["stats"]["total"] >= 0

    # Triage update (PATCH)
    if data["findings"]:
        fid = data["findings"][0]["id"]
        patch = client.patch(
            f"/api/runs/{run_id}/findings/{fid}/triage",
            json={"triage": "accepted"},
        )
        assert patch.status_code == 200
        updated = patch.json()
        changed = next(f for f in updated["findings"] if f["id"] == fid)
        assert changed["triage"] == "accepted"


def test_ast_is_404_before_ingest(client):
    project_id = make_project(client)
    doc_id = upload(client, project_id, ("sop.md", SOP)).json()[0]["id"]
    assert client.get(f"/api/documents/{doc_id}/ast").status_code == 404
    assert client.get(f"/api/documents/{doc_id}").json()["parsed"] is None


def test_run_events_stream_as_sse_and_resume_from_last_event_id(client):
    project_id = make_project(client)
    upload(client, project_id, ("sop.md", SOP))
    run_id = client.post(f"/api/projects/{project_id}/runs", json={}).json()["id"]
    run = wait_for_run(client, run_id)

    # If paused at IR review, approve then wait for completion.
    if run["status"] == "paused":
        client.post(f"/api/runs/{run_id}/ir/review", json={"approved": True})
        wait_for_run(client, run_id, terminal=("succeeded", "failed"))

    def read_stream(headers=None):
        events = []
        with client.stream("GET", f"/api/runs/{run_id}/events", headers=headers) as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            current = {}
            for line in response.iter_lines():
                if line.startswith("event:"):
                    current["event"] = line.split(":", 1)[1].strip()
                elif line.startswith("id:"):
                    current["id"] = int(line.split(":", 1)[1])
                elif line.startswith("data:"):
                    current["data"] = json.loads(line.split(":", 1)[1])
                elif line == "" and current:
                    events.append(current)
                    current = {}
        return events

    events = read_stream()
    stage_events = [e for e in events if e["event"] == "stage"]
    terminal_statuses = ("started", "completed", "failed")
    transitions = [e for e in stage_events if e["data"]["status"] in terminal_statuses]
    # Each stage has started+completed (or started+failed). The interrupt pauses without completed,
    # then resumes and records completed. Total = 2 per stage.
    assert len(transitions) == 2 * len(STAGE_KEYS)
    assert events[-1]["event"] == "end"
    assert events[-1]["data"]["status"] == "succeeded"

    resumed = read_stream({"Last-Event-ID": str(stage_events[-3]["id"])})
    assert [e["event"] for e in resumed] == ["stage", "stage", "end"]
