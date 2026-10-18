"""Golden checks for the deterministic engine on the expense SOP (no LLM, no network).

``expense_ir_raw.json`` is what the first extraction produced (flat, unlinked steps, ``always``
conditions); ``expense_ir.json`` is a real Gemini extraction after flow normalisation.  Both must
yield the bugs planted in the SOP, and nothing spurious.
"""

import json
from pathlib import Path

import pytest

from app.analyze.registry import all_checks
from app.extract.flow import normalize_flow
from app.findings.aggregator import aggregate
from app.findings.enrich import enrich
from app.run.runner import run_test_suite
from app.schemas.finding import DiagnosticsReport
from app.schemas.ir_sop import SopIR
from app.testgen.service import TestGenService

FIXTURES = Path(__file__).parent / "fixtures"
HEADINGS = {"1": "Purpose", "2": "Scope", "3": "Submission", "4": "Approval",
            "5": "Payment", "6": "Audit", "7": "Controls"}


def _diagnostics(ir):
    return [d for c in all_checks() for d in c.fn(ir, None)]


@pytest.fixture(params=["raw", "normalised"])
def expense_ir(request):
    if request.param == "raw":
        data = json.loads((FIXTURES / "expense_ir_raw.json").read_text(encoding="utf-8"))
        ir = SopIR.model_validate(data)
        normalize_flow(ir.processes[0], ir.symbols, HEADINGS)
    else:
        ir = SopIR.model_validate_json((FIXTURES / "expense_ir.json").read_text(encoding="utf-8"))
    return ir


def test_planted_bugs_are_found(expense_ir):
    diags = _diagnostics(expense_ir)
    codes = [d.code for d in diags]
    by_code = {c: [d for d in diags if d.code == c] for c in set(codes)}

    # claims of exactly 10,000 fall through the gap (E102)
    gap = next(d for d in by_code["ST004"] if "10,000" in d.message)
    assert gap.evidence["counterexample"]["amount"] == 10000
    # a manager's / the Finance Head's claim under 10,000 matches two different routes (E103 x2)
    overlaps = by_code["ST005"]
    assert len(overlaps) == 2
    assert all("overlap" in d.message for d in overlaps)
    # the Finance Head cannot approve their own claim (E104)
    assert any(
        d.evidence["counterexample"].get("requester_role") == "finance_head" for d in by_code["RS004"]
    )
    assert {d.step_id for d in by_code["RS004"]} <= {"s4.2", "s4.4"}
    # nothing leads to the Internal Audit re-review (E101)
    assert [d.step_id for d in by_code["ST001"]] == ["s6.1"]
    # 3 + 5 working days cannot meet 7 calendar days (W204)
    assert any(d.evidence["path_hours"] > d.evidence["allowed_hours"] for d in by_code["TM002"])
    # "promptly" (W201)
    assert any(d.step_id == "s7.2" for d in by_code["TM003"])


def test_no_spurious_flow_errors(expense_ir):
    diags = _diagnostics(expense_ir)
    codes = {d.code for d in diags}
    assert "ST003" not in codes  # the receipts rework loop terminates
    st002 = [d.step_id for d in diags if d.code == "ST002"]
    assert st002 in ([], ["s6.1"])  # only the unreachable audit step may dead-end
    assert not any(d.code in {"ST004", "ST005"} and d.decision_id == "d3.1" for d in diags)


def test_runtime_tests_prove_the_gaps(expense_ir):
    suite = TestGenService(None).generate(expense_ir, "run_x")
    report = run_test_suite(expense_ir, suite)
    assert report.passed > 0, "valid scenarios must be able to complete"
    outcomes = {r.trace.outcome.value for r in report.results if r.trace}
    assert {"undetermined", "conflict", "completed"} <= outcomes
    happy = next(r for r in report.results if r.test_id.startswith("sc_path_"))
    assert happy.verdict.value == "pass"
    assert report.coverage.step_coverage_pct > 60


def test_findings_merge_proof_and_fingerprint(expense_ir):
    suite = TestGenService(None).generate(expense_ir, "run_x")
    report = run_test_suite(expense_ir, suite)
    diag_report = DiagnosticsReport(run_id="run_x", diagnostics=_diagnostics(expense_ir)).with_stats()
    findings = enrich(aggregate("run_x", diag_report, report, None), expense_ir)

    codes = [f.code for f in findings.findings]
    assert "ST004" in codes and "RS004" in codes
    # runtime proofs are folded into the static finding, not listed twice
    assert "EX002" not in codes
    assert "RS006" not in codes  # the self-approval runtime proof merges into RS004 on the same step
    gap = next(f for f in findings.findings if f.code == "ST004" and "10,000" in f.message)
    assert gap.reproduced_by_tests >= 1
    assert gap.suggested_fix and gap.clause_quote
    assert gap.witness["facts"]["amount"] == 10000
    fingerprints = [f.fingerprint for f in findings.findings]
    assert len(fingerprints) == len(set(fingerprints)), "fingerprints must be unique per finding"
