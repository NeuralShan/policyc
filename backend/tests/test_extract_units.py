"""Unit tests for Layer 2 extraction helpers (no LLM calls)."""

from app.extract.diagram_merge import check_diagram_vs_text
from app.extract.grounding import check_grounding
from app.schemas.docast import (
    DiagramEdge,
    DiagramGraph,
    DiagramNode,
    DiagramNodeKind,
    DocAST,
    DocNode,
    NodeKind,
)
from app.schemas.dsl import (
    always,
    condition_summary,
    duration,
    is_vague,
    money,
    vague,
    validate_condition,
)
from app.schemas.ir_sop import (
    ArtifactRef,
    CompareCondition,
    ConditionKind,
    LogicalCondition,
    Process,
    RoleRef,
    SopIR,
    Step,
    StepKind,
    SymbolTable,
    SystemRef,
    TypedValue,
    ValueType,
)
from app.schemas.provenance import SourceSpan

# ---------------------------------------------------------------------------
# DSL helpers
# ---------------------------------------------------------------------------


def test_is_vague_matches_promptly():
    assert is_vague("The CSA responds to the customer promptly.")


def test_is_vague_false_for_specific():
    assert not is_vague("within 3 business days")


def test_condition_summary_always():
    assert condition_summary(always()) == "always"


def test_condition_summary_vague():
    assert "VAGUE" in condition_summary(vague("promptly"))


def test_condition_summary_compare_money():
    cond = CompareCondition(
        kind=ConditionKind.COMPARE,
        left="refund_amount",
        op="gt",
        right=money(5000, "INR"),
    )
    summary = condition_summary(cond)
    assert "refund_amount" in summary
    assert "5000" in summary
    assert "INR" in summary


def test_condition_summary_logical():
    inner = CompareCondition(
        kind=ConditionKind.COMPARE,
        left="x",
        op="eq",
        right=TypedValue(value_type=ValueType.NUMBER, number=1),
    )
    outer = LogicalCondition(kind=ConditionKind.LOGICAL, logical_op="not", operands=[inner])
    assert condition_summary(outer).startswith("NOT")


def test_validate_condition_valid_compare():
    cond = CompareCondition(
        kind=ConditionKind.COMPARE,
        left="amount",
        op="lt",
        right=money(10000, "USD"),
    )
    assert validate_condition(cond) == []


def test_validate_condition_bad_op():
    cond = CompareCondition(
        kind=ConditionKind.COMPARE,
        left="x",
        op="INVALID",
        right=TypedValue(value_type=ValueType.NUMBER, number=1),
    )
    errors = validate_condition(cond)
    assert any("operator" in e for e in errors)


def test_validate_condition_money_no_currency():
    cond = CompareCondition(
        kind=ConditionKind.COMPARE,
        left="x",
        op="gt",
        right=TypedValue(value_type=ValueType.MONEY, number=100),  # missing currency
    )
    errors = validate_condition(cond)
    assert any("currency" in e for e in errors)


def test_validate_logical_not_multiple_operands():
    inner = always()
    cond = LogicalCondition(
        kind=ConditionKind.LOGICAL, logical_op="not", operands=[inner, inner]
    )
    errors = validate_condition(cond)
    assert any("one operand" in e for e in errors)


def test_duration_helper():
    d = duration(3, "business days")
    assert d.duration_unit == "business_days"
    assert d.number == 3


# ---------------------------------------------------------------------------
# Grounding check
# ---------------------------------------------------------------------------


def _minimal_ast(text: str = "The Agent shall log the complaint in CRM.") -> DocAST:
    return DocAST(
        document_id="doc_test",
        sha256="abc",
        filename="test.md",
        media_type="text/markdown",
        parser="test",
        text=text,
        nodes=[
            DocNode(
                id="n0001",
                kind=NodeKind.PARAGRAPH,
                text=text,
                spans=[
                    SourceSpan(
                        document_id="doc_test",
                        char_start=0,
                        char_end=len(text),
                        quote=text,
                    )
                ],
            )
        ],
    )


def _step_with_span(ast: DocAST, quote: str) -> Step:
    idx = ast.text.find(quote)
    spans = (
        [
            SourceSpan(
                document_id=ast.document_id,
                char_start=idx,
                char_end=idx + len(quote),
                quote=quote,
            )
        ]
        if idx >= 0
        else []
    )
    return Step(id="s01", kind=StepKind.ACTION, action="log complaint", source_spans=spans)


def test_grounding_valid_span():
    ast = _minimal_ast()
    step = _step_with_span(ast, "Agent shall log")
    proc = Process(id="p", name="test", document_id="doc_test", steps=[step])
    warnings = check_grounding(proc, ast)
    assert not warnings


def test_grounding_bad_quote():
    ast = _minimal_ast()
    span = SourceSpan(
        document_id="doc_test", char_start=0, char_end=5, quote="XYZNOTHERE"
    )
    step = Step(id="s01", kind=StepKind.ACTION, action="log", source_spans=[span])
    proc = Process(id="p", name="test", document_id="doc_test", steps=[step])
    warnings = check_grounding(proc, ast)
    assert any(w.code == "ungrounded_step" for w in warnings)


def test_grounding_no_span():
    ast = _minimal_ast()
    step = Step(id="s01", kind=StepKind.ACTION, action="log", source_spans=[])
    proc = Process(id="p", name="test", document_id="doc_test", steps=[step])
    warnings = check_grounding(proc, ast)
    assert any(w.code == "ungrounded_step" for w in warnings)


# ---------------------------------------------------------------------------
# Diagram merge
# ---------------------------------------------------------------------------


def _process_with_steps(*actions: str) -> Process:
    steps = [
        Step(id=f"s{i:02}", kind=StepKind.ACTION, action=a)
        for i, a in enumerate(actions, 1)
    ]
    return Process(id="p", name="test", document_id="doc_test", steps=steps)


def test_diagram_merge_no_warnings_when_labels_match():
    proc = _process_with_steps("log complaint in CRM", "send notification email")
    diagram = DiagramGraph(
        nodes=[
            DiagramNode(id="n1", label="log complaint", kind=DiagramNodeKind.TASK),
            DiagramNode(id="n2", label="send notification", kind=DiagramNodeKind.TASK),
        ],
        edges=[DiagramEdge(source="n1", target="n2")],
    )
    ast = _minimal_ast()
    warnings = check_diagram_vs_text(ast, proc, diagram)
    xd004 = [w for w in warnings if w.code == "xd004_candidate"]
    assert not xd004


def test_diagram_merge_flags_unmatched_diagram_node():
    proc = _process_with_steps("log complaint")
    diagram = DiagramGraph(
        nodes=[
            DiagramNode(id="n1", label="log complaint", kind=DiagramNodeKind.TASK),
            DiagramNode(id="n2", label="escalate to manager", kind=DiagramNodeKind.TASK),
        ],
        edges=[],
    )
    ast = _minimal_ast()
    warnings = check_diagram_vs_text(ast, proc, diagram)
    xd004 = [w for w in warnings if w.code == "xd004_candidate"]
    assert any("escalate to manager" in w.message for w in xd004)


# ---------------------------------------------------------------------------
# IR schema
# ---------------------------------------------------------------------------


def test_sop_ir_roundtrip():
    ir = SopIR(run_id="run_01", document_ids=["doc_01"])
    data = ir.model_dump(mode="json")
    ir2 = SopIR.model_validate(data)
    assert ir2.run_id == "run_01"
    assert ir2.review_status == "pending"


def test_symbol_table_all_ids():
    table = SymbolTable(
        roles=[RoleRef(id="csa", name="CSA")],
        artifacts=[ArtifactRef(id="raf", name="Refund Approval Form")],
        systems=[SystemRef(id="crm", name="CRM")],
    )
    ids = table.all_ids()
    assert "csa" in ids
    assert "raf" in ids
    assert "crm" in ids
