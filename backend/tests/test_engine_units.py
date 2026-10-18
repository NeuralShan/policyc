"""Unit tests for the shared logic, text rules, flow normaliser, rule checks and simulator changes."""

import pytest

from app.analyze.checks.decisions_z3 import decision_checks
from app.analyze.checks.rules import deadline_checks, ordering_checks, segregation_checks
from app.extract.flow import normalize_flow
from app.extract.textrules import (
    is_exception_text,
    is_no_self_action,
    parse_applicability,
    parse_deadline,
)
from app.logic import ConstraintBuilder, normalize_op
from app.model.evaluator import eval_condition
from app.model.simulator import simulate
from app.schemas.ir_sop import (
    SLA,
    AlwaysCondition,
    CompareCondition,
    Constraint,
    ConstraintKind,
    Deadline,
    Decision,
    DecisionBranch,
    Process,
    RoleRef,
    SopIR,
    Step,
    StepKind,
    SymbolTable,
    TimeUnit,
    Transition,
    TypedValue,
    ValueType,
)
from app.schemas.trace import Scenario, TraceOutcome


def money(left, op, n):
    return CompareCondition(
        left=left, op=op, right=TypedValue(value_type=ValueType.MONEY, number=n, currency="INR")
    )


def enum(left, value, op="eq"):
    return CompareCondition(left=left, op=op, right=TypedValue(value_type=ValueType.ENUM, text=value))


def boolean(left, value):
    return CompareCondition(left=left, op="eq", right=TypedValue(value_type=ValueType.BOOL, bool_value=value))


def make_ir(proc: Process, roles=()) -> SopIR:
    return SopIR(
        run_id="r",
        document_ids=["d"],
        processes=[proc],
        symbols=SymbolTable(roles=[RoleRef(id=r, name=r.replace("_", " ").title()) for r in roles]),
    )


# --- operators -------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,canonical",
    [("lte", "le"), ("<=", "le"), ("gte", "ge"), (">=", "ge"), ("LT", "lt"), ("equals", "eq"), ("!=", "ne")],
)
def test_operator_aliases(raw, canonical):
    assert normalize_op(raw) == canonical


def test_lte_and_gte_evaluate_instead_of_unknown():
    # the extraction prompt emits "lte"/"gte"; the evaluator used to answer "unknown" for both
    assert eval_condition(money("amount", "lte", 10000), {"amount": 10000}) == "true"
    assert eval_condition(money("amount", "gte", 10000), {"amount": 9999}) == "false"


def test_enum_comparison_ignores_case_and_punctuation():
    assert eval_condition(enum("role", "finance_head"), {"role": "Finance Head"}) == "true"


# --- solver ----------------------------------------------------------------


def _decision(branches):
    return Decision(id="d1", question="Route?", preceding_step_id="s1", branches=branches)


def _proc(decision, steps=None):
    steps = steps or [
        Step(id="s1", action="Start", actor_role_id="a"),
        Step(id="s2", action="Low", actor_role_id="mgr"),
        Step(id="s3", action="High", actor_role_id="fin"),
    ]
    return Process(id="p", name="P", document_id="d", steps=steps, decisions=[decision])


def test_gap_between_below_and_above_is_reported_with_the_exact_value():
    dec = _decision(
        [
            DecisionBranch(label="low", condition=money("amount", "lt", 10000), next_step_id="s2"),
            DecisionBranch(label="high", condition=money("amount", "gt", 10000), next_step_id="s3"),
        ]
    )
    diags = decision_checks(make_ir(_proc(dec)), None)
    gap = [d for d in diags if d.code == "ST004"]
    assert len(gap) == 1 and gap[0].evidence["counterexample"] == {"amount": 10000.0}


def test_otherwise_branch_is_exhaustive_and_never_overlaps():
    dec = _decision(
        [
            DecisionBranch(label="low", condition=money("amount", "lt", 10000), next_step_id="s2"),
            DecisionBranch(label="otherwise", condition=AlwaysCondition(), next_step_id="s3"),
        ]
    )
    assert decision_checks(make_ir(_proc(dec)), None) == []


def test_enum_and_number_overlap_leads_to_different_outcomes():
    dec = _decision(
        [
            DecisionBranch(label="low", condition=money("amount", "lt", 10000), next_step_id="s2"),
            DecisionBranch(label="mgr", condition=enum("requester_role", "manager"), next_step_id="s3"),
            DecisionBranch(label="rest", condition=AlwaysCondition(), next_step_id="s2"),
        ]
    )
    diags = decision_checks(make_ir(_proc(dec)), None)
    overlap = [d for d in diags if d.code == "ST005"]
    assert len(overlap) == 1
    assert overlap[0].evidence["counterexample"]["requester_role"] == "manager"


def test_overlap_with_the_same_outcome_is_not_a_conflict():
    steps = [
        Step(id="s1", action="Start", actor_role_id="a"),
        Step(id="s2", action="Approve big", kind=StepKind.APPROVAL, actor_role_id="fin"),
        Step(id="s3", action="Approve manager", kind=StepKind.APPROVAL, actor_role_id="fin"),
    ]
    dec = _decision(
        [
            DecisionBranch(label="big", condition=money("amount", "gt", 10000), next_step_id="s2"),
            DecisionBranch(label="mgr", condition=enum("requester_role", "manager"), next_step_id="s3"),
            DecisionBranch(label="rest", condition=AlwaysCondition(), next_step_id="s2"),
        ]
    )
    assert not [d for d in decision_checks(make_ir(_proc(dec, steps)), None) if d.code == "ST005"]


def test_builder_gives_other_value_for_enums():
    b = ConstraintBuilder()
    cond = enum("requester_role", "manager")
    b.scan(cond)
    assert b.enum_values["requester_role"] == ["other", "manager"]
    assert b.baseline() == {"requester_role": "other"}


# --- text rules --------------------------------------------------------------


def test_text_rules_read_thresholds_roles_deadlines_and_prohibitions():
    roles = [RoleRef(id="finance_head", name="Finance Head")]
    below = parse_applicability("Claims below INR 10,000 are approved by the line manager.", roles)
    assert below.op == "lt" and below.right.number == 10000 and below.right.currency == "INR"
    mgr = parse_applicability("Claims submitted by a manager are approved by the Finance Head.", roles)
    assert mgr.left == "requester_role" and mgr.right.text == "manager"
    own = parse_applicability("The Finance Head's own claims must be approved by the Finance Head.", roles)
    assert own.right.text == "finance_head"
    assert parse_deadline("Every claim must be reimbursed within 7 calendar days of submission.") == (
        7.0,
        TimeUnit.CALENDAR_DAYS,
        "submission",
    )
    assert is_no_self_action("No person may approve their own claim.")
    assert not is_no_self_action("The requester submits the claim.")
    assert is_exception_text("Claims escalated by the Audit Committee are re-reviewed.")
    assert not is_exception_text("Pay approved claims.")


# --- flow normaliser ---------------------------------------------------------


def test_flow_normaliser_builds_routing_and_keeps_the_gap_visible():
    steps = [
        Step(id="s3.1", number="3.1", action="Submit claim", actor_role_id="req"),
        Step(id="s4.1", number="4.1", action="Approve claims below INR 10,000", actor_role_id="lm"),
        Step(id="s4.2", number="4.2", action="Approve claims above INR 10,000", actor_role_id="fh"),
        Step(id="s5.1", number="5.1", action="Pay claim", actor_role_id="acc"),
        Step(id="s6.1", number="6.1", action="Claims escalated by the Audit Committee are re-reviewed",
             actor_role_id="ia"),
    ]
    proc = Process(id="p", name="P", document_id="d", steps=steps)
    ir = make_ir(proc, roles=["req", "lm", "fh", "acc", "ia"])
    normalize_flow(proc, ir.symbols, {"3": "Submission", "4": "Approval", "5": "Payment", "6": "Audit"})

    assert proc.entry() == "s3.1"
    routing = proc.decision("d_route_4")
    assert routing and {b.next_step_id for b in routing.branches} == {"s4.1", "s4.2"}
    assert all(t.inferred for t in proc.transitions)  # nothing here was stated by the document
    codes = {d.code for d in decision_checks(ir, None)}
    assert "ST004" in codes  # exactly 10,000 is still unhandled: the normaliser does not fix the SOP
    # the audit step is an exception clause: it must stay unreachable, not be chained in
    from app.analyze.checks.structural import structural_checks

    unreachable = [d.step_id for d in structural_checks(ir, None) if d.code == "ST001"]
    assert unreachable == ["s6.1"]


def test_with_without_labels_become_one_boolean():
    steps = [
        Step(id="s1", action="Check", actor_role_id="a"),
        Step(id="s2", action="Return", actor_role_id="a"),
        Step(id="s3", action="Continue", actor_role_id="a"),
    ]
    dec = Decision(
        id="d1",
        question="Receipts?",
        preceding_step_id="s1",
        branches=[
            DecisionBranch(label="Without receipts", condition=AlwaysCondition(), next_step_id="s2"),
            DecisionBranch(label="With receipts", condition=AlwaysCondition(), next_step_id="s3"),
        ],
    )
    proc = Process(id="p", name="P", document_id="d", steps=steps, decisions=[dec])
    ir = make_ir(proc)
    normalize_flow(proc, ir.symbols, {})
    left = {b.condition.left for b in dec.branches}
    assert left == {"receipts_present"}
    assert decision_checks(ir, None) == []


# --- rule checks -----------------------------------------------------------


def test_deadline_infeasible_reports_the_sum():
    steps = [
        Step(id="a", action="Approve", actor_role_id="x", sla=SLA(max_duration=3, unit=TimeUnit.BUSINESS_DAYS)),
        Step(id="b", action="Pay", actor_role_id="y", sla=SLA(max_duration=5, unit=TimeUnit.BUSINESS_DAYS)),
    ]
    proc = Process(
        id="p",
        name="P",
        document_id="d",
        steps=steps,
        transitions=[Transition(from_id="a", to_id="b"), Transition(from_id="b", to_id="END")],
        deadlines=[Deadline(id="dl", description="within 7 days", max_duration=7, unit=TimeUnit.CALENDAR_DAYS)],
    )
    diags = deadline_checks(make_ir(proc), None)
    assert len(diags) == 1 and diags[0].evidence["path_hours"] == 192 and diags[0].evidence["allowed_hours"] == 168


def test_mandatory_step_bypass_is_found_through_the_exception():
    steps = [
        Step(id="shutdown", action="Shut down"),
        Step(id="isolate", action="Isolate energy"),
        Step(id="verify", action="Verify zero energy"),
        Step(id="maintain", action="Perform maintenance"),
    ]
    dec = Decision(
        id="d1",
        question="Minor tool change?",
        preceding_step_id="shutdown",
        branches=[
            DecisionBranch(label="minor", condition=boolean("minor", True), next_step_id="maintain"),
            DecisionBranch(label="otherwise", condition=AlwaysCondition(), next_step_id="isolate"),
        ],
    )
    proc = Process(
        id="p",
        name="P",
        document_id="d",
        steps=steps,
        decisions=[dec],
        transitions=[
            Transition(from_id="isolate", to_id="verify"),
            Transition(from_id="verify", to_id="maintain"),
            Transition(from_id="maintain", to_id="END"),
        ],
        constraints=[
            Constraint(id="c1", kind=ConstraintKind.MUST_PRECEDE, description="verify first",
                       before_step_id="verify", target_step_id="maintain")
        ],
    )
    diags = ordering_checks(make_ir(proc), None)
    assert len(diags) == 1 and diags[0].code == "ST008"
    assert diags[0].evidence["path"] == ["shutdown", "d1", "maintain"]


def _self_approval_ir():
    steps = [
        Step(id="s1", action="Submit", actor_role_id="req"),
        Step(id="s2", action="Approve by manager", kind=StepKind.APPROVAL, actor_role_id="manager"),
        Step(id="s3", action="Approve by finance head", kind=StepKind.APPROVAL, actor_role_id="finance_head"),
    ]
    dec = Decision(
        id="d1",
        question="Who approves?",
        preceding_step_id="s1",
        branches=[
            DecisionBranch(label="fh own", condition=enum("requester_role", "finance_head"), next_step_id="s3"),
            DecisionBranch(label="others", condition=enum("requester_role", "finance_head", "ne"), next_step_id="s2"),
        ],
    )
    proc = Process(
        id="p", name="P", document_id="d", steps=steps, decisions=[dec],
        constraints=[Constraint(id="c1", kind=ConstraintKind.NO_SELF_ACTION, description="No person may approve their own claim.")],
    )
    return make_ir(proc, roles=["req", "manager", "finance_head"])


def test_self_approval_deadlock_is_proved_by_the_solver():
    diags = segregation_checks(_self_approval_ir(), None)
    assert [d.step_id for d in diags] == ["s3"]
    assert diags[0].evidence["counterexample"] == {"requester_role": "finance_head"}


def test_simulator_blocks_self_approval_and_ends_at_END():
    ir = _self_approval_ir()
    proc = ir.processes[0]
    proc.transitions += [Transition(from_id="s1", to_id="d1"), Transition(from_id="s2", to_id="END"),
                         Transition(from_id="s3", to_id="END")]
    ok = simulate(ir, Scenario(id="a", description="", facts={"requester_role": "staff"}))
    assert ok.outcome == TraceOutcome.COMPLETED and ok.actor_unavailable_count == 0
    stuck = simulate(ir, Scenario(id="b", description="", facts={"requester_role": "finance_head"}))
    assert stuck.actor_unavailable_count == 1
    assert any("own request" in (s.note or "") for s in stuck.steps)


def test_simulator_corrects_a_fact_once_to_model_rework():
    steps = [
        Step(id="s1", action="Check"),
        Step(id="s2", action="Return"),
        Step(id="s3", action="Pay"),
    ]
    dec = Decision(
        id="d1",
        question="Receipts?",
        preceding_step_id="s1",
        branches=[
            DecisionBranch(label="with", condition=boolean("receipts_present", True), next_step_id="s3"),
            DecisionBranch(label="without", condition=boolean("receipts_present", False), next_step_id="s2"),
        ],
    )
    proc = Process(
        id="p", name="P", document_id="d", steps=steps, decisions=[dec],
        transitions=[Transition(from_id="s1", to_id="d1"), Transition(from_id="s2", to_id="s1"),
                     Transition(from_id="s3", to_id="END")],
    )
    trace = simulate(make_ir(proc), Scenario(id="x", description="", facts={"receipts_present": False}))
    assert trace.outcome == TraceOutcome.COMPLETED


# --- reference / outcome / separate-flow handling -------------------------------


def _quote(text):
    from app.schemas.provenance import SourceSpan

    return [SourceSpan(document_id="d", char_start=0, char_end=len(text), quote=text)]


def test_broken_cross_reference_is_reported_and_not_linked_onward():
    from app.analyze.checks.rules import reference_checks
    from app.analyze.checks.structural import structural_checks

    steps = [
        Step(id="s1", number="2.1", action="Receive application", actor_role_id="a"),
        Step(id="s2", number="2.2", action="Open joint account with a guardian as described in Section 9",
             actor_role_id="g", source_spans=_quote("as described in Section 9")),
        Step(id="s3", number="3.1", action="Collect documents", actor_role_id="a"),
    ]
    proc = Process(id="p", name="P", document_id="d", steps=steps)
    ir = make_ir(proc, roles=["a", "g"])
    normalize_flow(proc, ir.symbols, {"2": "Eligibility", "3": "KYC"})
    assert [d.step_id for d in reference_checks(ir, None)] == ["s2"]
    # the hand-off step is not silently chained to the next clause: it stays a visible dead end
    assert not any(t.from_id == "s2" for t in proc.transitions)
    assert any(d.code == "ST002" and d.step_id == "s2" for d in structural_checks(ir, None))


def test_outcome_branch_targets_end_the_process():
    steps = [
        Step(id="s1", number="3.1", action="Verify documents", actor_role_id="a"),
        Step(id="s2", number="3.2", action="Proceed to risk assessment", actor_role_id="a"),
        Step(id="s3", number="3.3", action="Reject the application", actor_role_id="a"),
    ]
    dec = Decision(
        id="d1", question="Verified?", preceding_step_id="s1",
        branches=[
            DecisionBranch(label="verified", condition=boolean("documents_verified", True), next_step_id="s2"),
            DecisionBranch(label="not verified", condition=boolean("documents_verified", False), next_step_id="s3"),
        ],
    )
    proc = Process(id="p", name="P", document_id="d", steps=steps, decisions=[dec])
    ir = make_ir(proc)
    normalize_flow(proc, ir.symbols, {"3": "KYC"})
    assert any(t.from_id == "s3" and t.to_id == "END" and t.inferred for t in proc.transitions)


def test_periodic_section_is_not_chained_into_the_request_flow():
    steps = [
        Step(id="s1", number="3.1", action="Raise request", actor_role_id="a"),
        Step(id="s2", number="3.2", action="Grant access", actor_role_id="b"),
        Step(id="s3", number="6.1", action="Revoke access that is no longer needed", actor_role_id="b"),
    ]
    proc = Process(id="p", name="P", document_id="d", steps=steps)
    ir = make_ir(proc)
    normalize_flow(proc, ir.symbols, {"3": "Request", "6": "Recertification"})
    from app.analyze.checks.structural import structural_checks

    assert [d.step_id for d in structural_checks(ir, None) if d.code == "ST001"] == ["s3"]


# --- lockout/tagout: exception shortcut, mandatory-order bypass, runtime proof --------


def _loto_ir():
    q = _quote
    steps = [
        Step(id="s2.1", number="2.1", action="Notify affected employees", actor_role_id="emp"),
        Step(id="s2.2", number="2.2", action="Shut down the machine using its normal stopping procedure",
             actor_role_id="emp"),
        Step(id="s2.3", number="2.3", action="Isolate all energy sources", actor_role_id="emp"),
        Step(id="s2.4", number="2.4", action="Apply lock and tag", actor_role_id="emp"),
        Step(id="s2.5", number="2.5", action="Verify zero energy", actor_role_id="emp", kind=StepKind.VERIFICATION),
        Step(id="s2.6", number="2.6", action="Perform maintenance or servicing", actor_role_id="emp"),
        Step(id="s3.1", number="3.1", action="Proceed directly to maintenance after shutting down the machine",
             actor_role_id="op",
             source_spans=q("For minor tool changes expected to take less than 10 minutes, the operator may "
                            "proceed directly to maintenance after shutting down the machine.")),
    ]
    transitions = [Transition(from_id=a, to_id=b) for a, b in
                   [("s2.1", "s2.2"), ("s2.2", "s2.3"), ("s2.3", "s2.4"), ("s2.4", "s2.5"), ("s2.5", "s2.6")]]
    transitions.append(Transition(from_id="s2.6", to_id="END"))
    proc = Process(
        id="p", name="LOTO", document_id="d", steps=steps, transitions=transitions,
        constraints=[Constraint(id="c1", kind=ConstraintKind.MUST_PRECEDE, description="verify first",
                                before_step_id="s2.5", target_step_id="s2.6")],
    )
    return make_ir(proc, roles=["emp", "op"])


def test_exception_shortcut_becomes_a_decision_and_exposes_the_bypass():
    from app.analyze.checks.structural import structural_checks

    ir = _loto_ir()
    proc = ir.processes[0]
    normalize_flow(proc, ir.symbols, {"2": "Procedure", "3": "Exceptions"})
    dec = proc.decision("d_shortcut_3.1")
    assert dec and dec.preceding_step_id == "s2.2"
    assert {b.next_step_id for b in dec.branches} == {"s2.6", "s2.3"}
    assert not [d for d in structural_checks(ir, None) if d.code == "ST001"]
    bypass = ordering_checks(ir, None)
    assert len(bypass) == 1 and bypass[0].evidence["path"][-1] == "s2.6"
    assert "s2.5" not in bypass[0].evidence["path"]


def test_runtime_scenario_proves_the_bypass():
    from app.run.runner import run_test_suite
    from app.testgen.service import TestGenService

    ir = _loto_ir()
    normalize_flow(ir.processes[0], ir.symbols, {"2": "Procedure", "3": "Exceptions"})
    report = run_test_suite(ir, TestGenService(None).generate(ir, "r"))
    bad = [r for r in report.results if r.trace and r.trace.violations]
    assert bad, "a task under 10 minutes must skip verification"
    assert all(r.trace.scenario.facts["task_duration_minutes"] < 10 for r in bad)
    assert any(r.verdict.value == "fail" and "order_violation" in [x.value for x in r.fail_reasons] for r in bad)
    assert any(r.verdict.value == "pass" for r in report.results)


def test_ordering_rule_clause_becomes_a_constraint_not_a_step():
    ir = _loto_ir()
    proc = ir.processes[0]
    proc.constraints.clear()
    proc.steps.append(
        Step(id="s2.7", number="2.7", action="Verify zero energy before maintenance begins", actor_role_id=None,
             source_spans=_quote("Verification of zero energy must always be performed before any maintenance "
                                 "or servicing begins."))
    )
    normalize_flow(proc, ir.symbols, {"2": "Procedure", "3": "Exceptions"})
    assert proc.step("s2.7").off_flow
    cons = [(c.before_step_id, c.target_step_id) for c in proc.constraints]
    assert cons == [("s2.5", "s2.6")]
    assert ordering_checks(ir, None)  # ...and the exception shortcut violates it


def test_dead_end_joiner_rejoins_the_step_its_predecessors_continue_to():
    steps = [Step(id=i, number=n, action=a, actor_role_id="x") for i, n, a in
             [("a", "4.1", "Approve small"), ("b", "4.2", "Approve large"), ("c", "4.3", "Decide within 2 days"),
              ("d", "5.1", "Record outcome")]]
    proc = Process(
        id="p", name="P", document_id="d", steps=steps,
        transitions=[Transition(from_id="a", to_id="c"), Transition(from_id="b", to_id="c"),
                     Transition(from_id="a", to_id="d"), Transition(from_id="b", to_id="d"),
                     Transition(from_id="d", to_id="END")],
    )
    ir = make_ir(proc)
    normalize_flow(proc, ir.symbols, {})
    assert any(t.from_id == "c" and t.to_id == "d" and t.inferred for t in proc.transitions)


def test_outcome_clauses_become_an_approval_decision_without_a_loop():
    from app.analyze.checks.structural import structural_checks

    steps = [
        Step(id="s4.3", number="4.3", action="Decide within 2 working days", actor_role_id="approver"),
        Step(id="s5.1", number="5.1", action="Record approved leave", actor_role_id="hr",
             source_spans=_quote("Approved leave is recorded in the HR portal.")),
        Step(id="s5.2", number="5.2", action="Close rejected requests", actor_role_id="hr",
             source_spans=_quote("Rejected requests are closed and the employee is notified.")),
        Step(id="s5.3", number="5.3", action="Notify the employee", actor_role_id="hr"),
    ]
    proc = Process(
        id="p", name="P", document_id="d", steps=steps,
        transitions=[Transition(from_id="s5.1", to_id="s5.3"), Transition(from_id="s5.2", to_id="s5.3"),
                     Transition(from_id="s5.3", to_id="END")],
    )
    ir = make_ir(proc, roles=["approver", "hr"])
    normalize_flow(proc, ir.symbols, {"4": "Approval", "5": "Outcome"})
    dec = proc.decision("d_outcome_s5.1")
    assert dec and dec.preceding_step_id == "s4.3"
    assert {b.next_step_id for b in dec.branches} == {"s5.1", "s5.2"}
    codes = {d.code for d in structural_checks(ir, None) + decision_checks(ir, None)}
    assert not codes & {"ST001", "ST002", "ST003", "ST004", "ST005"}


def test_patched_exception_that_verifies_first_no_longer_bypasses():
    """After the fix "the operator must verify zero energy before proceeding directly to maintenance"
    the clause splits into verify + proceed; the exception path now contains its own verification."""
    ir = _loto_ir()
    proc = ir.processes[0]
    q = _quote("For minor tool changes expected to take less than 10 minutes, the operator must verify zero "
               "energy before proceeding directly to maintenance after shutting down the machine.")
    proc.steps = [s for s in proc.steps if s.id != "s3.1"] + [
        Step(id="s3.1a", number="3.1", action="verify zero energy before proceeding", actor_role_id="op", source_spans=q),
        Step(id="s3.1b", number="3.1", action="proceed directly to maintenance after shutting down the machine",
             actor_role_id="op", source_spans=q),
    ]
    normalize_flow(proc, ir.symbols, {"2": "Procedure", "3": "Exceptions"})
    assert len([d for d in proc.decisions if d.id.startswith("d_shortcut_")]) == 1
    assert ordering_checks(ir, None) == []
    from app.run.runner import run_test_suite
    from app.testgen.service import TestGenService

    report = run_test_suite(ir, TestGenService(None).generate(ir, "r"))
    assert not [r for r in report.results if r.trace and r.trace.violations]
