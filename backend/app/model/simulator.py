"""Layer 5 process simulator.

Walks a compiled SOP IR using a Scenario to produce an ExecutionTrace.

Decision semantics (four-valued):
  DETERMINED   — exactly one branch condition is "true"
  UNDETERMINED — no branch is "true"; none is vague/unknown
  CONFLICT     — multiple branches are "true"
  AMBIGUOUS    — at least one branch is "vague" or "unknown" and no branch is
                 definitively "true"
"""

from __future__ import annotations

import logging

from app.logic import norm_text, same_outcome
from app.model.evaluator import eval_condition
from app.schemas.ir_sop import (
    AlwaysCondition,
    CompareCondition,
    ConstraintKind,
    Decision,
    Process,
    SopIR,
    Step,
    StepKind,
    TimeUnit,
    ValueType,
)
from app.schemas.trace import (
    DecisionOutcome,
    ExecutionTrace,
    Scenario,
    StepStatus,
    TraceOutcome,
    TraceStep,
)

log = logging.getLogger(__name__)

# Unit conversions to seconds (approximate)
_TO_SECONDS: dict[str, float] = {
    TimeUnit.HOURS: 3600,
    TimeUnit.DAYS: 86400,
    TimeUnit.BUSINESS_DAYS: 28800,  # 8 h per business day
    TimeUnit.CALENDAR_DAYS: 86400,
    TimeUnit.WEEKS: 604800,
}


def _sla_seconds(step: Step) -> float | None:
    if step.sla is None or step.sla.vague:
        return None
    factor = _TO_SECONDS.get(step.sla.unit, 3600)
    return step.sla.max_duration * factor


def _step_duration(step: Step) -> float:
    """Approximate duration (seconds) to spend on a step (= SLA if defined, else 0)."""
    s = _sla_seconds(step)
    return s or 0.0


def _build_transition_map(proc: Process) -> dict[str, list[str]]:
    """Map node_id → [next_node_id, ...] from Transition objects."""
    m: dict[str, list[str]] = {}
    for t in proc.transitions:
        m.setdefault(t.from_id, []).append(t.to_id)
    return m


def _rework(dec: Decision, facts: dict) -> bool:
    """Model the requester fixing the problem: flip a yes/no fact so another branch applies."""
    for branch in dec.branches:
        c = branch.condition
        if (
            isinstance(c, CompareCondition)
            and c.right.value_type == ValueType.BOOL
            and c.right.bool_value is not None
            and facts.get(c.left) is not None
            and bool(facts[c.left]) != c.right.bool_value
        ):
            facts[c.left] = c.right.bool_value
            return True
    return False


def _requester_value(facts: dict) -> str | None:
    for key, value in facts.items():
        if "requester" in key.lower() or "submitter" in key.lower():
            return norm_text(value)
    return None


def simulate(ir: SopIR, scenario: Scenario) -> ExecutionTrace:
    """Run the simulator and return a complete ExecutionTrace."""
    # Select process
    proc: Process | None = None
    if scenario.process_id:
        proc = next((p for p in ir.processes if p.id == scenario.process_id), None)
    if proc is None and ir.processes:
        proc = ir.processes[0]
    if proc is None:
        return ExecutionTrace(
            run_id=ir.run_id,
            process_id="",
            scenario_id=scenario.id,
            scenario=scenario,
            outcome=TraceOutcome.DEAD_END,
        )

    decision_map = {d.id: d for d in proc.decisions}
    step_map = {s.id: s for s in proc.steps}

    facts = dict(scenario.facts)  # the simulator may model rework by correcting a yes/no fact
    no_self_action = any(c.kind == ConstraintKind.NO_SELF_ACTION for c in proc.constraints)
    reworks = 0
    trace_steps: list[TraceStep] = []
    visited: set[str] = set()
    elapsed_s: float = 0.0
    sla_breaches = 0
    actor_unavailable_count = 0
    system_down_count = 0

    # Start node = first step in declaration order
    current_id: str = proc.entry() or ""
    if not current_id:
        return ExecutionTrace(
            run_id=ir.run_id,
            process_id=proc.id,
            scenario_id=scenario.id,
            scenario=scenario,
            outcome=TraceOutcome.DEAD_END,
        )

    outcome = TraceOutcome.COMPLETED
    seq = 0

    while seq < scenario.max_steps:
        if current_id == "END":
            outcome = TraceOutcome.COMPLETED
            break
        # Loop detection (a rework loop is allowed to run again once the requester has fixed it)
        if current_id in visited:
            last_dec = next(
                (decision_map[t.node_id] for t in reversed(trace_steps) if t.node_id in decision_map),
                None,
            )
            if last_dec is not None and reworks < 3 and _rework(last_dec, facts):
                reworks += 1
                visited = set()
            else:
                outcome = TraceOutcome.LOOP_DETECTED
                break
        visited.add(current_id)

        # ── Decision node ──────────────────────────────────────────────────
        if current_id in decision_map:
            dec = decision_map[current_id]
            true_branches = []
            non_false_branches = []

            for branch in dec.branches:
                if isinstance(branch.condition, AlwaysCondition):
                    continue  # an "otherwise" branch only applies when no explicit branch does
                result = eval_condition(branch.condition, facts)
                if result == "true":
                    true_branches.append(branch)
                if result in ("true", "vague", "unknown"):
                    non_false_branches.append(branch)

            if len(true_branches) > 1 and all(
                same_outcome(proc, true_branches[0].next_step_id, b.next_step_id)
                for b in true_branches[1:]
            ):
                true_branches = true_branches[:1]  # redundant rules agreeing on the outcome
            if len(true_branches) > 1:
                dec_outcome = DecisionOutcome.CONFLICT
                trace_outcome = TraceOutcome.CONFLICT
            elif len(true_branches) == 1:
                dec_outcome = DecisionOutcome.DETERMINED
                trace_outcome = None
            elif non_false_branches:
                dec_outcome = DecisionOutcome.AMBIGUOUS
                trace_outcome = TraceOutcome.AMBIGUOUS
            else:
                # Check for AlwaysCondition branch
                always = next(
                    (b for b in dec.branches if isinstance(b.condition, AlwaysCondition)),
                    None,
                )
                if always:
                    true_branches = [always]
                    dec_outcome = DecisionOutcome.DETERMINED
                    trace_outcome = None
                else:
                    dec_outcome = DecisionOutcome.UNDETERMINED
                    trace_outcome = TraceOutcome.UNDETERMINED

            chosen = true_branches[0] if true_branches else None
            ts = TraceStep(
                seq=seq,
                node_id=current_id,
                node_kind="decision",
                process_id=proc.id,
                action=dec.question,
                decision_outcome=dec_outcome,
                branch_taken=chosen.label if chosen else None,
                elapsed_s=elapsed_s,
                source_spans=dec.source_spans,
            )
            trace_steps.append(ts)
            seq += 1

            if trace_outcome is not None:
                outcome = trace_outcome
                break

            current_id = chosen.next_step_id  # type: ignore[union-attr]
            continue

        # ── Step node ──────────────────────────────────────────────────────
        step = step_map.get(current_id)
        if step is None:
            # Dangling reference (shouldn't happen in a validated IR)
            outcome = TraceOutcome.DEAD_END
            break

        node_kind: str = "terminal" if step.kind == StepKind.TERMINAL else "step"

        # Resolve actor
        role_id = step.actor_role_id
        actor: str | None = None
        step_status = StepStatus.OK
        note: str | None = None

        if role_id:
            if role_id in scenario.actor_overrides:
                actor = scenario.actor_overrides[role_id]
                if actor is None:
                    step_status = StepStatus.ACTOR_UNAVAILABLE
                    actor_unavailable_count += 1
                    note = f"actor '{role_id}' unavailable"
            else:
                role_ref = ir.symbols.role(role_id)
                actor = role_ref.name if role_ref else role_id

        # Segregation of duties: nobody may approve their own request
        requester = _requester_value(facts)
        if (
            no_self_action
            and requester
            and role_id
            and step_status == StepStatus.OK
            and (step.kind in (StepKind.APPROVAL, StepKind.VERIFICATION) or "approv" in step.action.lower())
            and requester in {norm_text(role_id), norm_text(actor or "")}
        ):
            step_status = StepStatus.ACTOR_UNAVAILABLE
            actor_unavailable_count += 1
            note = f"no eligible approver: the {actor or role_id} may not approve their own request"

        # Check systems
        if step_status == StepStatus.OK:
            for sys_id in step.systems:
                if sys_id in scenario.system_overrides and not scenario.system_overrides[sys_id]:
                    step_status = StepStatus.SYSTEM_DOWN
                    system_down_count += 1
                    note = f"system '{sys_id}' is down"
                    break

        # SLA
        sla_s = _sla_seconds(step)
        dur = _step_duration(step)
        elapsed_s += dur
        sla_ok: bool | None = None
        if sla_s is not None:
            sla_ok = dur <= sla_s
            if not sla_ok:
                sla_breaches += 1
                if step_status == StepStatus.OK:
                    step_status = StepStatus.SLA_BREACHED

        ts = TraceStep(
            seq=seq,
            node_id=current_id,
            node_kind=node_kind,  # type: ignore[arg-type]
            process_id=proc.id,
            action=step.action,
            actor=actor,
            step_status=step_status,
            sla_max_s=sla_s,
            elapsed_s=elapsed_s,
            sla_ok=sla_ok,
            source_spans=step.source_spans,
            note=note,
        )
        trace_steps.append(ts)
        seq += 1

        if step.kind == StepKind.TERMINAL:
            outcome = TraceOutcome.COMPLETED
            break

        # Find next node from transitions first, then decision map
        outs = [t for t in proc.transitions if t.from_id == current_id]
        chosen_t = next((t for t in outs if eval_condition(t.condition, facts) == "true"), None)
        if chosen_t is None and outs:
            chosen_t = outs[0]
        if chosen_t is not None:
            current_id = chosen_t.to_id
        else:
            # Check if the step leads to a decision
            dec_next = next(
                (d.id for d in proc.decisions if d.preceding_step_id == current_id),
                None,
            )
            if dec_next:
                current_id = dec_next
            else:
                outcome = TraceOutcome.DEAD_END
                break
    else:
        outcome = TraceOutcome.MAX_STEPS

    violations: list[str] = []
    order = [t.node_id for t in trace_steps]
    for c in proc.constraints:
        if c.kind != ConstraintKind.MUST_PRECEDE or not (c.before_step_id and c.target_step_id):
            continue
        if c.target_step_id in order:
            first_target = order.index(c.target_step_id)
            from app.extract.shortcuts import equivalent_steps

            if not (equivalent_steps(proc, c.before_step_id) & set(order[:first_target])):
                violations.append(f"{c.target_step_id} reached without {c.before_step_id}")

    return ExecutionTrace(
        run_id=ir.run_id,
        process_id=proc.id,
        scenario_id=scenario.id,
        scenario=scenario,
        steps=trace_steps,
        violations=violations,
        outcome=outcome,
        elapsed_s=elapsed_s,
        sla_breaches=sla_breaches,
        actor_unavailable_count=actor_unavailable_count,
        system_down_count=system_down_count,
    )
