"""Layer 9 aggregated-findings schema.

Each ``AggregatedFinding`` clusters one or more pieces of evidence (Layer 4 diagnostics,
Layer 7 test failures, Layer 8 RL deviations) that share the same root element and gap code.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

FINDINGS_VERSION = 1


class ConfidenceTier(StrEnum):
    DETERMINISTIC = "deterministic"   # static analysis / test failure — fully reproducible
    HISTORICAL = "historical"         # real case data — real but potentially noisy
    JUDGMENT = "judgment"             # LLM analysis (stub — not yet implemented)


class FindingTriage(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    FALSE_POSITIVE = "false_positive"
    WONT_FIX = "wont_fix"
    FIXED = "fixed"


class EvidenceItem(BaseModel):
    kind: Literal["diagnostic", "test_failure", "rl_finding"]
    code: str
    message: str
    process_id: str | None = None
    step_id: str | None = None
    decision_id: str | None = None
    test_id: str | None = None      # for test_failure
    fail_reason: str | None = None  # for test_failure
    case_count: int | None = None   # for rl_finding
    rate: float | None = None       # for rl_finding
    data: dict[str, Any] = Field(default_factory=dict)  # counterexample / facts / path / rule
    source_quote: str | None = None
    document_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None


class RiskScore(BaseModel):
    likelihood: float          # 0.0–1.0 — how often this gap manifests
    impact: float              # 1.0–5.0 — severity of the consequence
    confidence_weight: float   # 0.0–1.0 — how certain we are (deterministic vs historical)
    total: float               # likelihood × impact × confidence_weight

    @classmethod
    def compute(cls, likelihood: float, impact: float, confidence: float) -> RiskScore:
        total = round(likelihood * impact * confidence, 3)
        return cls(
            likelihood=round(likelihood, 3),
            impact=round(impact, 2),
            confidence_weight=round(confidence, 2),
            total=total,
        )


class AggregatedFinding(BaseModel):
    id: str
    code: str
    title: str
    severity: str             # "error" | "warning" | "info"
    confidence_tier: ConfidenceTier
    triage: FindingTriage = FindingTriage.OPEN
    process_id: str | None = None
    step_id: str | None = None
    decision_id: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    risk: RiskScore
    rank: int = 0             # 1 = highest risk, assigned after sorting
    message: str = ""         # the specific, human-readable statement of the problem
    witness: dict[str, Any] = Field(default_factory=dict)  # counterexample facts / path / rule
    clause_ref: str | None = None      # clause number(s) as printed in the document
    clause_quote: str | None = None    # verbatim source text
    document_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    involved_node_ids: list[str] = Field(default_factory=list)  # steps/decisions to highlight
    suggested_fix: str | None = None
    fingerprint: str = ""     # stable identity across runs (used for the fixed/new/remaining diff)
    reproduced_by_tests: int = 0  # number of failing test scenarios that prove it


class FindingsReport(BaseModel):
    version: int = FINDINGS_VERSION
    run_id: str
    findings: list[AggregatedFinding] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)

    def with_stats(self) -> FindingsReport:
        by_severity: dict[str, int] = {}
        by_code: dict[str, int] = {}
        by_triage: dict[str, int] = {}
        for f in self.findings:
            by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
            by_code[f.code] = by_code.get(f.code, 0) + 1
            by_triage[f.triage] = by_triage.get(f.triage, 0) + 1
        self.stats = {
            "total": len(self.findings),
            "by_severity": by_severity,
            "by_triage": by_triage,
            "top_codes": sorted(by_code.items(), key=lambda x: -x[1])[:5],
            "open": by_triage.get("open", 0),
        }
        return self
