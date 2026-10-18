"""Flow pass (LLM): whole-document conditional routing, ordering rules and deadlines.

The structure pass sees one section at a time.  This pass sees the whole SOP plus the extracted
steps and adds what only a reader of the full text can know: exceptions that skip steps, "must
happen before" rules, event links ("re-reviewed before payment") and end-to-end deadlines.

It is strictly *additive and validated*: every id must exist, quotes are re-grounded in the
document text, and a bad or missing reply leaves the structure-pass result untouched.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field

from app.core.llm.gateway import CallContext, LLMGateway, LLMOutputError, LLMUnavailable
from app.extract.structure import _parse_condition
from app.extract.textrules import is_exception_text, parse_applicability, parse_deadline
from app.extract.symbols import symbol_table_json
from app.schemas.docast import DocAST
from app.schemas.ir_sop import (
    AlwaysCondition,
    Constraint,
    ConstraintKind,
    Deadline,
    Decision,
    DecisionBranch,
    ExtractionWarning,
    Process,
    SymbolTable,
    TimeUnit,
    Transition,
    UnknownCondition,
)
from app.schemas.provenance import SourceSpan

log = logging.getLogger(__name__)

MAX_DOC_CHARS = 14_000
_END_TO_END = re.compile(r"submission|submit|request|application|filing|raised|end-to-end|overall|total", re.I)


class _Link(BaseModel):
    from_id: str
    to_id: str
    label: str | None = None


class _Branch(BaseModel, extra="allow"):
    label: str = ""
    condition: dict = Field(default_factory=dict)
    next_step_id: str = "END"


class _Decision(BaseModel, extra="allow"):
    id: str
    question: str = ""
    preceding_step_id: str | None = None
    branches: list[_Branch] = Field(default_factory=list)


class _Constraint(BaseModel, extra="allow"):
    kind: str
    description: str = ""
    before_step_id: str | None = None
    target_step_id: str | None = None
    source_quote: str | None = None


class _Deadline(BaseModel, extra="allow"):
    description: str = ""
    max_duration: float
    unit: str = "days"
    from_step_id: str | None = None
    to_step_id: str | None = None
    source_quote: str | None = None


class FlowReply(BaseModel, extra="allow"):
    entry_step_id: str | None = None
    rule_step_ids: list[str] = Field(default_factory=list)
    links: list[_Link] = Field(default_factory=list)
    decisions: list[_Decision] = Field(default_factory=list)
    constraints: list[_Constraint] = Field(default_factory=list)
    deadlines: list[_Deadline] = Field(default_factory=list)


def _steps_summary(proc: Process) -> str:
    lines = []
    for s in proc.steps:
        actor = s.actor_role_id or s.actor_raw or "-"
        quote = (s.source_spans[0].quote if s.source_spans else "")[:140]
        lines.append(f"[{s.id}] clause {s.number or '?'} | actor: {actor} | {s.action} | “{quote}”")
    return "\n".join(lines) or "(none)"


def _decisions_summary(proc: Process) -> str:
    if not proc.decisions:
        return "(none)"
    return "\n".join(
        f"[{d.id}] after {d.preceding_step_id}: {d.question} -> "
        + ", ".join(f"{b.label}=>{b.next_step_id}" for b in d.branches)
        for d in proc.decisions
    )


def _span(ast: DocAST, quote: str | None) -> list[SourceSpan]:
    if not quote:
        return []
    idx = ast.text.find(quote)
    if idx < 0:
        return []
    return [
        SourceSpan(
            document_id=ast.document_id, char_start=idx, char_end=idx + len(quote), quote=quote
        )
    ]


def apply_flow_pass(
    ast: DocAST,
    proc: Process,
    symbols: SymbolTable,
    llm: LLMGateway,
    context: CallContext,
    reuse: dict | None = None,
    record: dict | None = None,
    key: str = "",
) -> list[ExtractionWarning]:
    """Run the pass and merge its validated output into ``proc`` (in place).

    ``reuse`` replays a previous reply (incremental recompile); ``record`` collects the reply.
    """
    warnings: list[ExtractionWarning] = []
    if not proc.steps:
        return warnings
    try:
        if reuse is not None:
            reply = FlowReply.model_validate(reuse)
            if record is not None:
                record[key] = reuse
            return warnings + _merge_reply(ast, proc, symbols, reply)
        reply = llm.structured(
            "flow_pass",
            FlowReply,
            {
                "filename": ast.filename,
                "symbol_table_json": symbol_table_json(symbols),
                "steps_summary": _steps_summary(proc),
                "decisions_summary": _decisions_summary(proc),
                "document_text": ast.text[:MAX_DOC_CHARS],
            },
            context=context,
        )
    except (LLMUnavailable, LLMOutputError) as exc:
        return [ExtractionWarning(code="flow_pass_failed", message=str(exc)[:300])]
    except Exception as exc:  # never let an enrichment pass break extraction
        log.exception("flow pass crashed")
        return [ExtractionWarning(code="flow_pass_failed", message=f"unexpected error: {exc}"[:300])]

    if record is not None:
        record[key] = reply.model_dump(mode="json")
    return warnings + _merge_reply(ast, proc, symbols, reply)


def _merge_reply(ast: DocAST, proc: Process, symbols: SymbolTable, reply: FlowReply) -> list[ExtractionWarning]:
    warnings: list[ExtractionWarning] = []
    step_ids = {s.id for s in proc.steps}
    node_ids = step_ids | {d.id for d in proc.decisions} | {"END"}

    if reply.entry_step_id in step_ids:
        proc.entry_step_id = reply.entry_step_id

    for sid in reply.rule_step_ids:
        step = proc.step(sid)
        if step is None or step.sla is not None:
            continue  # a step with its own time limit is part of the flow
        quote = " ".join(sp.quote for sp in step.source_spans) + " " + step.action
        if parse_deadline(quote) is None and parse_applicability(quote, symbols.roles) is None:
            step.off_flow = True  # (a clause with its own applicability condition is routing)

    for ln in reply.links:
        if ln.from_id in step_ids and ln.to_id in node_ids and ln.from_id != ln.to_id:
            if not any(t.from_id == ln.from_id and t.to_id == ln.to_id for t in proc.transitions):
                proc.transitions.append(
                    Transition(from_id=ln.from_id, to_id=ln.to_id, label=ln.label)
                )

    for d in reply.decisions:
        decision_ids = {x.id for x in proc.decisions} | {d.id}
        targets = step_ids | decision_ids | {"END"}
        branches: list[DecisionBranch] = []
        for b in d.branches:
            if b.next_step_id not in targets:
                continue
            cond = _parse_condition(b.condition or {"kind": "always"})
            branches.append(DecisionBranch(label=b.label, condition=cond, next_step_id=b.next_step_id))
        if len(branches) < 2:
            continue
        if d.preceding_step_id and d.preceding_step_id not in step_ids:
            continue
        if any((st := proc.step(b.next_step_id)) is not None and st.off_flow for b in branches):
            continue  # it models a clause already absorbed as a rule or shortcut
        new_targets = {b.next_step_id for b in branches if b.next_step_id in step_ids}
        if len(new_targets) >= 2 and any(
            len(new_targets & {b.next_step_id for b in x.branches}) >= 2
            for x in proc.decisions
            if x.id != d.id
        ):
            continue  # same routing already extracted; keep the existing decision
        # 'always' is only valid for an explicit otherwise branch; the normaliser re-checks this
        new = Decision(
            id=d.id,
            question=d.question,
            preceding_step_id=d.preceding_step_id,
            branches=branches,
            extraction_confidence=0.7,
        )
        existing = proc.decision(d.id)
        if existing is not None and existing.inferred:
            continue  # never overwrite a decision the deterministic normaliser derived
        if existing is not None:
            proc.decisions[proc.decisions.index(existing)] = new
        else:
            proc.decisions.append(new)

    n = len(proc.constraints)
    for c in reply.constraints:
        try:
            kind = ConstraintKind(c.kind)
        except ValueError:
            continue
        if kind == ConstraintKind.MUST_PRECEDE and not (
            c.before_step_id in step_ids and c.target_step_id in step_ids
        ):
            continue
        if kind == ConstraintKind.MUST_PRECEDE:
            before = proc.step(c.before_step_id or "")
            if before is not None and is_exception_text(
                " ".join([a.quote for a in before.source_spans] + [before.action])
            ):
                continue  # an exception handler is not a precondition for every path
            if c.before_step_id == c.target_step_id:
                continue
        if any(
            x.kind == kind and x.before_step_id == c.before_step_id and x.target_step_id == c.target_step_id
            for x in proc.constraints
        ):
            continue
        n += 1
        proc.constraints.append(
            Constraint(
                id=f"c{n:02d}",
                kind=kind,
                description=c.description,
                before_step_id=c.before_step_id,
                target_step_id=c.target_step_id,
                source_spans=_span(ast, c.source_quote),
            )
        )

    n = len(proc.deadlines)
    for d in reply.deadlines:
        try:
            unit = TimeUnit(d.unit)
        except ValueError:
            unit = TimeUnit.DAYS
        if (d.from_step_id and d.from_step_id not in step_ids) or (
            d.to_step_id and d.to_step_id not in step_ids
        ):
            continue
        if any(x.description == d.description for x in proc.deadlines):
            continue
        step_sla_match = any(
            st.sla and st.sla.max_duration == d.max_duration and st.sla.unit == unit
            for st in proc.steps
        )
        if d.from_step_id and d.from_step_id == d.to_step_id:
            continue
        if step_sla_match and not _END_TO_END.search((d.description or "") + " " + (d.source_quote or "")):
            continue  # that limit already lives on a step; the per-step SLA covers it
        if not d.from_step_id and not d.to_step_id:
            # a limit that belongs to one step (its own SLA) is not an end-to-end deadline
            text = (d.description or "") + " " + (d.source_quote or "")
            if not _END_TO_END.search(text) or any(
                st.sla and st.sla.max_duration == d.max_duration and st.source_spans
                and st.source_spans[0].quote and st.source_spans[0].quote in text
                for st in proc.steps
            ):
                continue
        if any(x.max_duration == d.max_duration and x.unit == unit for x in proc.deadlines):
            continue
        n += 1
        proc.deadlines.append(
            Deadline(
                id=f"dl{n:02d}",
                description=d.description,
                max_duration=d.max_duration,
                unit=unit,
                from_step_id=d.from_step_id,
                to_step_id=d.to_step_id,
                source_spans=_span(ast, d.source_quote),
            )
        )

    warnings.append(
        ExtractionWarning(
            code="flow_pass",
            message=(
                f"Flow pass added {len(reply.links)} link(s), {len(reply.decisions)} decision(s), "
                f"{len(reply.constraints)} constraint(s), {len(reply.deadlines)} deadline(s)."
            ),
        )
    )
    # keep imports honest for type checkers
    _ = (AlwaysCondition, UnknownCondition, json)
    return warnings
