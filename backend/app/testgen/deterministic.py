"""6.1 Deterministic test generation: boundary values and path coverage.

No LLM calls. Extracts numeric thresholds from decision conditions, then
produces three scenarios per threshold (value below, at, and above).
Also generates one happy-path scenario per process.
"""

from __future__ import annotations

import re

from app.schemas.ir_sop import (
    CompareCondition,
    ConditionExpr,
    LogicalCondition,
    SopIR,
    StepKind,
)
from app.schemas.testcase import TestCase, TestOrigin
from app.schemas.trace import Scenario, TraceOutcome


def _collect_thresholds(
    expr: ConditionExpr,
    out: dict[str, set[float]],
) -> None:
    """Recursively collect (variable, numeric_threshold) pairs from a condition."""
    if isinstance(expr, CompareCondition):
        rv = expr.right
        if rv.number is not None:
            out.setdefault(expr.left, set()).add(float(rv.number))
    elif isinstance(expr, LogicalCondition):
        for sub in expr.operands:
            _collect_thresholds(sub, out)


def extract_thresholds(ir: SopIR) -> dict[str, list[float]]:
    """Return {variable_name: sorted_thresholds} from all decisions in the IR."""
    raw: dict[str, set[float]] = {}
    for proc in ir.processes:
        for dec in proc.decisions:
            for branch in dec.branches:
                _collect_thresholds(branch.condition, raw)
    return {k: sorted(v) for k, v in raw.items()}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", text.lower()).strip("_")


def generate_boundary_tests(ir: SopIR) -> list[TestCase]:
    """For each numeric threshold t, generate facts: t-1, t, t+1."""
    tests: list[TestCase] = []
    thresholds = extract_thresholds(ir)

    for proc in ir.processes:
        relevant_vars = set()
        for dec in proc.decisions:
            raw: dict[str, set[float]] = {}
            for branch in dec.branches:
                _collect_thresholds(branch.condition, raw)
            relevant_vars.update(raw)

        for var in sorted(relevant_vars):
            for t in thresholds.get(var, []):
                for delta, tag in [(-1.0, "below"), (0.0, "at"), (1.0, "above")]:
                    val = t + delta
                    sc_id = f"sc_bv_{_slug(proc.id)}_{_slug(var)}_{int(t)}_{tag}"
                    tests.append(
                        TestCase(
                            id=sc_id,
                            description=(
                                f"Boundary: {var} = {val} ({tag} threshold {t})"
                                f" in '{proc.name}'"
                            ),
                            origin=TestOrigin.BOUNDARY,
                            process_id=proc.id,
                            scenario=Scenario(
                                id=sc_id,
                                description=f"{var}={val} ({tag} {t})",
                                process_id=proc.id,
                                facts={var: val},
                            ),
                            tags=[f"var:{var}", f"threshold:{t}", f"delta:{tag}"],
                        )
                    )
    return tests


def _first_terminal_path(
    proc,
    step_map: dict,
    transition_map: dict[str, list[str]],
) -> list[str]:
    """Walk straight-line transitions to find the shortest terminal path."""
    visited: set[str] = set()
    path: list[str] = []
    current = proc.steps[0].id if proc.steps else None
    while current and current not in visited:
        visited.add(current)
        path.append(current)
        step = step_map.get(current)
        if step and step.kind == StepKind.TERMINAL:
            break
        nexts = transition_map.get(current, [])
        current = nexts[0] if nexts else None
    return path


def generate_path_tests(ir: SopIR) -> list[TestCase]:
    """Generate one happy-path test per process (walks straight-line transitions)."""
    tests: list[TestCase] = []
    for proc in ir.processes:
        if not proc.steps:
            continue
        transition_map: dict[str, list[str]] = {}
        for t in proc.transitions:
            transition_map.setdefault(t.from_id, []).append(t.to_id)

        sc_id = f"sc_path_{_slug(proc.id)}"
        tests.append(
            TestCase(
                id=sc_id,
                description=f"Happy-path test for process '{proc.name}'",
                origin=TestOrigin.PATH,
                process_id=proc.id,
                scenario=Scenario(
                    id=sc_id,
                    description=f"Happy path: {proc.name}",
                    process_id=proc.id,
                    facts={},
                ),
                expected_outcome=TraceOutcome.COMPLETED
                if any(s.kind == StepKind.TERMINAL for s in proc.steps)
                else None,
                tags=["path:happy"],
            )
        )
    return tests
