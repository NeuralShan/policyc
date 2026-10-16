"""Layer 9 aggregator: cluster diagnostics + test failures + RL findings into AggregatedFindings.

Clustering key: (code, step_id, decision_id) — same gap code at the same IR element = same finding.
Evidence from all three layers is merged into a single finding with a combined risk score.
"""

from __future__ import annotations

import uuid

from app.schemas.finding import DiagnosticsReport
from app.schemas.findings import (
    AggregatedFinding,
    ConfidenceTier,
    EvidenceItem,
    FindingsReport,
    FindingTriage,
    RiskScore,
)
from app.schemas.reality import RealityReport
from app.schemas.testrun import FailReason, TestRunReport

# Map FailReason → gap code
_FAIL_REASON_CODE: dict[FailReason, str] = {
    FailReason.STRUCTURAL_GAP: "EX001",
    FailReason.SLA_BREACH: "EX003",
    FailReason.ACTOR_UNAVAILABLE: "RS006",
    FailReason.EXPECTED_OUTCOME_MISMATCH: "EX001",
}

_FAIL_REASON_TITLE: dict[FailReason, str] = {
    FailReason.STRUCTURAL_GAP: "Undetermined or conflicting execution outcome",
    FailReason.SLA_BREACH: "SLA breach in execution",
    FailReason.ACTOR_UNAVAILABLE: "No backup when actor is unavailable",
    FailReason.EXPECTED_OUTCOME_MISMATCH: "Process outcome differs from expectation",
}

_SEVERITY_IMPACT: dict[str, float] = {
    "error": 4.0,
    "warning": 2.0,
    "info": 1.0,
}

_RL_IMPACT: dict[str, float] = {
    "RL001": 3.0,   # step routinely skipped
    "RL002": 2.5,   # undocumented step routinely performed
    "RL003": 3.5,   # SLA routinely breached in real data
    "RL004": 4.0,   # real cases with no documented path
    "RL005": 4.5,   # complaint traced to clause (highest impact)
}

_CODE_TITLE: dict[str, str] = {
    "EX001": "Undetermined execution outcome",
    "EX002": "Conflicting execution outcome",
    "EX003": "SLA breach under perturbation",
    "RS006": "No backup when actor is unavailable",
    "RL001": "Step routinely skipped in practice",
    "RL002": "Undocumented step routinely performed",
    "RL003": "Documented SLA routinely breached",
    "RL004": "Real cases outside any documented path",
    "RL005": "Complaint or audit finding traceable to a clause",
}


type _ClusterKey = tuple[str, str | None, str | None]


def _new_finding(
    code: str,
    severity: str,
    confidence_tier: ConfidenceTier,
    step_id: str | None,
    decision_id: str | None,
    process_id: str | None,
    likelihood: float,
    impact: float,
) -> AggregatedFinding:
    title = _CODE_TITLE.get(code, code)
    return AggregatedFinding(
        id=f"fnd_{uuid.uuid4().hex[:12]}",
        code=code,
        title=title,
        severity=severity,
        confidence_tier=confidence_tier,
        triage=FindingTriage.OPEN,
        process_id=process_id,
        step_id=step_id,
        decision_id=decision_id,
        risk=RiskScore.compute(
            likelihood=likelihood,
            impact=impact,
            confidence=1.0 if confidence_tier == ConfidenceTier.DETERMINISTIC else 0.8,
        ),
    )


def aggregate(
    run_id: str,
    diagnostics: DiagnosticsReport | None,
    test_run: TestRunReport | None,
    reality: RealityReport | None,
) -> FindingsReport:
    """Cluster all gap signals into a ranked, deduplicated findings report."""
    cluster: dict[_ClusterKey, AggregatedFinding] = {}

    # ── Layer 4 diagnostics ─────────────────────────────────────────────────
    if diagnostics:
        for diag in diagnostics.diagnostics:
            key: _ClusterKey = (diag.code, diag.step_id, diag.decision_id)
            ev = EvidenceItem(
                kind="diagnostic",
                code=diag.code,
                message=diag.message,
                process_id=diag.process_id,
                step_id=diag.step_id,
                decision_id=diag.decision_id,
            )
            if key not in cluster:
                impact = _SEVERITY_IMPACT.get(diag.severity.value, 2.0)
                cluster[key] = _new_finding(
                    code=diag.code,
                    severity=diag.severity.value,
                    confidence_tier=ConfidenceTier.DETERMINISTIC,
                    step_id=diag.step_id,
                    decision_id=diag.decision_id,
                    process_id=diag.process_id,
                    likelihood=0.5,
                    impact=impact,
                )
            cluster[key].evidence.append(ev)

    # ── Layer 7 test failures ────────────────────────────────────────────────
    if test_run:
        for result in test_run.results:
            if not result.fail_reasons:
                continue
            trace = result.trace
            trace_step_id = (
                trace.steps[-1].node_id if trace and trace.steps else None
            )
            for reason in result.fail_reasons:
                code = _FAIL_REASON_CODE.get(reason, "EX001")
                key = (code, trace_step_id, None)
                ev = EvidenceItem(
                    kind="test_failure",
                    code=code,
                    message=f"Test {result.test_id} failed: {reason}",
                    step_id=trace_step_id,
                    test_id=result.test_id,
                    fail_reason=reason,
                )
                if key not in cluster:
                    severity = "error" if reason == FailReason.STRUCTURAL_GAP else "warning"
                    impact = _SEVERITY_IMPACT.get(severity, 2.0)
                    cluster[key] = _new_finding(
                        code=code,
                        severity=severity,
                        confidence_tier=ConfidenceTier.DETERMINISTIC,
                        step_id=trace_step_id,
                        decision_id=None,
                        process_id=trace.process_id if trace else None,
                        likelihood=1.0,
                        impact=impact,
                    )
                else:
                    # Boost likelihood to 1.0 since a test reproduces it
                    existing = cluster[key]
                    if existing.risk.likelihood < 1.0:
                        existing.risk = RiskScore.compute(
                            likelihood=1.0,
                            impact=existing.risk.impact,
                            confidence=existing.risk.confidence_weight,
                        )
                cluster[key].evidence.append(ev)

    # ── Layer 8 RL findings ──────────────────────────────────────────────────
    if reality:
        for rl in reality.rl_findings:
            key = (rl.code, rl.step_id, None)
            ev = EvidenceItem(
                kind="rl_finding",
                code=rl.code,
                message=rl.message,
                step_id=rl.step_id,
                case_count=rl.case_count,
                rate=rl.rate,
            )
            if key not in cluster:
                impact = _RL_IMPACT.get(rl.code, 3.0)
                severity = "error" if rl.code in ("RL004", "RL005") else "warning"
                cluster[key] = _new_finding(
                    code=rl.code,
                    severity=severity,
                    confidence_tier=ConfidenceTier.HISTORICAL,
                    step_id=rl.step_id,
                    decision_id=None,
                    process_id=None,
                    likelihood=min(rl.rate * 2, 1.0),   # amplify rate → likelihood
                    impact=impact,
                )
            else:
                # Existing finding now has historical backing — update likelihood
                existing = cluster[key]
                historical_likelihood = min(rl.rate * 2, 1.0)
                if historical_likelihood > existing.risk.likelihood:
                    existing.risk = RiskScore.compute(
                        likelihood=historical_likelihood,
                        impact=existing.risk.impact,
                        confidence=existing.risk.confidence_weight,
                    )
            cluster[key].evidence.append(ev)

    # ── Rank by risk score and assign evidence counts ────────────────────────
    findings = sorted(cluster.values(), key=lambda f: -f.risk.total)
    for rank, finding in enumerate(findings, start=1):
        finding.rank = rank

    return FindingsReport(run_id=run_id, findings=findings).with_stats()
