"""Coverage computation: which steps and decision branches were exercised."""

from __future__ import annotations

from app.schemas.ir_sop import SopIR
from app.schemas.testrun import CoverageReport
from app.schemas.trace import ExecutionTrace


def compute_coverage(ir: SopIR, traces: list[ExecutionTrace]) -> CoverageReport:
    """Compute step and branch coverage across all execution traces."""
    # Collect all steps and decisions from the IR
    all_step_ids: set[str] = set()
    all_branch_keys: set[str] = set()  # "decision_id:branch_label"
    all_decision_ids: set[str] = set()

    for proc in ir.processes:
        for step in proc.steps:
            all_step_ids.add(step.id)
        for dec in proc.decisions:
            all_decision_ids.add(dec.id)
            for branch in dec.branches:
                all_branch_keys.add(f"{dec.id}:{branch.label}")

    # Collect what was exercised across all traces
    covered_step_ids: set[str] = set()
    covered_decision_ids: set[str] = set()
    covered_branch_keys: set[str] = set()

    for trace in traces:
        for ts in trace.steps:
            if ts.node_kind in ("step", "terminal"):
                covered_step_ids.add(ts.node_id)
            elif ts.node_kind == "decision":
                covered_decision_ids.add(ts.node_id)
                if ts.branch_taken:
                    covered_branch_keys.add(f"{ts.node_id}:{ts.branch_taken}")

    uncovered_steps = sorted(all_step_ids - covered_step_ids)
    uncovered_branches = sorted(all_branch_keys - covered_branch_keys)

    steps_total = len(all_step_ids)
    steps_covered = len(covered_step_ids & all_step_ids)
    decisions_total = len(all_decision_ids)
    decisions_covered = len(covered_decision_ids & all_decision_ids)
    branches_total = len(all_branch_keys)
    branches_covered = len(covered_branch_keys & all_branch_keys)

    return CoverageReport(
        steps_total=steps_total,
        steps_covered=steps_covered,
        step_coverage_pct=round(100 * steps_covered / steps_total, 1) if steps_total else 100.0,
        decisions_total=decisions_total,
        decisions_covered=decisions_covered,
        decision_coverage_pct=(
            round(100 * decisions_covered / decisions_total, 1) if decisions_total else 100.0
        ),
        branches_total=branches_total,
        branches_covered=branches_covered,
        branch_coverage_pct=(
            round(100 * branches_covered / branches_total, 1) if branches_total else 100.0
        ),
        uncovered_step_ids=uncovered_steps,
        uncovered_branch_keys=uncovered_branches,
    )
