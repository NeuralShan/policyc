"""Layer 6 test-case schema.

A ``TestCase`` is one scenario with optional expectations.
A ``TestSuite`` is the full generated regression suite for a run.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.trace import Scenario, TraceOutcome

TESTSUITE_VERSION = 1


class TestOrigin(StrEnum):
    BOUNDARY = "boundary"  # boundary value around a numeric threshold (6.1)
    PATH = "path"          # happy-path / full path coverage stub (6.1)
    BRANCH = "branch"      # Z3 witness for a specific decision branch (6.2)
    FAULT = "fault"        # fault injection: actor/system unavailable (6.3)


class TestCase(BaseModel):
    id: str                                      # stable slug, unique within suite
    description: str
    origin: TestOrigin
    process_id: str
    scenario: Scenario
    expected_outcome: TraceOutcome | None = None  # None = no expectation (exploratory)
    expected_branch: str | None = None           # branch label expected at decision_id
    expected_decision_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    generator_version: int = 1


class TestSuite(BaseModel):
    version: int = TESTSUITE_VERSION
    run_id: str
    test_cases: list[TestCase] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)

    def with_stats(self) -> TestSuite:
        counts: dict[str, int] = {}
        for tc in self.test_cases:
            counts[tc.origin] = counts.get(tc.origin, 0) + 1
        counts["total"] = len(self.test_cases)
        self.stats = counts
        return self
