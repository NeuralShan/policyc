"""Condition DSL helpers for Layer 2.

The DSL represents conditions extracted from SOP text as structured objects (see
``ir_sop.ConditionExpr``).  Helper functions here parse the LLM's structured JSON output and
validate that conditions are internally consistent.

A full Lark grammar (for text → AST) is added in Layer 4 when Z3 compilation is needed.
"""

import re

from app.schemas.ir_sop import (
    AlwaysCondition,
    ConditionExpr,
    ConditionKind,
    TypedValue,
    UnknownCondition,
    VagueCondition,
    ValueType,
)

# Phrases that signal a vague temporal / quantity expression.
_VAGUE_PATTERNS = [
    r"\bpromptly\b",
    r"\bsoon\b",
    r"\bas needed\b",
    r"\bperiodically\b",
    r"\bin a timely (manner|fashion)\b",
    r"\bat the earliest\b",
    r"\bwhenever possible\b",
    r"\bsatisfactory\b",
    r"\bappropriate\b",
    r"\breasonable\b",
    r"\bsufficient\b",
]

_VAGUE_RE = re.compile("|".join(_VAGUE_PATTERNS), re.IGNORECASE)

VALID_OPS = {"gt", "gte", "lt", "lte", "eq", "ne", "in", "not_in"}

DURATION_UNIT_MAP: dict[str, str] = {
    "hour": "hours",
    "hours": "hours",
    "hr": "hours",
    "hrs": "hours",
    "day": "days",
    "days": "days",
    "business day": "business_days",
    "business days": "business_days",
    "bd": "business_days",
    "bds": "business_days",
    "calendar day": "calendar_days",
    "calendar days": "calendar_days",
    "week": "weeks",
    "weeks": "weeks",
}


def is_vague(text: str) -> bool:
    """Return True if *text* contains a vague temporal/quantity phrase."""
    return bool(_VAGUE_RE.search(text))


def vague(text: str) -> VagueCondition:
    return VagueCondition(kind=ConditionKind.VAGUE, text=text)


def always() -> AlwaysCondition:
    return AlwaysCondition(kind=ConditionKind.ALWAYS)


def unknown(raw: str) -> UnknownCondition:
    return UnknownCondition(kind=ConditionKind.UNKNOWN, raw_text=raw)


def validate_condition(expr: ConditionExpr) -> list[str]:
    """Return a list of validation error strings (empty = valid)."""
    errors: list[str] = []
    if expr.kind == ConditionKind.COMPARE:
        if expr.op not in VALID_OPS:
            errors.append(f"unknown operator {expr.op!r}")
        if expr.right is None:
            errors.append("compare condition has no right-hand value")
        elif expr.right.value_type == ValueType.MONEY and expr.right.currency is None:
            errors.append("money value missing currency")
        elif expr.right.value_type == ValueType.DURATION and expr.right.duration_unit is None:
            errors.append("duration value missing unit")
    elif expr.kind == ConditionKind.LOGICAL:
        if not expr.operands:
            errors.append("logical condition has no operands")
        if expr.logical_op == "not" and len(expr.operands) != 1:
            errors.append("'not' requires exactly one operand")
        for sub in expr.operands:
            errors.extend(validate_condition(sub))
    return errors


def money(value: float, currency: str) -> TypedValue:
    return TypedValue(value_type=ValueType.MONEY, number=value, currency=currency)


def duration(value: float, unit: str) -> TypedValue:
    normalised = DURATION_UNIT_MAP.get(unit.lower(), unit)
    return TypedValue(value_type=ValueType.DURATION, number=value, duration_unit=normalised)


def condition_summary(expr: ConditionExpr) -> str:
    """Short human-readable string for debugging / UI."""
    if expr.kind == ConditionKind.ALWAYS:
        return "always"
    if expr.kind == ConditionKind.VAGUE:
        return f"VAGUE({expr.text!r})"
    if expr.kind == ConditionKind.UNKNOWN:
        return f"UNKNOWN({expr.raw_text!r})"
    if expr.kind == ConditionKind.COMPARE:
        right = expr.right
        if right is None:
            rhs = "?"
        elif right.value_type == ValueType.MONEY:
            rhs = f"{right.currency or ''}{right.number}"
        elif right.value_type == ValueType.DURATION:
            rhs = f"{right.number} {right.duration_unit}"
        elif right.number is not None:
            rhs = str(right.number)
        else:
            rhs = str(right.text or right.bool_value)
        return f"{expr.left} {expr.op} {rhs}"
    if expr.kind == ConditionKind.LOGICAL:
        if expr.logical_op == "not":
            return f"NOT {condition_summary(expr.operands[0])}"
        sep = f" {expr.logical_op.upper()} "
        return f"({sep.join(condition_summary(o) for o in expr.operands)})"
    return repr(expr)
