"""ST004 / ST005 — Decision branch checks using Z3.

ST004  decision missing a branch (branches < 2, or Z3 finds un-covered input)
ST005  overlapping branches (Z3 finds an input satisfying two branches simultaneously)

Z3 is used only when all branch conditions are CompareConditions on numeric types.
VagueCondition/UnknownCondition blocks Z3 and falls back to a count-only check.
"""

from __future__ import annotations

import logging

import z3

from app.analyze.registry import register
from app.schemas.finding import CheckTier, Diagnostic, Severity
from app.schemas.graph import LinkedIR
from app.schemas.ir_sop import (
    AlwaysCondition,
    CompareCondition,
    ConditionExpr,
    Decision,
    LogicalCondition,
    SopIR,
    UnknownCondition,
    VagueCondition,
    ValueType,
)

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
    """Convert a ConditionExpr to a Z3 formula. Returns None when un-translatable."""
    if isinstance(expr, AlwaysCondition):
        return z3.BoolVal(True)
    if isinstance(expr, (VagueCondition, UnknownCondition)):
        return None  # can't model
    if isinstance(expr, CompareCondition):
        rv = expr.right
        if rv.value_type not in (ValueType.NUMBER, ValueType.MONEY, ValueType.DURATION):
            return None
        num = rv.number
        if num is None:
            return None
        if expr.left not in vars_cache:
            vars_cache[expr.left] = z3.Real(expr.left)
        lhs = vars_cache[expr.left]
        op_fn = _OP_MAP.get(expr.op)
        if op_fn is None:
            return None
        return op_fn(lhs, num)
    if isinstance(expr, LogicalCondition):
        sub_formulas = [_to_z3(op, vars_cache) for op in expr.operands]
        if any(f is None for f in sub_formulas):
            return None
        if expr.logical_op == "and":
            return z3.And(*sub_formulas)
        if expr.logical_op == "or":
            return z3.Or(*sub_formulas)
        if expr.logical_op == "not" and len(sub_formulas) == 1:
            return z3.Not(sub_formulas[0])
    return None


def _check_decision(dec: Decision, proc_id: str) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    # ST004 — fewer than 2 branches
    if len(dec.branches) < 2:
        diags.append(
            Diagnostic(
                code="ST004",
                severity=Severity.ERROR,
                message=(
                    f"Decision '{dec.id}' ('{dec.question}') has only "
                    f"{len(dec.branches)} branch(es) — at least 2 required"
                ),
                process_id=proc_id,
                decision_id=dec.id,
                source_spans=dec.source_spans,
                check_tier=CheckTier.DETERMINISTIC,
            )
        )
        return diags  # no point running Z3 with <2 branches

    # Attempt Z3 translation
    vars_cache: dict[str, z3.ArithRef] = {}
    formulas: list[z3.BoolRef | None] = [
        _to_z3(b.condition, vars_cache) for b in dec.branches
    ]

    if any(f is None for f in formulas):
        # At least one branch can't be modelled — skip Z3 but log
        log.debug(
            "decision %s: skipping Z3 (un-translatable condition in one or more branches)",
            dec.id,
        )
        return diags

    typed_formulas: list[z3.BoolRef] = formulas  # type: ignore[assignment]

    # ST005 — overlapping branches: ∃ input satisfying bi ∧ bj (i ≠ j)
    for i in range(len(typed_formulas)):
        for j in range(i + 1, len(typed_formulas)):
            s = z3.Solver()
            s.add(z3.And(typed_formulas[i], typed_formulas[j]))
            if s.check() == z3.sat:
                model = s.model()
                example = {str(d): str(model[d]) for d in model.decls()}
                diags.append(
                    Diagnostic(
                        code="ST005",
                        severity=Severity.ERROR,
                        message=(
                            f"Decision '{dec.id}': branch '{dec.branches[i].label}' and "
                            f"branch '{dec.branches[j].label}' overlap "
                            f"(both satisfiable simultaneously)"
                        ),
                        process_id=proc_id,
                        decision_id=dec.id,
                        source_spans=dec.source_spans,
                        evidence={"counterexample": example},
                        check_tier=CheckTier.DETERMINISTIC,
                    )
                )

    # ST004 — non-exhaustive: ¬(b1 ∨ b2 ∨ … ∨ bn) is satisfiable
    s = z3.Solver()
    s.add(z3.Not(z3.Or(*typed_formulas)))
    if s.check() == z3.sat:
        model = s.model()
        example = {str(d): str(model[d]) for d in model.decls()}
        diags.append(
            Diagnostic(
                code="ST004",
                severity=Severity.ERROR,
                message=(
                    f"Decision '{dec.id}' ('{dec.question}') is non-exhaustive: "
                    "there exist inputs not covered by any branch"
                ),
                process_id=proc_id,
                decision_id=dec.id,
                source_spans=dec.source_spans,
                evidence={"counterexample": example},
                check_tier=CheckTier.DETERMINISTIC,
            )
        )

    return diags


@register("ST", "Decision branch checks (Z3)")
def decision_checks(ir: SopIR, _linked: LinkedIR | None) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for proc in ir.processes:
        for dec in proc.decisions:
            diags.extend(_check_decision(dec, proc.id))
    return diags
