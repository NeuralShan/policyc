"""Unit tests for Layer 7: oracle, coverage, and runner (no LLM, no DB)."""

from __future__ import annotations

from app.run.coverage import compute_coverage
from app.run.oracle import apply_oracle
from app.run.runner import run_test_suite
from app.schemas.ir_sop import (
    AlwaysCondition,
    ArtifactRef,
    Decision,
    DecisionBranch,
    ModalVerb,
    Process,
    ReviewStatus,
    RoleRef,
    SopIR,
    Step,
    StepKind,
    SymbolTable,
    SystemRef,
    Transition,
)
from app.schemas.testcase import TestOrigin, TestSuite
from app.schemas.testrun import FailReason, TestVerdict
from app.schemas.trace import (
    ExecutionTrace,
    Scenario,
    TraceOutcome,
    TraceStep,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_ir(*, with_decision: bool = False) -> SopIR:
    steps = [
        Step(id="s01", action="start", modal=ModalVerb.SHALL, actor_role_id="agent"),
        Step(id="s02", action="done", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    transitions = [Transition(from_id="s01", to_id="s02")]
    decisions = []
    if with_decision:
        decisions = [
            Decision(
                id="d01",
                question="Always?",
                preceding_step_id="s01",
                branches=[
                    DecisionBranch(label="yes", condition=AlwaysCondition(), next_step_id="s02"),
                ],
            )
        ]
        transitions = []

    proc = Process(
        id="p01",
        name="Simple",
        document_id="doc1",
        steps=steps,
        transitions=transitions,
        decisions=decisions,
    )
    return SopIR(
        run_id="r1",
        document_ids=["doc1"],
        symbols=SymbolTable(
            roles=[RoleRef(id="agent", name="Agent")],
            systems=[SystemRef(id="sys", name="Sys")],
            artifacts=[ArtifactRef(id="form", name="Form")],
        ),
        processes=[proc],
        review_status=ReviewStatus.APPROVED,
    )


def _scenario(sc_id: str = "sc1") -> Scenario:
    return Scenario(id=sc_id, description="test scenario", process_id="p01")


def _completed_trace(run_id: str = "r1", sla_breaches: int = 0) -> ExecutionTrace:
    return ExecutionTrace(
        run_id=run_id,
        process_id="p01",
        scenario_id="sc1",
        scenario=_scenario(),
        steps=[
            TraceStep(seq=0, node_id="s01", node_kind="step", process_id="p01", action="start"),
            TraceStep(seq=1, node_id="s02", node_kind="terminal", process_id="p01", action="done"),
        ],
        outcome=TraceOutcome.COMPLETED,
        sla_breaches=sla_breaches,
    )


def _undetermined_trace() -> ExecutionTrace:
    return ExecutionTrace(
        run_id="r1",
        process_id="p01",
        scenario_id="sc1",
        scenario=_scenario(),
        steps=[
            TraceStep(seq=0, node_id="s01", node_kind="step", process_id="p01", action="start"),
        ],
        outcome=TraceOutcome.UNDETERMINED,
    )


def _test_case(
    tc_id: str = "tc1",
    origin: TestOrigin = TestOrigin.PATH,
    expected_outcome: TraceOutcome | None = None,
):
    from app.schemas.testcase import TestCase

    return TestCase(
        id=tc_id,
        description="a test",
        origin=origin,
        process_id="p01",
        scenario=_scenario(tc_id),
        expected_outcome=expected_outcome,
    )


# ---------------------------------------------------------------------------
# Oracle tests
# ---------------------------------------------------------------------------


def test_oracle_pass_on_completed():
    tc = _test_case()
    trace = _completed_trace()
    verdict, reasons = apply_oracle(tc, trace)
    assert verdict == TestVerdict.PASS
    assert reasons == []


def test_oracle_structural_gap_flags_fail():
    tc = _test_case()
    trace = _undetermined_trace()
    verdict, reasons = apply_oracle(tc, trace)
    assert verdict == TestVerdict.FAIL
    assert FailReason.STRUCTURAL_GAP in reasons


def test_oracle_sla_breach_always_fails():
    tc = _test_case(origin=TestOrigin.FAULT)
    trace = _completed_trace(sla_breaches=1)
    verdict, reasons = apply_oracle(tc, trace)
    assert verdict == TestVerdict.FAIL
    assert FailReason.SLA_BREACH in reasons


def test_oracle_actor_unavailable_skipped_for_fault_test():
    from app.schemas.testcase import TestCase

    tc = TestCase(
        id="tc_fault",
        description="fault test",
        origin=TestOrigin.FAULT,
        process_id="p01",
        scenario=_scenario("sc_fault"),
    )
    trace = ExecutionTrace(
        run_id="r1",
        process_id="p01",
        scenario_id="sc_fault",
        scenario=_scenario("sc_fault"),
        steps=[],
        outcome=TraceOutcome.COMPLETED,
        actor_unavailable_count=1,
    )
    verdict, reasons = apply_oracle(tc, trace)
    assert verdict == TestVerdict.PASS
    assert FailReason.ACTOR_UNAVAILABLE not in reasons


def test_oracle_actor_unavailable_fails_non_fault():
    trace = ExecutionTrace(
        run_id="r1",
        process_id="p01",
        scenario_id="sc1",
        scenario=_scenario(),
        steps=[],
        outcome=TraceOutcome.COMPLETED,
        actor_unavailable_count=1,
    )
    tc = _test_case(origin=TestOrigin.PATH)
    verdict, reasons = apply_oracle(tc, trace)
    assert verdict == TestVerdict.FAIL
    assert FailReason.ACTOR_UNAVAILABLE in reasons


def test_oracle_expected_outcome_mismatch():
    tc = _test_case(expected_outcome=TraceOutcome.COMPLETED)
    trace = _undetermined_trace()
    verdict, reasons = apply_oracle(tc, trace)
    assert FailReason.EXPECTED_OUTCOME_MISMATCH in reasons


def test_oracle_no_mismatch_when_expected_matches():
    tc = _test_case(expected_outcome=TraceOutcome.COMPLETED)
    trace = _completed_trace()
    verdict, reasons = apply_oracle(tc, trace)
    assert FailReason.EXPECTED_OUTCOME_MISMATCH not in reasons
    assert verdict == TestVerdict.PASS


# ---------------------------------------------------------------------------
# Coverage tests
# ---------------------------------------------------------------------------


def test_coverage_100_when_all_steps_covered():
    ir = _simple_ir()
    traces = [_completed_trace()]
    cov = compute_coverage(ir, traces)
    assert cov.steps_total == 2
    assert cov.steps_covered == 2
    assert cov.step_coverage_pct == 100.0
    assert cov.uncovered_step_ids == []


def test_coverage_partial_when_step_missed():
    ir = _simple_ir()
    # Trace only visits s01
    trace = ExecutionTrace(
        run_id="r1",
        process_id="p01",
        scenario_id="sc1",
        scenario=_scenario(),
        steps=[TraceStep(seq=0, node_id="s01", node_kind="step", process_id="p01")],
        outcome=TraceOutcome.DEAD_END,
    )
    cov = compute_coverage(ir, [trace])
    assert cov.steps_covered == 1
    assert "s02" in cov.uncovered_step_ids


def test_coverage_branches_tracked():
    ir = _simple_ir(with_decision=True)
    # A trace that takes the "yes" branch
    trace = ExecutionTrace(
        run_id="r1",
        process_id="p01",
        scenario_id="sc1",
        scenario=_scenario(),
        steps=[
            TraceStep(seq=0, node_id="s01", node_kind="step", process_id="p01"),
            TraceStep(
                seq=1,
                node_id="d01",
                node_kind="decision",
                process_id="p01",
                branch_taken="yes",
            ),
            TraceStep(seq=2, node_id="s02", node_kind="terminal", process_id="p01"),
        ],
        outcome=TraceOutcome.COMPLETED,
    )
    cov = compute_coverage(ir, [trace])
    assert cov.branches_total == 1
    assert cov.branches_covered == 1
    assert cov.branch_coverage_pct == 100.0
    assert cov.uncovered_branch_keys == []


def test_coverage_empty_traces_gives_zero():
    ir = _simple_ir()
    cov = compute_coverage(ir, [])
    assert cov.steps_covered == 0
    assert cov.step_coverage_pct == 0.0
    assert "s01" in cov.uncovered_step_ids
    assert "s02" in cov.uncovered_step_ids


# ---------------------------------------------------------------------------
# Runner integration
# ---------------------------------------------------------------------------


def test_runner_all_pass_on_happy_path():
    from app.schemas.testcase import TestCase

    ir = _simple_ir()
    tc = TestCase(
        id="tc_path",
        description="path test",
        origin=TestOrigin.PATH,
        process_id="p01",
        scenario=Scenario(
            id="sc_path",
            description="happy path",
            process_id="p01",
        ),
        expected_outcome=TraceOutcome.COMPLETED,
    )
    suite = TestSuite(run_id="r1", test_cases=[tc]).with_stats()
    report = run_test_suite(ir, suite)

    assert report.total == 1
    assert report.passed == 1
    assert report.failed == 0
    assert report.coverage.step_coverage_pct == 100.0


def test_runner_with_stats():
    from app.schemas.testcase import TestCase

    ir = _simple_ir()
    suite = TestSuite(
        run_id="r1",
        test_cases=[
            TestCase(
                id=f"tc{i}",
                description=f"test {i}",
                origin=TestOrigin.PATH,
                process_id="p01",
                scenario=Scenario(id=f"sc{i}", description="s", process_id="p01"),
            )
            for i in range(3)
        ],
    ).with_stats()
    report = run_test_suite(ir, suite)
    assert report.total == 3
    assert report.stats["total"] == 3
    assert "pass_rate_pct" in report.stats
