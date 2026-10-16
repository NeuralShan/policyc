"""TM: Temporal / SLA checks.

TM001  "shall/must" step with no SLA defined
TM003  vague time expression (SLA.vague = True or action mentions vague time words)
"""

from __future__ import annotations

import re

from app.analyze.registry import register
from app.schemas.finding import CheckTier, Diagnostic, Severity
from app.schemas.graph import LinkedIR
from app.schemas.ir_sop import ModalVerb, SopIR, StepKind

_VAGUE_TIME_RE = re.compile(
    r"\b(promptly|as\s+soon\s+as\s+possible|asap|timely|quickly|without\s+delay"
    r"|in\s+a\s+timely\s+manner|at\s+your\s+earliest\s+convenience|shortly)\b",
    re.IGNORECASE,
)


@register("TM", "Temporal / SLA checks")
def temporal_checks(ir: SopIR, _linked: LinkedIR | None) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    for proc in ir.processes:
        for step in proc.steps:
            if step.kind == StepKind.TERMINAL:
                continue

            is_obligatory = step.modal in (ModalVerb.SHALL, ModalVerb.MUST)

            # TM003 — vague SLA
            if step.sla and step.sla.vague:
                diags.append(
                    Diagnostic(
                        code="TM003",
                        severity=Severity.WARNING,
                        message=(
                            f"Step '{step.id}' ('{step.action}') has a vague SLA: "
                            f"'{step.sla.vague_text or 'unspecified'}'"
                        ),
                        process_id=proc.id,
                        step_id=step.id,
                        source_spans=step.source_spans,
                        evidence={"vague_text": step.sla.vague_text},
                        check_tier=CheckTier.DETERMINISTIC,
                    )
                )
            elif _VAGUE_TIME_RE.search(step.action):
                diags.append(
                    Diagnostic(
                        code="TM003",
                        severity=Severity.WARNING,
                        message=(
                            f"Step '{step.id}' uses a vague time expression in its "
                            f"action: '{step.action}'"
                        ),
                        process_id=proc.id,
                        step_id=step.id,
                        source_spans=step.source_spans,
                        check_tier=CheckTier.DETERMINISTIC,
                    )
                )

            # TM001 — obligatory step with no SLA
            if is_obligatory and step.sla is None:
                diags.append(
                    Diagnostic(
                        code="TM001",
                        severity=Severity.INFO,
                        message=(
                            f"Step '{step.id}' ('{step.action}') is a "
                            f"'{step.modal}' obligation with no SLA defined"
                        ),
                        process_id=proc.id,
                        step_id=step.id,
                        source_spans=step.source_spans,
                        check_tier=CheckTier.DETERMINISTIC,
                    )
                )

    return diags
