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
from app.schemas.taxonomy import TAXONOMY
from app.schemas.testrun import FailReason, TestRunReport

# Map FailReason → gap code
_FAIL_REASON_CODE: dict[FailReason, str] = {
    FailReason.STRUCTURAL_GAP: "EX001",
    FailReason.SLA_BREACH: "EX003",
    FailReason.ACTOR_UNAVAILABLE: "RS006",
    FailReason.EXPECTED_OUTCOME_MISMATCH: "EX001",
    FailReason.ORDER_VIOLATION: "ST008",
}

_FAIL_REASON_TITLE: dict[FailReason, str] = {
    FailReason.STRUCTURAL_GAP: "Undetermined or conflicting execution outcome",
    FailReason.SLA_BREACH: "SLA breach in execution",
    FailReason.ACTOR_UNAVAILABLE: "No backup when actor is unavailable",
    FailReason.EXPECTED_OUTCOME_MISMATCH: "Process outcome differs from expectation",
    FailReason.ORDER_VIOLATION: "Mandatory step skipped",
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

def _decision_key(diag) -> str | None:
    """Overlapping rule pairs in one decision are separate findings (one per pair)."""
    if diag.code == "ST005" and diag.decision_id:
        pair = diag.evidence.get("branches")
        if isinstance(pair, list) and pair:
            return f"{diag.decision_id}::{'|'.join(map(str, pair))}"
    return diag.decision_id


def _facts_text(facts: dict) -> str:
    return ", ".join(f"{k} = {v}" for k, v in sorted(facts.items()))


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
    title = _CODE_TITLE.get(code) or (TAXONOMY[code].title if code in TAXONOMY else code)
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
            key: _ClusterKey = (diag.code, diag.step_id, _decision_key(diag))
            span = diag.source_spans[0] if diag.source_spans else None
            ev = EvidenceItem(
                kind="diagnostic",
                code=diag.code,
                message=diag.message,
                process_id=diag.process_id,
                step_id=diag.step_id,
                decision_id=diag.decision_id,
                data=dict(diag.evidence),
                source_quote=span.quote if span else None,
                document_id=span.document_id if span else None,
                char_start=span.char_start if span else None,
                char_end=span.char_end if span else None,
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
            last_node = trace.steps[-1].node_id if trace and trace.steps else None
            is_decision = bool(
                last_node and trace and trace.steps and trace.steps[-1].node_kind == "decision"
            )
            trace_step_id = None if is_decision else last_node
            trace_decision_id = last_node if is_decision else None
            for reason in result.fail_reasons:
                code = _FAIL_REASON_CODE.get(reason, "EX001")
                if reason == FailReason.STRUCTURAL_GAP and trace and trace.outcome.value == "conflict":
                    code = "EX002"
                step_for_key, decision_for_key = trace_step_id, trace_decision_id
                if reason == FailReason.ORDER_VIOLATION and trace and trace.violations:
                    step_for_key, decision_for_key = trace.violations[0].split()[0], None
                elif reason in (FailReason.ACTOR_UNAVAILABLE, FailReason.SLA_BREACH) and trace:
                    # anchor to the step that actually blocked / breached, not the last node reached
                    wanted = "actor_unavailable" if reason == FailReason.ACTOR_UNAVAILABLE else "sla_breached"
                    culprit = next((t for t in trace.steps if t.step_status is not None and t.step_status.value == wanted), None)
                    if culprit is not None:
                        step_for_key, decision_for_key = culprit.node_id, None
                key = (code, step_for_key, decision_for_key)
                facts = dict(trace.scenario.facts) if trace else {}
                ev = EvidenceItem(
                    kind="test_failure",
                    code=code,
                    message=(
                        f"Scenario {_facts_text(facts) or result.test_id} → "
                        f"{trace.outcome.value if trace else reason}"
                    ),
                    step_id=step_for_key,
                    decision_id=decision_for_key,
                    test_id=result.test_id,
                    fail_reason=reason,
                    data={
                        "facts": facts,
                        "outcome": trace.outcome.value if trace else None,
                        "trace_nodes": [t.node_id for t in trace.steps] if trace else [],
                    },
                )
                if key not in cluster:
                    severity = "error" if reason == FailReason.STRUCTURAL_GAP else "warning"
                    if trace is not None and trace.outcome.value == "ambiguous":
                        severity = "warning"  # hinges on a vague condition: a wording issue, not a proven gap
                    impact = _SEVERITY_IMPACT.get(severity, 2.0)
                    cluster[key] = _new_finding(
                        code=code,
                        severity=severity,
                        confidence_tier=ConfidenceTier.DETERMINISTIC,
                        step_id=step_for_key,
                        decision_id=decision_for_key,
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
