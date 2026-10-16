"""Layer 8 reality schema: conformance-checking results and RL findings."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

REALITY_VERSION = 1


class CaseResult(BaseModel):
    """Conformance result for one real case."""

    case_id: str
    fitness: float                    # 0.0–1.0 (1.0 = fully conformant)
    synced: list[str] = []            # step_ids matched in both model and case
    skipped: list[str] = []           # step_ids in model but not in case (model moves)
    extra: list[str] = []             # activities in case but not in model (log moves)
    sla_breaches: list[str] = []      # step_ids where elapsed time > SLA
    has_no_path: bool = False         # fitness < 0.2 → RL004


class StepStats(BaseModel):
    step_id: str
    total_cases: int = 0
    synced_count: int = 0
    skipped_count: int = 0
    extra_count: int = 0
    sla_breach_count: int = 0

    @property
    def skip_rate(self) -> float:
        return self.skipped_count / self.total_cases if self.total_cases else 0.0

    @property
    def sla_breach_rate(self) -> float:
        return self.sla_breach_count / self.total_cases if self.total_cases else 0.0


class RlFinding(BaseModel):
    code: str          # RL001–RL004
    message: str
    step_id: str | None = None
    activity: str | None = None
    case_count: int = 0
    rate: float = 0.0


class RealityReport(BaseModel):
    version: int = REALITY_VERSION
    run_id: str
    source_filename: str
    total_cases: int = 0
    conformant_cases: int = 0           # fitness >= 0.8
    avg_fitness: float = 0.0
    case_results: list[CaseResult] = Field(default_factory=list)
    step_stats: dict[str, StepStats] = Field(default_factory=dict)
    extra_activity_counts: dict[str, int] = Field(default_factory=dict)
    rl_findings: list[RlFinding] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)

    def with_stats(self) -> RealityReport:
        self.total_cases = len(self.case_results)
        self.conformant_cases = sum(1 for r in self.case_results if r.fitness >= 0.8)
        self.avg_fitness = (
            sum(r.fitness for r in self.case_results) / self.total_cases
            if self.total_cases else 0.0
        )
        self.stats = {
            "total_cases": self.total_cases,
            "conformant_cases": self.conformant_cases,
            "avg_fitness": round(self.avg_fitness, 3),
            "conformance_rate_pct": round(
                100 * self.conformant_cases / self.total_cases, 1
            ) if self.total_cases else 0.0,
            "rl_findings": len(self.rl_findings),
        }
        return self
