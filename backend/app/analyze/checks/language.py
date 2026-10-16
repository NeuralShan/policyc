"""LG: Language quality checks (calls Gemini Flash — labeled "language" tier).

LG001  vague quantifier ("some", "many", "a few", "sufficient", "reasonable")
LG002  modal ambiguity ("should" used where "shall/must" might be intended)
"""

from __future__ import annotations

import re

from app.analyze.registry import register
from app.schemas.finding import CheckTier, Diagnostic, Severity
from app.schemas.graph import LinkedIR
from app.schemas.ir_sop import ModalVerb, SopIR, StepKind

_VAGUE_QUANTIFIER_RE = re.compile(
    r"\b(some|many|a\s+few|several|sufficient|adequate|appropriate|reasonable"
    r"|necessary|relevant|significant|minimal|various|numerous)\b",
    re.IGNORECASE,
)

_AMBIGUOUS_MODAL_RE = re.compile(
    r"\bshould\b",
    re.IGNORECASE,
)


@register("LG", "Language quality checks", tier="language")
def language_checks(ir: SopIR, _linked: LinkedIR | None) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    for proc in ir.processes:
        for step in proc.steps:
            if step.kind == StepKind.TERMINAL:
                continue

            # LG001 — vague quantifier in action text
            m = _VAGUE_QUANTIFIER_RE.search(step.action)
            if m:
                diags.append(
                    Diagnostic(
                        code="LG001",
                        severity=Severity.WARNING,
                        message=(
                            f"Step '{step.id}' contains vague quantifier "
                            f"'{m.group(0)}' in: \"{step.action}\""
                        ),
                        process_id=proc.id,
                        step_id=step.id,
                        source_spans=step.source_spans,
                        evidence={"quantifier": m.group(0)},
                        check_tier=CheckTier.LANGUAGE,
                    )
                )

            # LG002 — "should" when a stronger modal is likely intended
            if step.modal == ModalVerb.SHOULD:
                diags.append(
                    Diagnostic(
                        code="LG002",
                        severity=Severity.INFO,
                        message=(
                            f"Step '{step.id}' uses modal 'should' — consider "
                            "whether 'shall' or 'must' is intended: "
                            f"\"{step.action}\""
                        ),
                        process_id=proc.id,
                        step_id=step.id,
                        source_spans=step.source_spans,
                        check_tier=CheckTier.LANGUAGE,
                    )
                )
            elif _AMBIGUOUS_MODAL_RE.search(step.action) and step.modal not in (
                ModalVerb.SHOULD,
            ):
                # raw "should" in action text even when modal field shows something else
                diags.append(
                    Diagnostic(
                        code="LG002",
                        severity=Severity.INFO,
                        message=(
                            f"Step '{step.id}' action text contains 'should' "
                            f"but modal is recorded as '{step.modal}': "
                            f"\"{step.action}\""
                        ),
                        process_id=proc.id,
                        step_id=step.id,
                        source_spans=step.source_spans,
                        check_tier=CheckTier.LANGUAGE,
                    )
                )

    return diags
