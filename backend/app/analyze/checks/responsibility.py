"""RS: Responsibility checks.

RS001  step with no owner (actor_role_id is None and actor_raw is None/blank)
RS002  vague owner ("the team", "someone", "staff", "relevant party")
"""

from __future__ import annotations

import re

from app.analyze.registry import register
from app.schemas.finding import CheckTier, Diagnostic, Severity
from app.schemas.graph import LinkedIR
from app.schemas.ir_sop import ModalVerb, SopIR, StepKind

_VAGUE_ACTOR_RE = re.compile(
    r"\b(the\s+team|staff|someone|anyone|everybody|relevant\s+party|appropriate\s+person"
    r"|responsible\s+party|stakeholder|department|management)\b",
    re.IGNORECASE,
)


@register("RS", "Responsibility checks")
def responsibility_checks(ir: SopIR, _linked: LinkedIR | None) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    for proc in ir.processes:
        for step in proc.steps:
            if step.kind == StepKind.TERMINAL or step.off_flow:
                continue

            has_role = bool(step.actor_role_id)
            raw = (step.actor_raw or "").strip()

            # RS001 — no owner at all
            if not has_role and not raw:
                # Only flag "shall/must" steps (strong obligation)
                if step.modal in (ModalVerb.SHALL, ModalVerb.MUST):
                    diags.append(
                        Diagnostic(
                            code="RS001",
                            severity=Severity.ERROR,
                            message=(
                                f"Step '{step.id}' ('{step.action}') has no actor — "
                                "a 'shall/must' step must have an owner"
                            ),
                            process_id=proc.id,
                            step_id=step.id,
                            source_spans=step.source_spans,
                            check_tier=CheckTier.DETERMINISTIC,
                        )
                    )
                else:
                    diags.append(
                        Diagnostic(
                            code="RS001",
                            severity=Severity.WARNING,
                            message=f"Step '{step.id}' ('{step.action}') has no assigned actor",
                            process_id=proc.id,
                            step_id=step.id,
                            source_spans=step.source_spans,
                            check_tier=CheckTier.DETERMINISTIC,
                        )
                    )
                continue

            # RS002 — vague actor
            check_text = raw if raw else ""
            if not has_role and _VAGUE_ACTOR_RE.search(check_text):
                diags.append(
                    Diagnostic(
                        code="RS002",
                        severity=Severity.WARNING,
                        message=(
                            f"Step '{step.id}' ('{step.action}') has a vague actor: "
                            f"'{check_text}'"
                        ),
                        process_id=proc.id,
                        step_id=step.id,
                        source_spans=step.source_spans,
                        evidence={"actor_raw": check_text},
                        check_tier=CheckTier.DETERMINISTIC,
                    )
                )

    return diags
