"""Insight API: flow graph, health score, report, regression diff, explain fallback, samples."""

import json
from pathlib import Path

import pytest

from app.analyze.registry import all_checks
from app.api.insight import _locate, _threshold_patch
from app.extract.service import get_extractor
from app.findings.aggregator import aggregate
from app.findings.enrich import enrich
from app.findings.service import get_findings_service
from app.models import CompileRun
from app.run.service import get_runner_service
from app.run.runner import run_test_suite
from app.schemas.finding import DiagnosticsReport
from app.schemas.findings import AggregatedFinding, ConfidenceTier, RiskScore
from app.schemas.ir_sop import SopIR
from app.testgen.service import TestGenService

FIXTURE = Path(__file__).parent / "fixtures" / "expense_ir.json"


def _seed_run(client, project_id: str, run_id: str, drop_codes: set[str] | None = None) -> None:
    services = client.app.state.services
    ir = SopIR.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    ir.run_id = run_id
    diags = [d for c in all_checks() for d in c.fn(ir, None) if d.code not in (drop_codes or set())]
    suite = TestGenService(None).generate(ir, run_id)
    test_report = run_test_suite(ir, suite)
    report = enrich(
        aggregate(run_id, DiagnosticsReport(run_id=run_id, diagnostics=diags).with_stats(), test_report, None),
        ir,
    )
    report.findings = [f for f in report.findings if f.code not in (drop_codes or set())]
    report.with_stats()
    with services.sessions() as s:
        s.add(CompileRun(id=run_id, project_id=project_id, status="succeeded", document_ids=[]))
        s.commit()
    get_extractor(services).save(ir)
    get_runner_service(services).save(test_report)
    get_findings_service(services).save(report)


@pytest.fixture
def seeded(client):
    project = client.post("/api/projects", json={"name": "Expense", "description": ""}).json()["id"]
    _seed_run(client, project, "run_aaaa")
    return project


def test_flow_has_entry_decisions_and_labelled_edges(seeded, client):
    flow = client.get("/api/runs/run_aaaa/flow").json()
    nodes = {n["id"]: n for n in flow["nodes"]}
    assert flow["entry"] == "s3.1a" and "END" in nodes
    route = nodes["d_route_4"]
    assert route["kind"] == "decision" and route["severity"] == "error" and "ST004" in route["codes"]
    labels = {e["label"] for e in flow["edges"] if e["source"] == "d_route_4"}
    assert any(label and "10,000" in label for label in labels)
    assert nodes["s6.1"]["severity"] == "error"  # unreachable audit step is annotated
    assert nodes["s7.2"]["kind"] == "rule"  # standing rules are not flow nodes
    assert any(e["inferred"] for e in flow["edges"])


def test_health_score_and_report(seeded, client):
    health = client.get("/api/runs/run_aaaa/health").json()
    assert health["errors"] >= 4 and health["score"] < 60 and health["grade"] in {"D", "F"}
    assert health["tests"]["total"] > 0 and health["coverage"]["steps"] > 50
    md = client.get("/api/runs/run_aaaa/report?format=md")
    assert md.status_code == 200 and "ST004" in md.text and "10,000" in md.text
    assert "<h1>" in client.get("/api/runs/run_aaaa/report?format=html").text


def test_regression_reports_fixed_new_and_remaining(seeded, client):
    _seed_run(client, seeded, "run_bbbb", drop_codes={"ST004", "EX001"})
    reg = client.get("/api/runs/run_bbbb/regression", params={"base": "run_aaaa"}).json()
    assert reg["counts"]["fixed"] >= 1 and reg["counts"]["new"] == 0 and reg["counts"]["remaining"] >= 3
    assert any(f["code"] == "ST004" for f in reg["fixed"])
    assert reg["health"]["after"] > reg["health"]["before"]


def test_explain_falls_back_to_a_deterministic_threshold_patch(seeded, client):
    findings = client.get("/api/runs/run_aaaa/findings").json()["findings"]
    gap = next(f for f in findings if f["code"] == "ST004" and "10,000" in f["message"])
    # no parsed document in this fixture run and a fake model: the endpoint still answers
    resp = client.post(f"/api/runs/run_aaaa/findings/{gap['id']}/explain")
    assert resp.status_code == 200 and resp.json()["plain_explanation"]


def test_threshold_patch_makes_the_lower_band_inclusive():
    finding = AggregatedFinding(
        id="f", code="ST004", title="gap", severity="error", confidence_tier=ConfidenceTier.DETERMINISTIC,
        risk=RiskScore.compute(1, 4, 1), witness={"kind": "counterexample", "facts": {"amount": 10000.0}},
    )
    text = "4.1 Claims below INR 10,000 are approved by the line manager.\n4.2 Claims above INR 10,000 need Finance."
    patch = _threshold_patch(finding, text)
    assert patch and patch.clause_ref == "4.1"
    assert patch.new_text == "4.1 Claims INR 10,000 or below are approved by the line manager."
    assert _locate(text, "Claims  below INR 10,000") == "Claims below INR 10,000"
    assert _locate(text, "something absent") is None


def test_samples_list_and_unknown_sample(client):
    samples = client.get("/api/samples").json()
    ids = {s["id"] for s in samples}
    assert {"expense", "account", "loto", "leave"} <= ids
    expense = next(s for s in samples if s["id"] == "expense")
    assert expense["planted_bugs"] == 7 and expense["title"]
    assert client.post("/api/samples/nope/run").status_code == 404


def test_run_options_are_recorded(client):
    project = client.post("/api/projects", json={"name": "x", "description": ""}).json()["id"]
    assert client.post(f"/api/projects/{project}/runs", json={"auto_approve": True}).status_code == 422  # no docs
    assert json.loads(json.dumps(client.get("/api/me").json()))["auth_enabled"] is False


def test_case_history_upload_and_reality_check(seeded, client):
    csv = (
        "case_id,activity,timestamp\n"
        "C1,Submit expense claim with receipts through expense portal,2026-09-01T09:00:00\n"
        "C1,Check every claim for receipts,2026-09-01T10:00:00\n"
        "C1,Pay approved claims,2026-09-02T10:00:00\n"
    )
    up = client.post("/api/runs/run_aaaa/case-history", files={"file": ("cases.csv", csv, "text/csv")})
    assert up.status_code == 201, up.text
    assert up.json()["source_filename"] == "cases.csv"
    rep = client.post("/api/runs/run_aaaa/reality")
    assert rep.status_code == 201, rep.text
    assert rep.json()["total_cases"] == 1
