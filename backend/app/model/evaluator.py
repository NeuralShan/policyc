"""Condition evaluator: ConditionExpr × facts → EvalResult.

EvalResult is a four-valued logic:
  "true"    — the condition holds
  "false"   — the condition does not hold
  "vague"   — the condition uses natural-language vagueness (VagueCondition)
  "unknown" — a variable is absent from facts, or the condition could not be parsed
"""

from __future__ import annotations

from typing import Any, Literal

from app.logic import norm_text, normalize_op
from app.schemas.ir_sop import (
    AlwaysCondition,
    CompareCondition,
    ConditionExpr,
    LogicalCondition,
    UnknownCondition,
    VagueCondition,
    ValueType,
)

EvalResult = Literal["true", "false", "vague", "unknown"]

_OPS: dict[str, Any] = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
}


def _r(val: bool) -> EvalResult:
    return "true" if val else "false"


def eval_condition(expr: ConditionExpr, facts: dict[str, Any]) -> EvalResult:
    """Evaluate a ConditionExpr against a facts dict."""
    if isinstance(expr, AlwaysCondition):
        return "true"
    if isinstance(expr, VagueCondition):
        return "vague"
    if isinstance(expr, UnknownCondition):
        return "unknown"
    if isinstance(expr, CompareCondition):
        return _eval_compare(expr, facts)
    if isinstance(expr, LogicalCondition):
        return _eval_logical(expr, facts)
    return "unknown"


def _eval_compare(expr: CompareCondition, facts: dict[str, Any]) -> EvalResult:
    lhs = facts.get(expr.left)
    if lhs is None:
        return "unknown"

    rv = expr.right
    op = normalize_op(expr.op)
    op_fn = _OPS.get(op) if op else None
    if op_fn is None:
        return "unknown"

    try:
        if rv.value_type in (ValueType.NUMBER, ValueType.MONEY, ValueType.DURATION):
            if rv.number is None:
                return "unknown"
            return _r(op_fn(float(lhs), rv.number))

        if rv.value_type == ValueType.BOOL:
            if rv.bool_value is None:
                return "unknown"
            return _r(op_fn(bool(lhs), rv.bool_value))

        if rv.value_type in (ValueType.ENUM, ValueType.DATE):
            if rv.text is None:
                return "unknown"
            if op == "eq":
                return _r(norm_text(lhs) == norm_text(rv.text))
            if op == "ne":
                return _r(norm_text(lhs) != norm_text(rv.text))
            return "unknown"
    except (TypeError, ValueError):
        return "unknown"

    return "unknown"


def _eval_logical(expr: LogicalCondition, facts: dict[str, Any]) -> EvalResult:
    sub = [eval_condition(op, facts) for op in expr.operands]

    if expr.logical_op == "and":
        if "false" in sub:
            return "false"
        if any(r in ("vague", "unknown") for r in sub):
            return "vague" if "vague" in sub else "unknown"
        return "true"

    if expr.logical_op == "or":
        if "true" in sub:
            return "true"
        if any(r in ("vague", "unknown") for r in sub):
            return "vague" if "vague" in sub else "unknown"
        return "false"

    if expr.logical_op == "not" and len(sub) == 1:
        r = sub[0]
        if r == "true":
            return "false"
        if r == "false":
            return "true"
        return r  # vague/unknown propagates

    return "unknown"
