"""Layer 7 test-run schema: oracle verdicts and coverage report."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.trace import ExecutionTrace

TESTRUN_VERSION = 1


class TestVerdict(StrEnum):
    PASS = "pass"    # no intrinsic gap detected
    FAIL = "fail"    # intrinsic gap found
    SKIP = "skip"    # could not run (missing IR, etc.)


class FailReason(StrEnum):
    EXPECTED_OUTCOME_MISMATCH = "expected_outcome_mismatch"
    STRUCTURAL_GAP = "structural_gap"    # undetermined / conflict / ambiguous / dead_end / loop
    SLA_BREACH = "sla_breach"
    ACTOR_UNAVAILABLE = "actor_unavailable"   # only for non-fault tests
    ORDER_VIOLATION = "order_violation"   # a mandatory step was skipped on this path


class TestResult(BaseModel):
    test_id: str
    verdict: TestVerdict
    fail_reasons: list[FailReason] = Field(default_factory=list)
    trace: ExecutionTrace | None = None
    skip_reason: str | None = None


class CoverageReport(BaseModel):
    steps_total: int = 0
    steps_covered: int = 0
    step_coverage_pct: float = 0.0
    decisions_total: int = 0
    decisions_covered: int = 0
    decision_coverage_pct: float = 0.0
    branches_total: int = 0
    branches_covered: int = 0
    branch_coverage_pct: float = 0.0
    uncovered_step_ids: list[str] = Field(default_factory=list)
    uncovered_branch_keys: list[str] = Field(default_factory=list)  # "dec_id:label"


class TestRunReport(BaseModel):
    version: int = TESTRUN_VERSION
    run_id: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[TestResult] = Field(default_factory=list)
    coverage: CoverageReport = Field(default_factory=CoverageReport)
    stats: dict[str, Any] = Field(default_factory=dict)

    def with_stats(self) -> TestRunReport:
        self.total = len(self.results)
        self.passed = sum(1 for r in self.results if r.verdict == TestVerdict.PASS)
        self.failed = sum(1 for r in self.results if r.verdict == TestVerdict.FAIL)
        self.skipped = sum(1 for r in self.results if r.verdict == TestVerdict.SKIP)
        fail_reason_counts: dict[str, int] = {}
        for r in self.results:
            for reason in r.fail_reasons:
                fail_reason_counts[reason] = fail_reason_counts.get(reason, 0) + 1
        self.stats = {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "pass_rate_pct": round(100 * self.passed / self.total, 1) if self.total else 0.0,
            **fail_reason_counts,
        }
        return self
