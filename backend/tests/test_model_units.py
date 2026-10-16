"""Unit tests for Layer 5 evaluator and simulator (no LLM, no DB)."""

from __future__ import annotations

from app.model.evaluator import eval_condition
from app.model.simulator import simulate
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
from app.schemas.trace import DecisionOutcome, Scenario, TraceOutcome

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cmp(left: str, op: str, val: float) -> CompareCondition:
    return CompareCondition(
        left=left, op=op, right=TypedValue(value_type=ValueType.NUMBER, number=val)
    )


def _scenario(**kwargs) -> Scenario:
    return Scenario(id="sc1", description="test", **kwargs)


def _simple_ir(
    steps: list[Step],
    decisions: list[Decision] | None = None,
    transitions: list[Transition] | None = None,
) -> SopIR:
    proc = Process(
        id="p01",
        name="P",
        document_id="d1",
        steps=steps,
        decisions=decisions or [],
        transitions=transitions or [],
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


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def test_always_condition():
    assert eval_condition(AlwaysCondition(), {}) == "true"


def test_vague_condition():
    assert eval_condition(VagueCondition(text="promptly"), {}) == "vague"


def test_compare_true():
    cond = _cmp("amount", "gt", 100.0)
    assert eval_condition(cond, {"amount": 200}) == "true"


def test_compare_false():
    cond = _cmp("amount", "gt", 100.0)
    assert eval_condition(cond, {"amount": 50}) == "false"


def test_compare_missing_fact():
    cond = _cmp("amount", "gt", 100.0)
    assert eval_condition(cond, {}) == "unknown"


def test_compare_equality_enum():
    from app.schemas.ir_sop import CompareCondition, TypedValue, ValueType

    cond = CompareCondition(
        left="status",
        op="eq",
        right=TypedValue(value_type=ValueType.ENUM, text="approved"),
    )
    assert eval_condition(cond, {"status": "approved"}) == "true"
    assert eval_condition(cond, {"status": "rejected"}) == "false"


def test_logical_and_short_circuits_on_false():
    from app.schemas.ir_sop import LogicalCondition

    cond = LogicalCondition(
        logical_op="and",
        operands=[_cmp("a", "gt", 10), _cmp("b", "gt", 10)],
    )
    assert eval_condition(cond, {"a": 5, "b": 20}) == "false"
    assert eval_condition(cond, {"a": 20, "b": 20}) == "true"


def test_logical_or():
    from app.schemas.ir_sop import LogicalCondition

    cond = LogicalCondition(
        logical_op="or",
        operands=[_cmp("a", "gt", 100), _cmp("b", "gt", 100)],
    )
    assert eval_condition(cond, {"a": 50, "b": 200}) == "true"
    assert eval_condition(cond, {"a": 50, "b": 50}) == "false"


def test_logical_not():
    from app.schemas.ir_sop import LogicalCondition

    cond = LogicalCondition(logical_op="not", operands=[_cmp("a", "gt", 100)])
    assert eval_condition(cond, {"a": 50}) == "true"
    assert eval_condition(cond, {"a": 200}) == "false"


def test_logical_and_with_vague_propagates():
    from app.schemas.ir_sop import LogicalCondition

    cond = LogicalCondition(
        logical_op="and",
        operands=[_cmp("a", "gt", 10), VagueCondition(text="promptly")],
    )
    assert eval_condition(cond, {"a": 20}) == "vague"


# ---------------------------------------------------------------------------
# Simulator — happy path
# ---------------------------------------------------------------------------


def test_simulate_linear_two_steps_completes():
    steps = [
        Step(id="s01", action="first", modal=ModalVerb.SHALL, actor_role_id="agent"),
        Step(id="s02", action="last", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    transitions = [Transition(from_id="s01", to_id="s02")]
    ir = _simple_ir(steps, transitions=transitions)
    trace = simulate(ir, _scenario())
    assert trace.outcome == TraceOutcome.COMPLETED
    assert len(trace.steps) == 2
    assert trace.steps[-1].node_kind == "terminal"


def test_simulate_dead_end():
    steps = [Step(id="s01", action="only step", modal=ModalVerb.SHALL)]
    ir = _simple_ir(steps)
    trace = simulate(ir, _scenario())
    assert trace.outcome == TraceOutcome.DEAD_END


def test_simulate_loop_detected():
    steps = [
        Step(id="s01", action="loop a", modal=ModalVerb.SHALL),
        Step(id="s02", action="loop b", modal=ModalVerb.SHALL),
    ]
    transitions = [
        Transition(from_id="s01", to_id="s02"),
        Transition(from_id="s02", to_id="s01"),
    ]
    ir = _simple_ir(steps, transitions=transitions)
    trace = simulate(ir, _scenario())
    assert trace.outcome == TraceOutcome.LOOP_DETECTED


# ---------------------------------------------------------------------------
# Simulator — decisions
# ---------------------------------------------------------------------------


def test_simulate_determined_branch():
    steps = [
        Step(id="s01", action="assess", modal=ModalVerb.SHALL),
        Step(id="s02", action="small", modal=ModalVerb.SHALL),
        Step(id="s03", action="large", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    dec = Decision(
        id="d01",
        question="Is amount small?",
        preceding_step_id="s01",
        branches=[
            DecisionBranch(
                label="small", condition=_cmp("amount", "lt", 100), next_step_id="s02"
            ),
            DecisionBranch(
                label="large", condition=_cmp("amount", "ge", 100), next_step_id="s03"
            ),
        ],
    )
    transitions = [Transition(from_id="s02", to_id="s03")]
    ir = _simple_ir(steps, decisions=[dec], transitions=transitions)

    trace = simulate(ir, _scenario(facts={"amount": 50}))
    decision_step = next(ts for ts in trace.steps if ts.node_kind == "decision")
    assert decision_step.decision_outcome == DecisionOutcome.DETERMINED
    assert decision_step.branch_taken == "small"


def test_simulate_undetermined():
    steps = [Step(id="s01", action="check", modal=ModalVerb.SHALL)]
    dec = Decision(
        id="d01",
        question="Is X big?",
        preceding_step_id="s01",
        branches=[
            DecisionBranch(label="yes", condition=_cmp("x", "gt", 100), next_step_id="s01")
        ],
    )
    ir = _simple_ir(steps, decisions=[dec])
    trace = simulate(ir, _scenario(facts={"x": 50}))
    assert trace.outcome == TraceOutcome.UNDETERMINED


def test_simulate_conflict():
    steps = [
        Step(id="s01", action="check", modal=ModalVerb.SHALL),
        Step(id="s02", action="a", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
        Step(id="s03", action="b", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    dec = Decision(
        id="d01",
        question="Which?",
        preceding_step_id="s01",
        branches=[
            DecisionBranch(label="a", condition=_cmp("x", "gt", 10), next_step_id="s02"),
            DecisionBranch(label="b", condition=_cmp("x", "gt", 5), next_step_id="s03"),
        ],
    )
    ir = _simple_ir(steps, decisions=[dec])
    trace = simulate(ir, _scenario(facts={"x": 50}))
    assert trace.outcome == TraceOutcome.CONFLICT


def test_simulate_ambiguous():
    steps = [Step(id="s01", action="check", modal=ModalVerb.SHALL)]
    dec = Decision(
        id="d01",
        question="Urgent?",
        preceding_step_id="s01",
        branches=[
            DecisionBranch(
                label="yes", condition=VagueCondition(text="urgent"), next_step_id="s01"
            ),
            DecisionBranch(
                label="no", condition=VagueCondition(text="not urgent"), next_step_id="s01"
            ),
        ],
    )
    ir = _simple_ir(steps, decisions=[dec])
    trace = simulate(ir, _scenario())
    assert trace.outcome == TraceOutcome.AMBIGUOUS


def test_simulate_always_condition_branch():
    steps = [
        Step(id="s01", action="go", modal=ModalVerb.SHALL),
        Step(id="s02", action="done", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    dec = Decision(
        id="d01",
        question="Always?",
        preceding_step_id="s01",
        branches=[
            DecisionBranch(label="always", condition=AlwaysCondition(), next_step_id="s02"),
        ],
    )
    ir = _simple_ir(steps, decisions=[dec])
    trace = simulate(ir, _scenario())
    assert trace.outcome == TraceOutcome.COMPLETED


# ---------------------------------------------------------------------------
# Simulator — actor / system overrides
# ---------------------------------------------------------------------------


def test_simulate_actor_unavailable():
    steps = [
        Step(
            id="s01",
            action="approve",
            modal=ModalVerb.SHALL,
            actor_role_id="agent",
            kind=StepKind.APPROVAL,
        ),
        Step(id="s02", action="done", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    transitions = [Transition(from_id="s01", to_id="s02")]
    ir = _simple_ir(steps, transitions=transitions)
    trace = simulate(ir, _scenario(actor_overrides={"agent": None}))
    approval_step = next(ts for ts in trace.steps if ts.node_id == "s01")
    from app.schemas.trace import StepStatus

    assert approval_step.step_status == StepStatus.ACTOR_UNAVAILABLE
    assert trace.actor_unavailable_count == 1


def test_simulate_system_down():
    steps = [
        Step(id="s01", action="log", modal=ModalVerb.SHALL, systems=["crm"]),
        Step(id="s02", action="done", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    transitions = [Transition(from_id="s01", to_id="s02")]
    ir = _simple_ir(steps, transitions=transitions)
    trace = simulate(ir, _scenario(system_overrides={"crm": False}))
    assert trace.system_down_count == 1


# ---------------------------------------------------------------------------
# Evaluator — type coercion edge cases
# ---------------------------------------------------------------------------


def test_compare_bool_true():
    from app.schemas.ir_sop import CompareCondition, TypedValue, ValueType

    cond = CompareCondition(
        left="approved",
        op="eq",
        right=TypedValue(value_type=ValueType.BOOL, bool_value=True),
    )
    assert eval_condition(cond, {"approved": True}) == "true"
    assert eval_condition(cond, {"approved": False}) == "false"
