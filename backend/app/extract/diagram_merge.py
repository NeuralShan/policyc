"""Diagram vs text merge: detect XD004 (text and diagram disagree) candidates.

The Layer 1 DiagramGraph captures the flowchart that was read from a figure. This module compares
the diagram's step labels with the text-derived steps and flags significant discrepancies.

XD004 candidates are added as ExtractionWarning(code="xd004_candidate") for later promotion to
full findings in Layer 4.
"""

import re

from app.schemas.docast import DiagramGraph, DiagramNode, DiagramNodeKind, DocAST
from app.schemas.ir_sop import ExtractionWarning, Process, Step


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower())


def _overlap(a: str, b: str) -> float:
    """Rough word-overlap score between two strings (0–1)."""
    wa = set(_normalise(a).split())
    wb = set(_normalise(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


def _best_match(diagram_label: str, steps: list[Step]) -> tuple[Step | None, float]:
    best: Step | None = None
    best_score = 0.0
    for step in steps:
        score = _overlap(diagram_label, step.action)
        if score > best_score:
            best_score = score
            best = step
    return best, best_score


OVERLAP_THRESHOLD = 0.35  # below this: diagram node has no text-step counterpart


def check_diagram_vs_text(
    ast: DocAST,
    process: Process,
    diagram: DiagramGraph,
) -> list[ExtractionWarning]:
    """Compare *diagram* nodes against the extracted *process* steps.

    Returns XD004 candidate warnings.
    """
    warnings: list[ExtractionWarning] = []
    text_steps = process.steps

    # Diagram nodes that the text extraction should have covered
    task_nodes = [
        n for n in diagram.nodes
        if n.kind in (DiagramNodeKind.TASK, DiagramNodeKind.DECISION, DiagramNodeKind.DOCUMENT)
        and n.label.strip()
    ]

    if not task_nodes:
        return []

    unmatched_diagram: list[DiagramNode] = []
    for dnode in task_nodes:
        _, score = _best_match(dnode.label, text_steps)
        if score < OVERLAP_THRESHOLD:
            unmatched_diagram.append(dnode)

    for dnode in unmatched_diagram:
        warnings.append(
            ExtractionWarning(
                code="xd004_candidate",
                message=(
                    f"Diagram node {dnode.label!r} (kind={dnode.kind}) has no matching text step "
                    f"— possible text/diagram disagreement (XD004)"
                ),
            )
        )

    # Also flag text steps that exist only in the text but not in the diagram
    # (only meaningful when the diagram is supposed to be the authoritative flow)
    diagram_labels = [n.label for n in task_nodes]
    for step in text_steps:
        best_label, score = (
            max(
                ((label, _overlap(step.action, label)) for label in diagram_labels),
                key=lambda x: x[1],
            )
            if diagram_labels
            else ("", 0.0)
        )
        if score < OVERLAP_THRESHOLD and step.action:
            warnings.append(
                ExtractionWarning(
                    code="xd004_candidate",
                    message=(
                        f"Text step {step.id} ({step.action!r}) has no counterpart in the diagram "
                        f"— possible text/diagram disagreement (XD004)"
                    ),
                    step_id=step.id,
                )
            )

    return warnings
