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

from app.model.evaluator import eval_condition
from app.schemas.ir_sop import (
    AlwaysCondition,
    Process,
    SopIR,
    Step,
    StepKind,
    TimeUnit,
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

    transition_map = _build_transition_map(proc)
    decision_map = {d.id: d for d in proc.decisions}
    step_map = {s.id: s for s in proc.steps}

    facts = scenario.facts
    trace_steps: list[TraceStep] = []
    visited: set[str] = set()
    elapsed_s: float = 0.0
    sla_breaches = 0
    actor_unavailable_count = 0
    system_down_count = 0

    # Start node = first step in declaration order
    current_id: str = proc.steps[0].id if proc.steps else ""
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
        # Loop detection
        if current_id in visited:
            outcome = TraceOutcome.LOOP_DETECTED
            break
        visited.add(current_id)

        # ── Decision node ──────────────────────────────────────────────────
        if current_id in decision_map:
            dec = decision_map[current_id]
            true_branches = []
            non_false_branches = []

            for branch in dec.branches:
                result = eval_condition(branch.condition, facts)
                if result == "true":
                    true_branches.append(branch)
                if result in ("true", "vague", "unknown"):
                    non_false_branches.append(branch)

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
        nexts = transition_map.get(current_id, [])
        if nexts:
            current_id = nexts[0]
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

    return ExecutionTrace(
        run_id=ir.run_id,
        process_id=proc.id,
        scenario_id=scenario.id,
        scenario=scenario,
        steps=trace_steps,
        outcome=outcome,
        elapsed_s=elapsed_s,
        sla_breaches=sla_breaches,
        actor_unavailable_count=actor_unavailable_count,
        system_down_count=system_down_count,
    )
