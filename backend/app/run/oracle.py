"""Intrinsic oracle: determine test verdict from the execution trace.

Oracle hierarchy (Layer 7, tier 1 — intrinsic only):
  1. STRUCTURAL_GAP: outcome is undetermined / conflict / ambiguous / dead_end / loop_detected
  2. SLA_BREACH: sla_breaches > 0 (only flagged as failure for non-fault tests)
  3. ACTOR_UNAVAILABLE: actor_unavailable_count > 0 (only for non-fault tests)
  4. EXPECTED_OUTCOME_MISMATCH: expected_outcome set and doesn't match actual outcome
  5. Otherwise: PASS

For fault injection tests (origin == "fault"), actor and system anomalies are expected
perturbations, not failures in their own right.
"""

from __future__ import annotations

from app.schemas.testcase import TestCase, TestOrigin
from app.schemas.testrun import FailReason, TestVerdict
from app.schemas.trace import ExecutionTrace, TraceOutcome

_STRUCTURAL_OUTCOMES = frozenset(
    {
        TraceOutcome.UNDETERMINED,
        TraceOutcome.CONFLICT,
        TraceOutcome.AMBIGUOUS,
        TraceOutcome.DEAD_END,
        TraceOutcome.LOOP_DETECTED,
        TraceOutcome.MAX_STEPS,
    }
)


def apply_oracle(
    test_case: TestCase,
    trace: ExecutionTrace,
) -> tuple[TestVerdict, list[FailReason]]:
    """Return (verdict, fail_reasons) for one test case."""
    reasons: list[FailReason] = []
    is_fault = test_case.origin == TestOrigin.FAULT

    # 1. Structural gap
    if trace.outcome in _STRUCTURAL_OUTCOMES:
        reasons.append(FailReason.STRUCTURAL_GAP)

    # 2. SLA breach — always a failure (even for fault tests the SOP should handle timing)
    if trace.sla_breaches > 0:
        reasons.append(FailReason.SLA_BREACH)

    # 3. Actor unavailable — only a failure for non-fault tests
    if not is_fault and trace.actor_unavailable_count > 0:
        reasons.append(FailReason.ACTOR_UNAVAILABLE)

    # 4. Expected outcome mismatch
    if (
        test_case.expected_outcome is not None
        and trace.outcome != test_case.expected_outcome
    ):
        reasons.append(FailReason.EXPECTED_OUTCOME_MISMATCH)

    verdict = TestVerdict.FAIL if reasons else TestVerdict.PASS
    return verdict, reasons
