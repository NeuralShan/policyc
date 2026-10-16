"""6.2 Solver-based test generation: Z3 witnesses for decision branches.

For each branch in each decision, find a set of facts that satisfies that branch's
condition (and, when possible, only that branch).  Skips branches whose conditions
are vague or unknown.
"""

from __future__ import annotations

import logging
import re

import z3

from app.schemas.ir_sop import (
    AlwaysCondition,
    CompareCondition,
    ConditionExpr,
    LogicalCondition,
    SopIR,
    UnknownCondition,
    VagueCondition,
    ValueType,
)
from app.schemas.testcase import TestCase, TestOrigin
from app.schemas.trace import Scenario

log = logging.getLogger(__name__)

_OP_MAP = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
}


def _to_z3(
    expr: ConditionExpr,
    vars_cache: dict[str, z3.ArithRef],
) -> z3.BoolRef | None:
    if isinstance(expr, AlwaysCondition):
        return z3.BoolVal(True)
    if isinstance(expr, (VagueCondition, UnknownCondition)):
        return None
    if isinstance(expr, CompareCondition):
        rv = expr.right
        if rv.value_type not in (ValueType.NUMBER, ValueType.MONEY, ValueType.DURATION):
            return None
        if rv.number is None:
            return None
        if expr.left not in vars_cache:
            vars_cache[expr.left] = z3.Real(expr.left)
        op_fn = _OP_MAP.get(expr.op)
        if op_fn is None:
            return None
        return op_fn(vars_cache[expr.left], rv.number)
    if isinstance(expr, LogicalCondition):
        sub = [_to_z3(op, vars_cache) for op in expr.operands]
        if any(f is None for f in sub):
            return None
        typed: list[z3.BoolRef] = sub  # type: ignore[assignment]
        if expr.logical_op == "and":
            return z3.And(*typed)
        if expr.logical_op == "or":
            return z3.Or(*typed)
        if expr.logical_op == "not" and len(typed) == 1:
            return z3.Not(typed[0])
    return None


def _extract_facts(
    model: z3.ModelRef,
    vars_cache: dict[str, z3.ArithRef],
) -> dict[str, float]:
    facts: dict[str, float] = {}
    for name, z3_var in vars_cache.items():
        val = model[z3_var]
        if val is None:
            continue
        try:
            facts[name] = float(val.numerator_as_long()) / float(val.denominator_as_long())
        except AttributeError:
            import contextlib

            with contextlib.suppress(ValueError, TypeError):
                facts[name] = float(str(val))
    return facts


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", text.lower()).strip("_")


def generate_branch_tests(ir: SopIR) -> list[TestCase]:
    """For each branch in each decision, ask Z3 for a satisfying assignment."""
    tests: list[TestCase] = []

    for proc in ir.processes:
        for dec in proc.decisions:
            for i, branch in enumerate(dec.branches):
                # AlwaysCondition: no variables needed
                if isinstance(branch.condition, AlwaysCondition):
                    sc_id = f"sc_branch_{_slug(dec.id)}_{i}_always"
                    tests.append(
                        TestCase(
                            id=sc_id,
                            description=(
                                f"Branch '{branch.label}' of decision '{dec.question}'"
                                " (always taken)"
                            ),
                            origin=TestOrigin.BRANCH,
                            process_id=proc.id,
                            scenario=Scenario(
                                id=sc_id,
                                description=f"Always-branch: {branch.label}",
                                process_id=proc.id,
                                facts={},
                            ),
                            expected_branch=branch.label,
                            expected_decision_id=dec.id,
                            tags=[f"decision:{dec.id}", f"branch:{_slug(branch.label)}"],
                        )
                    )
                    continue

                vars_cache: dict[str, z3.ArithRef] = {}
                formula = _to_z3(branch.condition, vars_cache)
                if formula is None:
                    log.debug(
                        "solver: skipping branch '%s' of decision '%s' (un-translatable)",
                        branch.label,
                        dec.id,
                    )
                    continue

                solver = z3.Solver()
                solver.add(formula)
                if solver.check() != z3.sat:
                    log.debug(
                        "solver: branch '%s' of decision '%s' is unsatisfiable",
                        branch.label,
                        dec.id,
                    )
                    continue

                facts = _extract_facts(solver.model(), vars_cache)
                sc_id = (
                    f"sc_branch_{_slug(dec.id)}_{i}_{_slug(branch.label)}"
                )
                tests.append(
                    TestCase(
                        id=sc_id,
                        description=(
                            f"Z3 witness for branch '{branch.label}'"
                            f" of decision '{dec.question}'"
                        ),
                        origin=TestOrigin.BRANCH,
                        process_id=proc.id,
                        scenario=Scenario(
                            id=sc_id,
                            description=f"Z3 witness: {branch.label}",
                            process_id=proc.id,
                            facts=facts,
                        ),
                        expected_branch=branch.label,
                        expected_decision_id=dec.id,
                        tags=[f"decision:{dec.id}", f"branch:{_slug(branch.label)}"],
                    )
                )

    return tests
