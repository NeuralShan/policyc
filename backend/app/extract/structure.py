"""Structure pass: extract steps, decisions and transitions from a DocAST section.

For each top-level heading section in the DocAST we make one LLM call (structure_pass prompt),
then merge the results into a single Process.  The section-by-section approach keeps each call
small enough for the lite/flash quota and makes repairs targeted.

Validation errors are fed back in a repair loop (up to MAX_REPAIRS attempts).
"""

import json

from pydantic import BaseModel, Field

from app.core.llm.gateway import CallContext, LLMGateway, LLMOutputError, LLMUnavailable
from app.schemas.docast import DocAST, DocNode, NodeKind
from app.schemas.ir_sop import (
    SLA,
    AlwaysCondition,
    CompareCondition,
    ConditionExpr,
    ConditionKind,
    Decision,
    DecisionBranch,
    ExternalReference,
    ExtractionWarning,
    LogicalCondition,
    ModalVerb,
    Process,
    Step,
    StepKind,
    SymbolTable,
    TerminalOutcome,
    TimeUnit,
    Transition,
    Trigger,
    TypedValue,
    UnknownCondition,
    VagueCondition,
    ValueType,
)
from app.schemas.provenance import SourceSpan

MAX_REPAIRS = 2
MAX_SECTION_CHARS = 4_000

# ---------------------------------------------------------------------------
# LLM reply schemas (permissive – we validate manually after)
# ---------------------------------------------------------------------------


class _ConditionData(BaseModel, extra="allow"):
    kind: str = "always"
    left: str | None = None
    op: str | None = None
    right: dict | None = None
    logical_op: str | None = None
    operands: list[dict] = Field(default_factory=list)
    text: str | None = None
    raw_text: str | None = None


class _SLAData(BaseModel):
    max_duration: float
    unit: str
    from_event: str = "step_start"
    vague: bool = False
    vague_text: str | None = None


class _StepData(BaseModel, extra="allow"):
    id: str
    kind: str = "action"
    number: str | None = None
    actor_role_id: str | None = None
    actor_raw: str | None = None
    modal: str = "unknown"
    action: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    preconditions: list[dict] = Field(default_factory=list)
    sla: _SLAData | None = None
    source_quote: str | None = None
    extraction_confidence: float = 1.0
    note: str | None = None
    terminal_outcome: str | None = None


class _BranchData(BaseModel, extra="allow"):
    label: str
    condition: dict = Field(default_factory=dict)
    next_step_id: str
    source_quote: str | None = None


class _DecisionData(BaseModel, extra="allow"):
    id: str
    question: str
    preceding_step_id: str
    branches: list[_BranchData] = Field(default_factory=list)
    source_quote: str | None = None
    extraction_confidence: float = 1.0


class _TransitionData(BaseModel, extra="allow"):
    from_id: str
    to_id: str
    condition: dict = Field(default_factory=lambda: {"kind": "always"})
    label: str | None = None


class _ReferenceData(BaseModel, extra="allow"):
    ref_text: str
    doc_code: str | None = None
    section: str | None = None


class StructureReply(BaseModel, extra="allow"):
    steps: list[_StepData] = Field(default_factory=list)
    decisions: list[_DecisionData] = Field(default_factory=list)
    transitions: list[_TransitionData] = Field(default_factory=list)
    references: list[_ReferenceData] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Converters: raw LLM data → IR objects
# ---------------------------------------------------------------------------


def _parse_condition(data: dict) -> ConditionExpr:
    kind = data.get("kind", "always")
    if kind == ConditionKind.ALWAYS:
        return AlwaysCondition()
    if kind == ConditionKind.VAGUE:
        return VagueCondition(kind=ConditionKind.VAGUE, text=data.get("text", ""))
    if kind == ConditionKind.UNKNOWN:
        return UnknownCondition(kind=ConditionKind.UNKNOWN, raw_text=data.get("raw_text", ""))
    if kind == ConditionKind.COMPARE:
        right_data = data.get("right") or {}
        vt_raw = right_data.get("value_type", "number")
        try:
            vt = ValueType(vt_raw)
        except ValueError:
            vt = ValueType.NUMBER
        right = TypedValue(
            value_type=vt,
            number=right_data.get("number"),
            text=right_data.get("text"),
            bool_value=right_data.get("bool_value"),
            currency=right_data.get("currency"),
            duration_unit=right_data.get("duration_unit"),
        )
        return CompareCondition(
            kind=ConditionKind.COMPARE,
            left=data.get("left", ""),
            op=data.get("op", "eq"),
            right=right,
        )
    if kind == ConditionKind.LOGICAL:
        operands = [_parse_condition(o) for o in data.get("operands", [])]
        return LogicalCondition(
            kind=ConditionKind.LOGICAL,
            logical_op=data.get("logical_op", "and"),
            operands=operands,
        )
    return UnknownCondition(kind=ConditionKind.UNKNOWN, raw_text=str(data))


def _parse_sla(data: _SLAData | None) -> SLA | None:
    if data is None:
        return None
    try:
        unit = TimeUnit(data.unit)
    except ValueError:
        unit = TimeUnit.DAYS
    return SLA(
        max_duration=data.max_duration,
        unit=unit,
        from_event=data.from_event,
        vague=data.vague,
        vague_text=data.vague_text,
    )


def _parse_step(d: _StepData, ast: DocAST, symbols: SymbolTable) -> tuple[Step, list[str]]:
    """Convert raw step data to a Step, returning (step, validation_errors)."""
    errors: list[str] = []
    try:
        kind = StepKind(d.kind)
    except ValueError:
        kind = StepKind.ACTION
        errors.append(f"step {d.id}: unknown kind {d.kind!r}")

    try:
        modal = ModalVerb(d.modal)
    except ValueError:
        modal = ModalVerb.UNKNOWN

    if d.actor_role_id and not symbols.role(d.actor_role_id):
        errors.append(f"step {d.id}: actor_role_id {d.actor_role_id!r} not in symbol table")

    for art_id in d.inputs + d.outputs:
        if not symbols.artifact(art_id):
            errors.append(f"step {d.id}: artifact {art_id!r} not in symbol table")

    for sys_id in d.systems:
        if not symbols.system(sys_id):
            errors.append(f"step {d.id}: system {sys_id!r} not in symbol table")

    spans: list[SourceSpan] = []
    if d.source_quote:
        idx = ast.text.find(d.source_quote)
        if idx >= 0:
            spans.append(
                SourceSpan(
                    document_id=ast.document_id,
                    char_start=idx,
                    char_end=idx + len(d.source_quote),
                    quote=d.source_quote,
                )
            )
        else:
            errors.append(f"step {d.id}: source_quote not found in document text")

    terminal: TerminalOutcome | None = None
    if d.terminal_outcome:
        try:
            terminal = TerminalOutcome(d.terminal_outcome)
        except ValueError:
            terminal = TerminalOutcome.OTHER

    preconditions = [_parse_condition(c) for c in d.preconditions]

    step = Step(
        id=d.id,
        kind=kind,
        number=d.number,
        actor_role_id=d.actor_role_id,
        actor_raw=d.actor_raw,
        modal=modal,
        action=d.action,
        inputs=d.inputs,
        outputs=d.outputs,
        systems=d.systems,
        preconditions=preconditions,
        sla=_parse_sla(d.sla),
        source_spans=spans,
        extraction_confidence=d.extraction_confidence,
        note=d.note,
        terminal_outcome=terminal,
    )
    return step, errors


def _parse_decision(
    d: _DecisionData, ast: DocAST, known_step_ids: set[str]
) -> tuple[Decision, list[str]]:
    errors: list[str] = []
    if d.preceding_step_id not in known_step_ids:
        errors.append(
            f"decision {d.id}: preceding_step_id {d.preceding_step_id!r} not a known step"
        )
    branches: list[DecisionBranch] = []
    for b in d.branches:
        cond = _parse_condition(b.condition)
        spans: list[SourceSpan] = []
        if b.source_quote:
            idx = ast.text.find(b.source_quote)
            if idx >= 0:
                spans.append(
                    SourceSpan(
                        document_id=ast.document_id,
                        char_start=idx,
                        char_end=idx + len(b.source_quote),
                        quote=b.source_quote,
                    )
                )
        branches.append(
            DecisionBranch(
                label=b.label, condition=cond, next_step_id=b.next_step_id, source_spans=spans
            )
        )

    spans_d: list[SourceSpan] = []
    if d.source_quote:
        idx = ast.text.find(d.source_quote)
        if idx >= 0:
            spans_d.append(
                SourceSpan(
                    document_id=ast.document_id,
                    char_start=idx,
                    char_end=idx + len(d.source_quote),
                    quote=d.source_quote,
                )
            )
    decision = Decision(
        id=d.id,
        question=d.question,
        preceding_step_id=d.preceding_step_id,
        branches=branches,
        source_spans=spans_d,
        extraction_confidence=d.extraction_confidence,
    )
    return decision, errors


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------


def _section_text(ast: DocAST, heading_node: DocNode) -> str:
    """Collect text of the heading and all its children."""
    parts = [heading_node.text]
    for node in ast.nodes:
        if node.parent_id == heading_node.id:
            parts.append(node.text)
    return "\n".join(parts)[:MAX_SECTION_CHARS]


def _top_level_sections(ast: DocAST) -> list[DocNode]:
    """Return level-1 heading nodes (the main sections of the SOP)."""
    return [n for n in ast.nodes if n.kind == NodeKind.HEADING and n.level == 1]


def _ir_summary(steps: list[Step], decisions: list[Decision]) -> str:
    """Produce a short human-readable summary of what was extracted for the round-trip check."""
    lines = []
    for s in steps:
        actor = s.actor_role_id or s.actor_raw or "(no actor)"
        lines.append(f"- [{s.id}] {actor}: {s.action}")
    for d in decisions:
        lines.append(f"- [decision {d.id}] {d.question} → {[b.label for b in d.branches]}")
    return "\n".join(lines) or "(no steps extracted)"


# ---------------------------------------------------------------------------
# Structure pass (per section)
# ---------------------------------------------------------------------------


def _extract_section(
    ast: DocAST,
    section_label: str,
    section_text: str,
    symbols: SymbolTable,
    prior_step_ids: list[str],
    llm: LLMGateway,
    context: CallContext,
) -> tuple[StructureReply | None, list[str]]:
    """Run the structure_pass prompt for one section. Returns (reply, errors)."""
    from app.extract.symbols import symbol_table_json

    variables = {
        "filename": ast.filename,
        "section_label": section_label,
        "symbol_table_json": symbol_table_json(symbols),
        "prior_step_ids": json.dumps(prior_step_ids),
        "section_text": section_text,
    }
    try:
        reply = llm.structured("structure_pass", StructureReply, variables, context=context)
        return reply, []
    except (LLMUnavailable, LLMOutputError) as exc:
        return None, [str(exc)]
    except Exception as exc:
        return None, [f"unexpected error: {exc}"]


def _run_roundtrip(
    ast: DocAST,
    section_label: str,
    section_text: str,
    steps: list[Step],
    decisions: list[Decision],
    llm: LLMGateway,
    context: CallContext,
) -> list[ExtractionWarning]:
    """Back-translate IR and ask the LLM to compare with source. Returns warnings."""

    class _RoundtripReply(BaseModel):
        agreement: float = 1.0
        missing: list[dict] = Field(default_factory=list)
        wrong: list[dict] = Field(default_factory=list)
        hallucinated: list[dict] = Field(default_factory=list)

    summary = _ir_summary(steps, decisions)
    try:
        reply = llm.structured(
            "roundtrip_check",
            _RoundtripReply,
            {
                "section_label": section_label,
                "ir_summary": summary,
                "section_text": section_text,
            },
            context=context,
        )
    except (LLMUnavailable, LLMOutputError):
        return []

    warnings: list[ExtractionWarning] = []
    if reply.agreement < 0.8:
        for item in reply.missing:
            warnings.append(
                ExtractionWarning(
                    code="roundtrip_missing",
                    message=f"[{section_label}] missing: {item.get('description', '')} "
                    f"(source: {item.get('source_quote', '')!r})",
                )
            )
        for item in reply.wrong:
            warnings.append(
                ExtractionWarning(
                    code="roundtrip_wrong",
                    message=f"[{section_label}] wrong: {item.get('description', '')}",
                )
            )
        for item in reply.hallucinated:
            warnings.append(
                ExtractionWarning(
                    code="roundtrip_hallucinated",
                    message=f"[{section_label}] hallucinated: {item.get('description', '')}",
                )
            )
    return warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_structure(
    ast: DocAST,
    symbols: SymbolTable,
    llm: LLMGateway,
    context: CallContext,
) -> tuple[Process, list[ExtractionWarning]]:
    """Run the structure pass over all sections.  Returns (Process, warnings)."""
    sections = _top_level_sections(ast)
    if not sections:
        # Flat document with no headings – treat whole text as one section.
        sections_data = [("(whole document)", ast.text[:MAX_SECTION_CHARS])]
    else:
        sections_data = [
            (f"Section {n.number or n.text[:40]}", _section_text(ast, n))
            for n in sections
        ]

    all_steps: list[Step] = []
    all_decisions: list[Decision] = []
    all_transitions: list[Transition] = []
    all_references: list[ExternalReference] = []
    all_warnings: list[ExtractionWarning] = []

    # IDs used so far across sections (to detect duplicates from the LLM)
    prior_step_ids: list[str] = []
    used_step_ids: set[str] = set()
    used_decision_ids: set[str] = set()

    for section_label, section_text in sections_data:
        if not section_text.strip():
            continue

        reply, errs = _extract_section(
            ast, section_label, section_text, symbols, prior_step_ids, llm, context
        )
        if reply is None:
            all_warnings.append(
                ExtractionWarning(
                    code="structure_pass_failed",
                    message=f"{section_label}: {'; '.join(errs)}",
                )
            )
            continue

        # Deduplicate ids (LLM may repeat across sections)
        def _fresh_step_id(raw: str) -> str:
            if raw not in used_step_ids:
                return raw
            i = 2
            while f"{raw}_{i}" in used_step_ids:
                i += 1
            return f"{raw}_{i}"

        def _fresh_decision_id(raw: str) -> str:
            if raw not in used_decision_ids:
                return raw
            i = 2
            while f"{raw}_{i}" in used_decision_ids:
                i += 1
            return f"{raw}_{i}"

        section_steps: list[Step] = []
        section_decisions: list[Decision] = []
        validation_errors: list[str] = []

        # --- Steps ---
        for d in reply.steps:
            # Remap id if duplicate
            new_id = _fresh_step_id(d.id)
            if new_id != d.id:
                d = d.model_copy(update={"id": new_id})
            used_step_ids.add(d.id)
            step, errs = _parse_step(d, ast, symbols)
            section_steps.append(step)
            validation_errors.extend(errs)

        # --- Decisions ---
        known_step_ids = {s.id for s in section_steps} | set(prior_step_ids)
        for d in reply.decisions:
            new_id = _fresh_decision_id(d.id)
            if new_id != d.id:
                # also remap references in branches
                d = d.model_copy(update={"id": new_id})
            used_decision_ids.add(d.id)
            decision, errs = _parse_decision(d, ast, known_step_ids)
            section_decisions.append(decision)
            validation_errors.extend(errs)

        # --- Transitions ---
        for t in reply.transitions:
            raw_cond = t.condition if isinstance(t.condition, dict) else {"kind": "always"}
            cond = _parse_condition(raw_cond)
            all_transitions.append(
                Transition(from_id=t.from_id, to_id=t.to_id, condition=cond, label=t.label)
            )

        # --- References ---
        for r in reply.references:
            all_references.append(
                ExternalReference(ref_text=r.ref_text, doc_code=r.doc_code, section=r.section)
            )

        # --- Validation warnings ---
        for err in validation_errors:
            all_warnings.append(ExtractionWarning(code="validation_error", message=err))

        # --- Round-trip check (only if flash quota available) ---
        rt_warnings = _run_roundtrip(
            ast, section_label, section_text, section_steps, section_decisions, llm, context
        )
        all_warnings.extend(rt_warnings)

        all_steps.extend(section_steps)
        all_decisions.extend(section_decisions)
        prior_step_ids = list(used_step_ids)

    # Try to detect a trigger from the title / first heading
    trigger: Trigger | None = None
    title_nodes = [n for n in ast.nodes if n.kind in (NodeKind.TITLE, NodeKind.HEADING)]
    if title_nodes:
        t_text = title_nodes[0].text
        trigger = Trigger(description=f"Initiation of {t_text}")

    process = Process(
        id="proc_01",
        name=ast.filename,
        document_id=ast.document_id,
        trigger=trigger,
        steps=all_steps,
        decisions=all_decisions,
        transitions=all_transitions,
        references=all_references,
    )
    return process, all_warnings
