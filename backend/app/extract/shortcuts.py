"""Exception shortcuts: "for minor tool changes under 10 minutes the operator may proceed directly
to maintenance after shutting down the machine".

Such a clause is a conditional jump *around* steps.  It matters most because it is how mandatory
steps get bypassed.  The LLM often places or completes this decision badly, so this module reads
the clause itself:

    condition    "less than 10 minutes"            -> task_duration_minutes < 10
    target       "maintenance"                     -> the step that performs maintenance
    after        "shutting down the machine"       -> the step it jumps from
    otherwise    the step that normally follows ``after``

and rewires ``after -> [condition -> target | otherwise -> old successor]``.  The clause step
itself becomes a rule (it is the decision now).  Nothing is invented: if the target or the
starting step cannot be found with confidence, nothing is changed.
"""

from __future__ import annotations

import re

from app.schemas.ir_sop import (
    AlwaysCondition,
    CompareCondition,
    Constraint,
    ConstraintKind,
    Decision,
    DecisionBranch,
    ExtractionWarning,
    Process,
    Step,
    StepKind,
    Transition,
    TypedValue,
    ValueType,
)

_SHORTCUT = re.compile(
    r"(?:proceed|go|move|skip|jump)\w*\s+(?:directly\s+|straight\s+)?(?:to|into)\s+"
    r"(?P<target>[^,.;]+?)(?:\s+after\s+(?P<after>[^,.;]+))?(?:[,.;]|$)",
    re.I,
)
_DURATION = re.compile(
    r"(?:less\s+than|under|below|fewer\s+than|shorter\s+than)\s+(?P<n>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>minutes?|mins?|hours?|hrs?)",
    re.I,
)
_TAKES = re.compile(r"\b(?:take|takes|taking|expected|last|lasts|duration|required)\b", re.I)
_STOP = {
    "the", "a", "an", "of", "to", "and", "for", "its", "their", "all", "is", "are", "be", "then", "that",
    "with", "using", "normal", "after", "before", "into", "from", "this", "any", "each", "every",
}


def parse_duration_condition(text: str) -> CompareCondition | None:
    """``expected to take less than 10 minutes`` -> ``task_duration_minutes lt 10``."""
    if not _TAKES.search(text or ""):
        return None
    m = _DURATION.search(text)
    if not m:
        return None
    minutes = float(m.group("n"))
    if m.group("unit").lower().startswith(("h", "hr")):
        minutes *= 60
    return CompareCondition(
        left="task_duration_minutes",
        op="lt",
        right=TypedValue(value_type=ValueType.DURATION, number=minutes, duration_unit="minutes"),
    )


def _stem(word: str) -> str:
    w = word.lower()
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: -len(suffix)]
            break
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiou":
        w = w[:-1]
    return w


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[A-Za-z]+", text or "") if t.lower() not in _STOP and len(t) > 2]


def _best_step(proc: Process, phrase: str, exclude: set[str]) -> Step | None:
    """Step whose action best matches ``phrase``; None unless there is a clear winner."""
    want = _tokens(phrase)
    if not want:
        return None
    scored: list[tuple[int, int, Step]] = []
    for i, s in enumerate(proc.steps):
        if s.id in exclude or s.off_flow:
            continue
        have = _tokens(s.action)
        overlap = len(set(want) & set(have))
        if overlap == 0:
            continue
        bonus = 2 if have and want[0] == have[0] else 0  # same leading verb/noun
        scored.append((overlap + bonus, -i, s))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][2]


def equivalent_steps(proc: Process, step_id: str) -> set[str]:
    """Steps that do the same job as ``step_id`` (same leading verb and at least two shared words),
    e.g. "Verify zero energy by attempting to start" and "verify zero energy before proceeding"."""
    base = proc.step(step_id)
    if base is None:
        return {step_id}
    want = _tokens(base.action)
    out = {step_id}
    for s in proc.steps:
        if s.id == step_id:
            continue
        have = _tokens(s.action)
        if want and have and want[0] == have[0] and len(set(want) & set(have)) >= 2:
            out.add(s.id)
    return out


def derive_shortcuts(
    proc: Process, warnings: list[ExtractionWarning], clauses: dict[str, str] | None = None
) -> None:
    clauses = clauses or {}
    for step in list(proc.steps):
        if step.off_flow or step.kind == StepKind.TERMINAL:
            continue
        text = " ".join([clauses.get(step.number or "", "")] + [sp.quote for sp in step.source_spans] + [step.action])
        m = _SHORTCUT.search(text)
        cond = parse_duration_condition(text)
        if not m or cond is None or not m.group("after"):
            continue
        if any(d.id.startswith("d_shortcut_") and d.id.endswith(f"_{step.number}") for d in proc.decisions):
            continue
        # other steps the same clause lists (e.g. "verify zero energy, then proceed directly...")
        siblings = [
            s for s in proc.steps
            if s.id != step.id and s.number and s.number == step.number and not s.off_flow
            and s.kind != StepKind.TERMINAL
        ]
        if siblings and not _SHORTCUT.search(step.action):
            continue  # a sibling step of the clause: the one that names the jump is the marker
        exclude = {step.id} | {s.id for s in siblings}
        target = _best_step(proc, m.group("target"), exclude)
        after = _best_step(proc, m.group("after"), exclude | ({target.id} if target else set()))
        if target is None or after is None or after.id == target.id:
            continue

        succ = next((t.to_id for t in proc.transitions if t.from_id == after.id), None)
        if succ is None:
            idx = proc.steps.index(after)
            succ = next(
                (s.id for s in proc.steps[idx + 1 :] if not s.off_flow and s.id not in exclude and s.id != target.id),
                None,
            )
        if succ is None or succ == target.id:
            continue

        dec_id = f"d_shortcut_{step.number or step.id}"
        # replace anything the model drew for this clause
        proc.decisions = [
            d for d in proc.decisions if d.id != dec_id and not any(b.next_step_id == step.id for b in d.branches)
        ]
        proc.transitions = [t for t in proc.transitions if t.from_id != after.id and t.to_id != step.id]
        label = f"under {cond.right.number:g} minutes"
        proc.decisions.append(
            Decision(
                id=dec_id,
                question=f"Is the task short (expected to take less than {cond.right.number:g} minutes)?",
                preceding_step_id=after.id,
                branches=[
                    DecisionBranch(
                        label=label,
                        condition=cond,
                        next_step_id=siblings[0].id if siblings else target.id,
                        source_spans=step.source_spans,
                    ),
                    DecisionBranch(label="otherwise", condition=AlwaysCondition(), next_step_id=succ),
                ],
                source_spans=step.source_spans,
                extraction_confidence=0.7,
                inferred=True,
            )
        )
        step.off_flow = True
        if siblings:  # the exception path runs its own steps before it rejoins at the target
            chain = [*siblings, target]
            proc.transitions = [t for t in proc.transitions if t.from_id not in {s.id for s in siblings}]
            for a, b in zip(chain, chain[1:], strict=False):
                proc.transitions.append(
                    Transition(from_id=a.id, to_id=b.id, label="exception path (inferred)", inferred=True)
                )
        warnings.append(
            ExtractionWarning(
                code="shortcut_inferred",
                message=(
                    f"Clause {step.number or step.id} lets work skip from “{after.action}” directly to "
                    f"“{target.action}” when the task is short; modelled as decision {dec_id}."
                ),
                decision_id=dec_id,
            )
        )


_BEFORE_RULE = re.compile(
    r"(?P<subject>[^.;]+?)\s+(?:must|shall)\s+(?:always\s+)?be\s+(?:performed|completed|done|carried\s+out|"
    r"verified|obtained|confirmed)\s+before\s+(?:any\s+|the\s+)?(?P<target>[^.;]+?)(?:\s+(?:begins?|starts?|commences?))?\s*(?:[.;]|$)",
    re.I,
)


def derive_ordering_rules(
    proc: Process, warnings: list[ExtractionWarning], clauses: dict[str, str] | None = None
) -> None:
    """"X must always be performed before Y begins": a standing rule plus a must_precede constraint.

    The clause itself is not a step; it becomes a rule, and the constraint links the step that does
    X to the step that does Y (only when both can be identified with confidence).
    """
    clauses = clauses or {}
    for step in list(proc.steps):
        if step.off_flow or step.kind == StepKind.TERMINAL:
            continue
        text = " ".join([clauses.get(step.number or "", "")] + [sp.quote for sp in step.source_spans] + [step.action])
        m = _BEFORE_RULE.search(text)
        if not m:
            continue
        exclude = {step.id}
        before = _best_step(proc, m.group("subject"), exclude)
        target = _best_step(proc, m.group("target"), exclude | ({before.id} if before else set()))
        step.off_flow = True  # the clause states a rule; the steps it talks about are the flow
        if before is None or target is None or before.id == target.id:
            continue
        if any(
            c.kind == ConstraintKind.MUST_PRECEDE and c.before_step_id == before.id and c.target_step_id == target.id
            for c in proc.constraints
        ):
            continue
        proc.constraints.append(
            Constraint(
                id=f"c{len(proc.constraints) + 1:02d}",
                kind=ConstraintKind.MUST_PRECEDE,
                description=(step.source_spans[0].quote if step.source_spans else step.action),
                before_step_id=before.id,
                target_step_id=target.id,
                source_spans=step.source_spans,
            )
        )
        warnings.append(
            ExtractionWarning(
                code="ordering_rule_inferred",
                message=f"Clause {step.number or step.id}: “{before.action}” must precede “{target.action}”.",
                step_id=step.id,
            )
        )


_POSITIVE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s+)?(?:approved|accepted|granted|successful|verified)\b", re.I)
_NEGATIVE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s+)?(?:rejected|declined|denied|refused|unsuccessful)\b", re.I)


def derive_outcome_branches(
    proc: Process, warnings: list[ExtractionWarning], clauses: dict[str, str] | None = None
) -> None:
    """"Approved leave is recorded…" / "Rejected requests are closed…": the two outcome clauses of
    a decision the model did not draw. They become an explicit approved / not-approved decision
    after the step that decides, so neither clause is left orphaned or chained into the other."""
    clauses = clauses or {}

    def lead(step: Step) -> str:
        return clauses.get(step.number or "") or (step.source_spans[0].quote if step.source_spans else step.action)

    pos = [s for s in proc.steps if not s.off_flow and _POSITIVE.search(lead(s))]
    neg = [s for s in proc.steps if not s.off_flow and _NEGATIVE.search(lead(s))]
    if not pos or not neg:
        return
    a, b = pos[0], neg[0]
    if a.id == b.id or proc.decision(f"d_outcome_{a.id}"):
        return
    first = min(proc.steps.index(a), proc.steps.index(b))
    # the step that decides is the nearest earlier on-flow step that is not itself an outcome clause
    decider = next(
        (s for s in reversed(proc.steps[:first]) if not s.off_flow and s.kind != StepKind.TERMINAL), None
    )
    if decider is None:
        return
    # the model may already have routed to either outcome; the decision replaces those edges
    members = {a.id, b.id}
    if any(b_.next_step_id in members for d in proc.decisions for b_ in d.branches):
        return
    proc.transitions = [t for t in proc.transitions if not (t.from_id == decider.id and t.to_id in members)]
    proc.decisions.append(
        Decision(
            id=f"d_outcome_{a.id}",
            question="Is the request approved?",
            preceding_step_id=decider.id,
            branches=[
                DecisionBranch(
                    label="approved",
                    condition=CompareCondition(
                        left="approved", op="eq", right=TypedValue(value_type=ValueType.BOOL, bool_value=True)
                    ),
                    next_step_id=a.id,
                    source_spans=a.source_spans,
                ),
                DecisionBranch(
                    label="not approved",
                    condition=CompareCondition(
                        left="approved", op="eq", right=TypedValue(value_type=ValueType.BOOL, bool_value=False)
                    ),
                    next_step_id=b.id,
                    source_spans=b.source_spans,
                ),
            ],
            extraction_confidence=0.6,
            inferred=True,
        )
    )
    warnings.append(
        ExtractionWarning(
            code="outcome_decision_inferred",
            message=(
                f"Clauses {a.number or a.id} and {b.number or b.id} are the approved / not-approved outcomes "
                f"of “{decider.action}”; modelled as a decision."
            ),
            step_id=decider.id,
        )
    )
