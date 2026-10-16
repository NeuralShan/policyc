"""Heuristic activity→step mapper using Jaccard token overlap (no LLM)."""

from __future__ import annotations

import re

from app.schemas.case_history import EventLog
from app.schemas.ir_sop import SopIR


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def map_activities(event_log: EventLog, ir: SopIR) -> dict[str, str | None]:
    """Return {activity_string: step_id | None} for every unique activity in the log.

    Steps are matched by best Jaccard overlap against their ``action`` text.
    Activities with similarity < 0.1 are unmapped (None).
    """
    # Build step token sets for every process
    step_tokens: dict[str, set[str]] = {}
    for proc in ir.processes:
        for step in proc.steps:
            step_tokens[step.id] = _tokens(step.action)

    unique_activities: set[str] = set()
    for events in event_log.cases.values():
        for e in events:
            unique_activities.add(e.activity)

    mapping: dict[str, str | None] = {}
    for activity in unique_activities:
        act_tok = _tokens(activity)
        best_id: str | None = None
        best_score = 0.0
        for step_id, step_tok in step_tokens.items():
            score = _jaccard(act_tok, step_tok)
            if score > best_score:
                best_score = score
                best_id = step_id
        mapping[activity] = best_id if best_score >= 0.10 else None

    return mapping
