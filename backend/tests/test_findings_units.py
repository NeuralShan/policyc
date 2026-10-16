"""Unit tests for Layer 9: aggregator, risk scoring, triage (no LLM, no DB)."""

from __future__ import annotations

from app.findings.aggregator import aggregate
from app.schemas.finding import CheckTier, Diagnostic, DiagnosticsReport, Severity
from app.schemas.findings import (
    ConfidenceTier,
    FindingTriage,
)
from app.schemas.reality import RealityReport, RlFinding
from app.schemas.testrun import FailReason, TestResult, TestRunReport, TestVerdict
from app.schemas.trace import ExecutionTrace, Scenario, TraceOutcome, TraceStep

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _diag(
    code: str,
    sev: Severity = Severity.WARNING,
    step_id: str | None = "s01",
) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=sev,
        message=f"Fixture diagnostic {code}",
        step_id=step_id,
        check_tier=CheckTier.DETERMINISTIC,
    )


def _diag_report(*diags: Diagnostic) -> DiagnosticsReport:
    return DiagnosticsReport(run_id="r1", diagnostics=list(diags)).with_stats()


def _trace(outcome: TraceOutcome = TraceOutcome.UNDETERMINED) -> ExecutionTrace:
    return ExecutionTrace(
        run_id="r1",
        process_id="p01",
        scenario_id="sc1",
        scenario=Scenario(id="sc1", description="t"),
        steps=[TraceStep(seq=0, node_id="s01", node_kind="step", process_id="p01")],
        outcome=outcome,
    )


def _fail_result(test_id: str, reason: FailReason) -> TestResult:
    return TestResult(
        test_id=test_id,
        verdict=TestVerdict.FAIL,
        fail_reasons=[reason],
        trace=_trace(),
    )


def _pass_result(test_id: str) -> TestResult:
    return TestResult(test_id=test_id, verdict=TestVerdict.PASS)


def _testrun(*results: TestResult) -> TestRunReport:
    return TestRunReport(run_id="r1", results=list(results)).with_stats()


def _rl_report(*findings: RlFinding) -> RealityReport:
    return RealityReport(
        run_id="r1",
        source_filename="cases.csv",
        rl_findings=list(findings),
    ).with_stats()


def _rl(code: str, step_id: str | None = "s01", rate: float = 0.5) -> RlFinding:
    return RlFinding(
        code=code,
        message=f"RL finding {code}",
        step_id=step_id,
        case_count=5,
        rate=rate,
    )


# ---------------------------------------------------------------------------
# Aggregator: from diagnostics only
# ---------------------------------------------------------------------------


def test_aggregate_empty_inputs():
    report = aggregate("r1", None, None, None)
    assert report.findings == []
    assert report.stats["total"] == 0


def test_aggregate_single_diagnostic():
    diags = _diag_report(_diag("ST001", Severity.ERROR))
    report = aggregate("r1", diags, None, None)
    assert len(report.findings) == 1
    f = report.findings[0]
    assert f.code == "ST001"
    assert f.severity == "error"
    assert f.confidence_tier == ConfidenceTier.DETERMINISTIC
    assert len(f.evidence) == 1
    assert f.evidence[0].kind == "diagnostic"


def test_aggregate_deduplicates_same_code_at_same_step():
    # Two diagnostics with same code at same step → one finding, two evidence items
    diags = _diag_report(_diag("ST004", step_id="d01"), _diag("ST004", step_id="d01"))
    report = aggregate("r1", diags, None, None)
    assert len(report.findings) == 1
    assert len(report.findings[0].evidence) == 2


def test_aggregate_different_steps_produce_separate_findings():
    diags = _diag_report(_diag("ST001", step_id="s01"), _diag("ST001", step_id="s02"))
    report = aggregate("r1", diags, None, None)
    assert len(report.findings) == 2


def test_aggregate_different_codes_produce_separate_findings():
    diags = _diag_report(_diag("ST001"), _diag("RS001"))
    report = aggregate("r1", diags, None, None)
    assert len(report.findings) == 2


# ---------------------------------------------------------------------------
# Aggregator: from test failures
# ---------------------------------------------------------------------------


def test_aggregate_test_failure_creates_finding():
    run = _testrun(_fail_result("tc1", FailReason.STRUCTURAL_GAP))
    report = aggregate("r1", None, run, None)
    codes = {f.code for f in report.findings}
    assert "EX001" in codes


def test_aggregate_test_failure_likelihood_is_1():
    run = _testrun(_fail_result("tc1", FailReason.STRUCTURAL_GAP))
    report = aggregate("r1", None, run, None)
    f = next(f for f in report.findings if f.code == "EX001")
    assert f.risk.likelihood == 1.0


def test_aggregate_sla_breach_maps_to_ex003():
    run = _testrun(_fail_result("tc1", FailReason.SLA_BREACH))
    report = aggregate("r1", None, run, None)
    codes = {f.code for f in report.findings}
    assert "EX003" in codes


def test_aggregate_actor_unavailable_maps_to_rs006():
    run = _testrun(_fail_result("tc1", FailReason.ACTOR_UNAVAILABLE))
    report = aggregate("r1", None, run, None)
    codes = {f.code for f in report.findings}
    assert "RS006" in codes


def test_aggregate_passes_produce_no_findings():
    run = _testrun(_pass_result("tc1"), _pass_result("tc2"))
    report = aggregate("r1", None, run, None)
    assert report.findings == []


# ---------------------------------------------------------------------------
# Aggregator: from RL findings
# ---------------------------------------------------------------------------


def test_aggregate_rl_finding_creates_historical_finding():
    reality = _rl_report(_rl("RL001"))
    report = aggregate("r1", None, None, reality)
    assert len(report.findings) == 1
    f = report.findings[0]
    assert f.code == "RL001"
    assert f.confidence_tier == ConfidenceTier.HISTORICAL
    assert len(f.evidence) == 1
    assert f.evidence[0].kind == "rl_finding"


def test_aggregate_rl004_has_error_severity():
    reality = _rl_report(_rl("RL004"))
    report = aggregate("r1", None, None, reality)
    f = report.findings[0]
    assert f.severity == "error"


def test_aggregate_rl_likelihood_scales_with_rate():
    low = _rl_report(_rl("RL001", rate=0.1))
    high = _rl_report(_rl("RL001", rate=0.9))
    low_report = aggregate("r1", None, None, low)
    high_report = aggregate("r1", None, None, high)
    assert low_report.findings[0].risk.likelihood < high_report.findings[0].risk.likelihood


# ---------------------------------------------------------------------------
# Aggregator: multi-source combination
# ---------------------------------------------------------------------------


def test_aggregate_diagnostic_plus_rl_at_same_step_merges():
    # A diagnostic AND an RL finding at the same step → one finding with 2 evidence items
    diags = _diag_report(_diag("RL001", step_id="s01"))
    reality = _rl_report(_rl("RL001", step_id="s01", rate=0.5))
    report = aggregate("r1", diags, None, reality)
    f = next(f for f in report.findings if f.code == "RL001")
    assert len(f.evidence) == 2


def test_aggregate_test_failure_boosts_existing_diagnostic_likelihood():
    # Diagnostic has likelihood=0.5, test failure should boost to 1.0
    diags = _diag_report(_diag("EX001", step_id="s01"))
    run = _testrun(_fail_result("tc1", FailReason.STRUCTURAL_GAP))
    report = aggregate("r1", diags, run, None)
    f = next(f for f in report.findings if f.code == "EX001")
    assert f.risk.likelihood == 1.0


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------


def test_risk_higher_for_error_than_warning():
    error_diags = _diag_report(_diag("ST001", Severity.ERROR, step_id="s01"))
    warn_diags = _diag_report(_diag("ST001", Severity.WARNING, step_id="s01"))
    error_report = aggregate("r1", error_diags, None, None)
    warn_report = aggregate("r1", warn_diags, None, None)
    assert error_report.findings[0].risk.total > warn_report.findings[0].risk.total


def test_risk_score_total_is_product():
    from app.schemas.findings import RiskScore

    rs = RiskScore.compute(likelihood=0.8, impact=3.0, confidence=1.0)
    assert abs(rs.total - 2.4) < 0.001


def test_findings_sorted_by_risk_descending():
    diags = _diag_report(
        _diag("ST001", Severity.INFO, step_id="s01"),
        _diag("RS001", Severity.ERROR, step_id="s02"),
        _diag("TM001", Severity.WARNING, step_id="s03"),
    )
    report = aggregate("r1", diags, None, None)
    scores = [f.risk.total for f in report.findings]
    assert scores == sorted(scores, reverse=True)


def test_rank_assigned():
    diags = _diag_report(_diag("ST001"), _diag("RS001", step_id="s02"))
    report = aggregate("r1", diags, None, None)
    ranks = [f.rank for f in report.findings]
    assert ranks[0] == 1
    assert ranks[1] == 2


# ---------------------------------------------------------------------------
# FindingsReport.with_stats
# ---------------------------------------------------------------------------


def test_findings_report_stats():
    diags = _diag_report(
        _diag("ST001", Severity.ERROR),
        _diag("RS001", Severity.WARNING),
    )
    report = aggregate("r1", diags, None, None)
    assert report.stats["total"] == 2
    assert report.stats["open"] == 2
    assert "by_severity" in report.stats


# ---------------------------------------------------------------------------
# Triage state machine
# ---------------------------------------------------------------------------


def test_triage_defaults_to_open():
    diags = _diag_report(_diag("ST001"))
    report = aggregate("r1", diags, None, None)
    assert report.findings[0].triage == FindingTriage.OPEN


def test_triage_update_changes_state():
    diags = _diag_report(_diag("ST001"))
    report = aggregate("r1", diags, None, None)
    finding_id = report.findings[0].id

    # Patch in-memory by directly calling the core logic
    for f in report.findings:
        if f.id == finding_id:
            f.triage = FindingTriage.ACCEPTED
    report = report.with_stats()

    accepted = next(f for f in report.findings if f.id == finding_id)
    assert accepted.triage == FindingTriage.ACCEPTED
    assert report.stats["open"] == 0
