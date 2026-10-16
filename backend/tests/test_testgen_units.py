"""Unit tests for Layer 6 test generators (no LLM, no DB)."""

from __future__ import annotations

from app.schemas.ir_sop import (
    AlwaysCondition,
    ArtifactRef,
    CompareCondition,
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
    TypedValue,
    VagueCondition,
    ValueType,
)
from app.schemas.testcase import TestOrigin
from app.testgen.deterministic import (
    extract_thresholds,
    generate_boundary_tests,
    generate_path_tests,
)
from app.testgen.faults import generate_actor_fault_tests, generate_system_fault_tests
from app.testgen.solver import generate_branch_tests

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cmp(left: str, op: str, val: float) -> CompareCondition:
    return CompareCondition(
        left=left, op=op, right=TypedValue(value_type=ValueType.NUMBER, number=val)
    )


def _ir_with_decision(branches: list[DecisionBranch]) -> SopIR:
    steps = [
        Step(id="s01", action="assess", modal=ModalVerb.SHALL, actor_role_id="agent"),
        Step(id="s02", action="path_a", modal=ModalVerb.SHALL),
        Step(id="s03", action="path_b", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    dec = Decision(id="d01", question="Which path?", preceding_step_id="s01", branches=branches)
    transitions = [Transition(from_id="s02", to_id="s03")]
    proc = Process(
        id="p01",
        name="Test Process",
        document_id="d1",
        steps=steps,
        decisions=[dec],
        transitions=transitions,
    )
    return SopIR(
        run_id="r1",
        document_ids=["d1"],
        symbols=SymbolTable(
            roles=[RoleRef(id="agent", name="Agent")],
            artifacts=[ArtifactRef(id="form", name="Form")],
            systems=[SystemRef(id="crm", name="CRM")],
        ),
        processes=[proc],
        review_status=ReviewStatus.APPROVED,
    )


def _simple_ir(steps: list[Step], transitions: list[Transition] | None = None) -> SopIR:
    proc = Process(
        id="p01",
        name="Simple",
        document_id="d1",
        steps=steps,
        transitions=transitions or [],
    )
    return SopIR(
        run_id="r1",
        document_ids=["d1"],
        symbols=SymbolTable(
            roles=[RoleRef(id="manager", name="Manager")],
            systems=[SystemRef(id="crm", name="CRM")],
        ),
        processes=[proc],
        review_status=ReviewStatus.APPROVED,
    )


# ---------------------------------------------------------------------------
# extract_thresholds
# ---------------------------------------------------------------------------


def test_extract_thresholds_finds_all_values():
    ir = _ir_with_decision([
        DecisionBranch(label="small", condition=_cmp("amount", "lt", 500), next_step_id="s02"),
        DecisionBranch(label="large", condition=_cmp("amount", "ge", 500), next_step_id="s03"),
    ])
    thresholds = extract_thresholds(ir)
    assert "amount" in thresholds
    assert 500.0 in thresholds["amount"]


def test_extract_thresholds_empty_when_no_decisions():
    steps = [Step(id="s01", action="log", modal=ModalVerb.SHALL)]
    ir = _simple_ir(steps)
    assert extract_thresholds(ir) == {}


def test_extract_thresholds_multiple_variables():
    ir = _ir_with_decision([
        DecisionBranch(label="a", condition=_cmp("x", "lt", 100), next_step_id="s02"),
        DecisionBranch(label="b", condition=_cmp("y", "gt", 200), next_step_id="s03"),
    ])
    thresholds = extract_thresholds(ir)
    assert "x" in thresholds and "y" in thresholds


# ---------------------------------------------------------------------------
# generate_boundary_tests
# ---------------------------------------------------------------------------


def test_generate_boundary_tests_produces_three_per_threshold():
    ir = _ir_with_decision([
        DecisionBranch(label="low", condition=_cmp("amount", "lt", 100), next_step_id="s02"),
        DecisionBranch(label="high", condition=_cmp("amount", "ge", 100), next_step_id="s03"),
    ])
    tests = generate_boundary_tests(ir)
    # One threshold (100) × 3 deltas = 3 test cases
    assert len(tests) == 3
    assert all(tc.origin == TestOrigin.BOUNDARY for tc in tests)
    vals = {tc.scenario.facts["amount"] for tc in tests}
    assert vals == {99.0, 100.0, 101.0}


def test_generate_boundary_tests_empty_when_no_decisions():
    steps = [Step(id="s01", action="log", modal=ModalVerb.SHALL)]
    ir = _simple_ir(steps)
    assert generate_boundary_tests(ir) == []


# ---------------------------------------------------------------------------
# generate_path_tests
# ---------------------------------------------------------------------------


def test_generate_path_tests_one_per_process():
    steps = [
        Step(id="s01", action="first", modal=ModalVerb.SHALL),
        Step(id="s02", action="done", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    ir = _simple_ir(steps, transitions=[Transition(from_id="s01", to_id="s02")])
    tests = generate_path_tests(ir)
    assert len(tests) == 1
    assert tests[0].origin == TestOrigin.PATH


# ---------------------------------------------------------------------------
# generate_branch_tests (Z3)
# ---------------------------------------------------------------------------


def test_generate_branch_tests_numeric():
    ir = _ir_with_decision([
        DecisionBranch(label="small", condition=_cmp("amount", "lt", 100), next_step_id="s02"),
        DecisionBranch(label="large", condition=_cmp("amount", "ge", 100), next_step_id="s03"),
    ])
    tests = generate_branch_tests(ir)
    assert len(tests) == 2
    assert all(tc.origin == TestOrigin.BRANCH for tc in tests)
    # Each test should have an "amount" fact
    for tc in tests:
        assert "amount" in tc.scenario.facts


def test_generate_branch_tests_always_condition():
    ir = _ir_with_decision([
        DecisionBranch(label="default", condition=AlwaysCondition(), next_step_id="s02"),
    ])
    tests = generate_branch_tests(ir)
    assert len(tests) == 1
    assert tests[0].scenario.facts == {}


def test_generate_branch_tests_skips_vague():
    ir = _ir_with_decision([
        DecisionBranch(label="vague", condition=VagueCondition(text="urgent"), next_step_id="s02"),
    ])
    tests = generate_branch_tests(ir)
    assert tests == []


def test_branch_witness_satisfies_condition():
    """The generated fact must actually satisfy the branch condition."""
    ir = _ir_with_decision([
        DecisionBranch(label="over1k", condition=_cmp("amount", "gt", 1000), next_step_id="s02"),
        DecisionBranch(label="under1k", condition=_cmp("amount", "le", 1000), next_step_id="s03"),
    ])
    tests = generate_branch_tests(ir)
    for tc in tests:
        amount = tc.scenario.facts.get("amount")
        if tc.expected_branch == "over1k":
            assert amount is not None and amount > 1000
        elif tc.expected_branch == "under1k":
            assert amount is not None and amount <= 1000


# ---------------------------------------------------------------------------
# generate_actor_fault_tests
# ---------------------------------------------------------------------------


def test_actor_fault_tests_one_per_role():
    steps = [
        Step(id="s01", action="log", modal=ModalVerb.SHALL, actor_role_id="manager"),
        Step(id="s02", action="approve", modal=ModalVerb.SHALL, actor_role_id="manager"),
        Step(id="s03", action="done", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    ir = _simple_ir(steps)
    tests = generate_actor_fault_tests(ir)
    # Only one unique role → one test
    assert len(tests) == 1
    assert tests[0].origin == TestOrigin.FAULT
    assert tests[0].scenario.actor_overrides == {"manager": None}


def test_actor_fault_tests_no_roles():
    steps = [Step(id="s01", action="log", modal=ModalVerb.SHALL)]
    ir = _simple_ir(steps)
    assert generate_actor_fault_tests(ir) == []


# ---------------------------------------------------------------------------
# generate_system_fault_tests
# ---------------------------------------------------------------------------


def test_system_fault_tests_one_per_system():
    steps = [
        Step(id="s01", action="log in crm", modal=ModalVerb.SHALL, systems=["crm"]),
        Step(id="s02", action="done", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    ir = _simple_ir(steps)
    tests = generate_system_fault_tests(ir)
    assert len(tests) == 1
    assert tests[0].scenario.system_overrides == {"crm": False}


def test_system_fault_tests_no_systems():
    steps = [Step(id="s01", action="log", modal=ModalVerb.SHALL)]
    ir = _simple_ir(steps)
    assert generate_system_fault_tests(ir) == []


# ---------------------------------------------------------------------------
# TestGenService (no DB)
# ---------------------------------------------------------------------------


def test_testgen_service_generate():
    from app.testgen.service import TestGenService

    svc = TestGenService.__new__(TestGenService)
    steps = [
        Step(
            id="s01", action="assess", modal=ModalVerb.SHALL,
            actor_role_id="manager", systems=["crm"],
        ),
        Step(id="s02", action="done", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    dec = Decision(
        id="d01",
        question="Small?",
        preceding_step_id="s01",
        branches=[
            DecisionBranch(label="yes", condition=_cmp("amount", "lt", 100), next_step_id="s02"),
            DecisionBranch(label="no", condition=_cmp("amount", "ge", 100), next_step_id="s02"),
        ],
    )
    proc = Process(id="p01", name="P", document_id="d1", steps=steps, decisions=[dec])
    ir = SopIR(
        run_id="r1",
        document_ids=["d1"],
        symbols=SymbolTable(
            roles=[RoleRef(id="manager", name="Manager")],
            systems=[SystemRef(id="crm", name="CRM")],
        ),
        processes=[proc],
        review_status=ReviewStatus.APPROVED,
    )
    suite = svc.generate(ir, "r1")
    assert suite.stats["total"] > 0
    origins = {tc.origin for tc in suite.test_cases}
    assert TestOrigin.BOUNDARY in origins
    assert TestOrigin.BRANCH in origins
    assert TestOrigin.FAULT in origins
    assert TestOrigin.PATH in origins


def test_testgen_deduplication():
    """No duplicate IDs in the generated suite."""
    from app.testgen.service import TestGenService

    svc = TestGenService.__new__(TestGenService)
    steps = [Step(id="s01", action="log", modal=ModalVerb.SHALL)]
    proc = Process(id="p01", name="P", document_id="d1", steps=steps)
    ir = SopIR(
        run_id="r1",
        document_ids=["d1"],
        symbols=SymbolTable(),
        processes=[proc],
        review_status=ReviewStatus.APPROVED,
    )
    suite = svc.generate(ir, "r1")
    ids = [tc.id for tc in suite.test_cases]
    assert len(ids) == len(set(ids))
