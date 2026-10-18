"""6.1 Deterministic test generation: boundary values and path coverage.

No LLM calls. Extracts numeric thresholds from decision conditions, then
produces three scenarios per threshold (value below, at, and above).
Also generates one happy-path scenario per process.
"""

from __future__ import annotations

import itertools
import random
import re

from app.logic import ConstraintBuilder, display_value
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


def _process_conditions(proc) -> list[ConditionExpr]:
    conds: list[ConditionExpr] = []
    for dec in proc.decisions:
        conds.extend(b.condition for b in dec.branches)
    conds.extend(t.condition for t in proc.transitions)
    return conds


def combination_domain(proc) -> tuple[ConstraintBuilder, dict[str, list]]:
    """Per-variable test values: thresholds ±1 for numbers, every enum value, both booleans."""
    builder = ConstraintBuilder()
    conds = _process_conditions(proc)
    for c in conds:
        builder.scan(c)
    thresholds: dict[str, set[float]] = {}
    for c in conds:
        _collect_thresholds(c, thresholds)
    domain: dict[str, list] = {}
    for var, kind in sorted(builder.kinds.items()):
        if kind == "num":
            vals = {0.0}
            for t in thresholds.get(var, set()):
                vals.update({t - 1, t, t + 1})
            domain[var] = sorted(v for v in vals if v >= 0)
        elif kind == "bool":
            domain[var] = [True, False]
        else:
            domain[var] = list(builder.enum_values.get(var, ["other"]))
    return builder, domain


def generate_combination_tests(ir: SopIR, cap: int = 150) -> list[TestCase]:
    """Complete assignments over every variable (boundary values × enum values × booleans).

    These are the scenarios that expose gaps and conflicts at run time: a claim of exactly 10,000, a
    manager's claim just under the threshold, the Finance Head's own claim.
    """
    tests: list[TestCase] = []
    for proc in ir.processes:
        builder, domain = combination_domain(proc)
        if not domain:
            continue
        names = list(domain)
        size = 1
        for v in domain.values():
            size *= len(v)
        if size <= cap:
            combos = list(itertools.product(*(domain[n] for n in names)))
        else:
            rng = random.Random(42)
            base = [domain[n][0] for n in names]
            combos_set = {tuple(base)}
            for i, n in enumerate(names):  # vary one variable at a time around the baseline
                for v in domain[n]:
                    c = list(base)
                    c[i] = v
                    combos_set.add(tuple(c))
            while len(combos_set) < cap:
                combos_set.add(tuple(rng.choice(domain[n]) for n in names))
            combos = sorted(combos_set, key=str)
        for i, combo in enumerate(combos):
            facts = dict(zip(names, combo, strict=True))
            sc_id = f"sc_combo_{_slug(proc.id)}_{i:03d}"
            label = ", ".join(f"{k}={display_value(v)}" for k, v in facts.items())
            tests.append(
                TestCase(
                    id=sc_id,
                    description=f"Combination: {label}",
                    origin=TestOrigin.BOUNDARY,
                    process_id=proc.id,
                    scenario=Scenario(
                        id=sc_id,
                        description=label,
                        process_id=proc.id,
                        facts=facts,
                    ),
                    tags=["combo", *[f"var:{n}" for n in names]],
                )
            )
    return tests
