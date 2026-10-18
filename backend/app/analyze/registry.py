"""Check plugin registry.

A ``Check`` is a plain function that inspects a SopIR (and optionally a LinkedIR)
and returns a list of Diagnostics.  All checks in CHECKS are run by the Analyzer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.finding import Diagnostic
    from app.schemas.graph import LinkedIR
    from app.schemas.ir_sop import SopIR

CheckFn = Callable[["SopIR", "LinkedIR | None"], list["Diagnostic"]]


@dataclass
class Check:
    code_prefix: str  # e.g. "ST", "RS", "DF", "TM", "LG"
    label: str
    fn: CheckFn
    tier: str = "deterministic"


_REGISTRY: list[Check] = []


def register(code_prefix: str, label: str, tier: str = "deterministic"):
    """Decorator: register a check function."""
    def decorator(fn: CheckFn) -> CheckFn:
        _REGISTRY.append(Check(code_prefix=code_prefix, label=label, fn=fn, tier=tier))
        return fn
    return decorator


def all_checks() -> list[Check]:
    # Import side-effectfully to trigger @register decorators
    from app.analyze.checks import (  # noqa: F401
        rules,  # first: later modules with the same prefix stay the 'primary' check
        dataflow,
        decisions_z3,
        language,
        responsibility,
        structural,
        temporal,
    )
    return list(_REGISTRY)
