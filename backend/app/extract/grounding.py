"""Quote grounding: verify that every source_span quote is actually in the DocAST text.

Every Step and Decision in the IR must have at least one SourceSpan whose quote appears verbatim
in DocAST.text.  Anything that fails is flagged (not removed) so the human reviewer can see it.
"""

from app.schemas.docast import DocAST
from app.schemas.ir_sop import ExtractionWarning, Process


def check_grounding(process: Process, ast: DocAST) -> list[ExtractionWarning]:
    """Return warnings for any IR element whose source quote is not found verbatim."""
    warnings: list[ExtractionWarning] = []
    text = ast.text

    for step in process.steps:
        if not step.source_spans:
            warnings.append(
                ExtractionWarning(
                    code="ungrounded_step",
                    message=f"step {step.id} ({step.action!r}) has no source span",
                    step_id=step.id,
                )
            )
            continue
        for span in step.source_spans:
            if span.quote not in text:
                warnings.append(
                    ExtractionWarning(
                        code="ungrounded_step",
                        message=(
                            f"step {step.id}: quote {span.quote!r} not found verbatim in document"
                        ),
                        step_id=step.id,
                    )
                )

    for decision in process.decisions:
        if not decision.source_spans:
            warnings.append(
                ExtractionWarning(
                    code="ungrounded_decision",
                    message=f"decision {decision.id} ({decision.question!r}) has no source span",
                    decision_id=decision.id,
                )
            )
            continue
        for span in decision.source_spans:
            if span.quote not in text:
                warnings.append(
                    ExtractionWarning(
                        code="ungrounded_decision",
                        message=(
                            f"decision {decision.id}: quote {span.quote!r} not found in document"
                        ),
                        decision_id=decision.id,
                    )
                )

    return warnings
