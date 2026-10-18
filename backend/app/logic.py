"""Shared condition logic: operator normalisation and the Z3 translation used by analysis and testgen.

The extraction prompt asks the model for ``lte`` / ``gte`` while the original evaluator only knew
``le`` / ``ge``.  Every "at or below" / "at or above" condition therefore evaluated to *unknown*.
All code now goes through :func:`normalize_op` so any spelling resolves to one canonical operator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import z3

from app.schemas.ir_sop import (
    AlwaysCondition,
    CompareCondition,
    ConditionExpr,
    LogicalCondition,
    UnknownCondition,
    VagueCondition,
    ValueType,
)

OTHER_VALUE = "other"  # stands for "any value not named in the document"

_OP_ALIASES: dict[str, str] = {
    "eq": "eq", "==": "eq", "=": "eq", "equals": "eq", "equal": "eq", "is": "eq",
    "ne": "ne", "!=": "ne", "<>": "ne", "neq": "ne", "not_equal": "ne", "not_equals": "ne",
    "lt": "lt", "<": "lt", "less_than": "lt", "below": "lt", "under": "lt",
    "le": "le", "lte": "le", "<=": "le", "≤": "le", "at_most": "le", "less_or_equal": "le",
    "gt": "gt", ">": "gt", "greater_than": "gt", "above": "gt", "over": "gt",
    "ge": "ge", "gte": "ge", ">=": "ge", "≥": "ge", "at_least": "ge", "greater_or_equal": "ge",
    "in": "in", "not_in": "not_in", "nin": "not_in",
}

NUMERIC_TYPES = (ValueType.NUMBER, ValueType.MONEY, ValueType.DURATION)
TEXT_TYPES = (ValueType.ENUM, ValueType.DATE)

_ARITH = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
}

OP_SYMBOL = {"eq": "=", "ne": "≠", "lt": "<", "le": "≤", "gt": ">", "ge": "≥"}


def normalize_op(op: str | None) -> str | None:
    """Return the canonical operator (eq/ne/lt/le/gt/ge/in/not_in) or None if unrecognised."""
    if op is None:
        return None
    key = op.strip().lower().replace(" ", "_")
    return _OP_ALIASES.get(key)


def norm_text(value: Any) -> str:
    """Case/punctuation-insensitive form used to compare enum-like facts."""
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def describe_condition(expr: ConditionExpr) -> str:
    """Short human-readable rendering, e.g. ``amount < 10,000`` or ``requester_role = manager``."""
    if isinstance(expr, AlwaysCondition):
        return "otherwise"
    if isinstance(expr, VagueCondition):
        return f"“{expr.text}”"
    if isinstance(expr, UnknownCondition):
        return expr.raw_text[:60] or "unknown condition"
    if isinstance(expr, CompareCondition):
        op = normalize_op(expr.op) or expr.op
        rv = expr.right
        if rv.value_type in NUMERIC_TYPES and rv.number is not None:
            num = f"{rv.number:,.0f}" if float(rv.number).is_integer() else f"{rv.number:g}"
            unit = f" {rv.currency}" if rv.currency else ""
            right = f"{num}{unit}"
        elif rv.value_type == ValueType.BOOL:
            right = "true" if rv.bool_value else "false"
        else:
            right = rv.text or "?"
        return f"{expr.left} {OP_SYMBOL.get(op, op)} {right}"
    if isinstance(expr, LogicalCondition):
        parts = [describe_condition(o) for o in expr.operands]
        if expr.logical_op == "not" and parts:
            return f"not ({parts[0]})"
        return f" {expr.logical_op} ".join(f"({p})" if " " in p else p for p in parts)
    return "?"


# ---------------------------------------------------------------------------
# Z3 translation
# ---------------------------------------------------------------------------


@dataclass
class ConstraintBuilder:
    """Translate ConditionExpr trees into Z3 formulas over typed variables.

    Numeric variables are Reals, booleans are Bools and enum-like variables are Ints indexing the
    literal values named in the document plus one ``__other__`` value (so "any other role" exists).
    """

    kinds: dict[str, str] = field(default_factory=dict)  # var -> "num" | "bool" | "enum"
    z3_vars: dict[str, Any] = field(default_factory=dict)
    enum_values: dict[str, list[str]] = field(default_factory=dict)
    _poisoned: set[str] = field(default_factory=set)

    # -- discovery -------------------------------------------------------
    def scan(self, expr: ConditionExpr) -> None:
        """Pre-register every variable so enum domains are complete before translating."""
        if isinstance(expr, CompareCondition):
            kind = self._kind_of(expr)
            if kind is None:
                return
            if expr.left in self.kinds and self.kinds[expr.left] != kind:
                self._poisoned.add(expr.left)
                return
            self.kinds[expr.left] = kind
            if kind == "enum":
                vals = self.enum_values.setdefault(expr.left, [OTHER_VALUE])
                lit = norm_text(expr.right.text or "")
                if lit and lit not in vals:
                    vals.append(lit)
        elif isinstance(expr, LogicalCondition):
            for sub in expr.operands:
                self.scan(sub)

    @staticmethod
    def _kind_of(expr: CompareCondition) -> str | None:
        vt = expr.right.value_type
        if vt in NUMERIC_TYPES:
            return "num"
        if vt == ValueType.BOOL:
            return "bool"
        if vt in TEXT_TYPES:
            return "enum"
        return None

    def _var(self, name: str) -> Any:
        if name not in self.z3_vars:
            kind = self.kinds[name]
            if kind == "num":
                self.z3_vars[name] = z3.Real(name)
            elif kind == "bool":
                self.z3_vars[name] = z3.Bool(name)
            else:
                self.z3_vars[name] = z3.Int(name)
        return self.z3_vars[name]

    # -- translation -----------------------------------------------------
    def formula(self, expr: ConditionExpr) -> z3.BoolRef | None:
        if isinstance(expr, AlwaysCondition):
            return z3.BoolVal(True)
        if isinstance(expr, (VagueCondition, UnknownCondition)):
            return None
        if isinstance(expr, CompareCondition):
            return self._compare(expr)
        if isinstance(expr, LogicalCondition):
            subs = [self.formula(o) for o in expr.operands]
            if not subs or any(s is None for s in subs):
                return None
            if expr.logical_op == "and":
                return z3.And(*subs)
            if expr.logical_op == "or":
                return z3.Or(*subs)
            if expr.logical_op == "not" and len(subs) == 1:
                return z3.Not(subs[0])
        return None

    def _compare(self, expr: CompareCondition) -> z3.BoolRef | None:
        op = normalize_op(expr.op)
        if op is None or expr.left in self._poisoned:
            return None
        if expr.left not in self.kinds:
            self.scan(expr)
        kind = self.kinds.get(expr.left)
        if kind is None or kind != self._kind_of(expr):
            return None
        var = self._var(expr.left)
        rv = expr.right
        if kind == "num":
            if rv.number is None or op not in _ARITH:
                return None
            return _ARITH[op](var, z3.RealVal(rv.number))
        if kind == "bool":
            if rv.bool_value is None or op not in ("eq", "ne"):
                return None
            val = z3.BoolVal(rv.bool_value)
            return var == val if op == "eq" else var != val
        # enum
        if op not in ("eq", "ne") or not rv.text:
            return None
        idx = self.enum_values[expr.left].index(norm_text(rv.text))
        return var == idx if op == "eq" else var != idx

    # -- domains and models ------------------------------------------------
    def domain(self) -> list[z3.BoolRef]:
        out: list[z3.BoolRef] = []
        for name, kind in self.kinds.items():
            if kind == "enum" and name in self.z3_vars:
                n = len(self.enum_values[name])
                out.append(z3.And(self.z3_vars[name] >= 0, self.z3_vars[name] < n))
        return out

    def facts(self, model: z3.ModelRef) -> dict[str, Any]:
        """Concrete facts for every variable the formula mentioned."""
        facts: dict[str, Any] = {}
        for name, var in self.z3_vars.items():
            val = model.eval(var, model_completion=True)
            kind = self.kinds[name]
            if kind == "num":
                facts[name] = _real_to_float(val)
            elif kind == "bool":
                facts[name] = z3.is_true(val)
            else:
                facts[name] = self.enum_values[name][val.as_long()]
        return facts

    def baseline(self) -> dict[str, Any]:
        """A neutral value per variable: 0, true, or the 'any other value' enum member."""
        base: dict[str, Any] = {}
        for name, kind in self.kinds.items():
            if name in self._poisoned:
                continue
            base[name] = 0.0 if kind == "num" else True if kind == "bool" else OTHER_VALUE
        return base


def _real_to_float(val: Any) -> float:
    try:
        return float(val.numerator_as_long()) / float(val.denominator_as_long())
    except (AttributeError, ZeroDivisionError):
        try:
            return float(val.as_decimal(6).rstrip("?"))
        except (AttributeError, ValueError):
            return 0.0


def display_value(value: Any) -> str:
    if value == OTHER_VALUE:
        return "(any other value)"
    if isinstance(value, float) and value.is_integer():
        return f"{value:,.0f}"
    return str(value)


def same_outcome(proc: Any, a: str, b: str) -> bool:
    """Two targets are interchangeable when they are the same node, or steps of the same kind
    performed by the same role (e.g. two clauses that both send a claim to the Finance Head)."""
    if a == b:
        return True
    if proc is None:
        return False
    sa, sb = proc.step(a), proc.step(b)
    return bool(
        sa and sb and sa.actor_role_id and sa.actor_role_id == sb.actor_role_id and sa.kind == sb.kind
    )
