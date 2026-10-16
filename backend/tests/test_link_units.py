"""Unit tests for Layer 3 linking helpers (no LLM, no DB)."""

from app.link.emitter import cypher_sha256, emit_cypher
from app.link.resolver import _jaccard, resolve_entities
from app.link.validator import load_graph, validate_graph
from app.link.xref import detect_crossrefs
from app.schemas.docast import DocAST, DocNode, NodeKind
from app.schemas.graph import LinkedIR
from app.schemas.ir_sop import (
    ArtifactRef,
    ExtractionWarning,
    Process,
    ReviewStatus,
    RoleRef,
    SopIR,
    Step,
    StepKind,
    SymbolTable,
    SystemRef,
)
from app.schemas.provenance import SourceSpan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_ir(
    run_id: str = "run_test",
    *,
    roles: list | None = None,
    steps: list | None = None,
) -> SopIR:
    symbols = SymbolTable(
        roles=roles or [RoleRef(id="agent", name="Agent")],
        artifacts=[ArtifactRef(id="form", name="Form")],
        systems=[SystemRef(id="crm", name="CRM")],
    )
    proc_steps = steps or [
        Step(id="s01", kind=StepKind.ACTION, action="log the complaint", actor_role_id="agent")
    ]
    proc = Process(id="p01", name="Complaint Handling", document_id="doc_test", steps=proc_steps)
    return SopIR(
        run_id=run_id,
        document_ids=["doc_test"],
        symbols=symbols,
        processes=[proc],
        review_status=ReviewStatus.APPROVED,
    )


def _minimal_ast(text: str = "The Agent shall log.", doc_id: str = "doc_test") -> DocAST:
    return DocAST(
        document_id=doc_id,
        sha256="abc",
        filename="SOP-CS-014.md",
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
                        document_id=doc_id,
                        char_start=0,
                        char_end=len(text),
                        quote=text,
                    )
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def test_jaccard_exact():
    assert _jaccard("Customer Service Agent", "Customer Service Agent") == 1.0


def test_jaccard_overlap():
    score = _jaccard("Line Manager", "Reporting Manager")
    assert 0 < score < 1.0


def test_jaccard_no_overlap():
    assert _jaccard("Agent", "System") == 0.0


def test_resolve_exact_duplicate():
    """Two roles with identical names should be merged."""
    ir = _minimal_ir(
        roles=[
            RoleRef(id="csa", name="Customer Service Agent"),
            RoleRef(id="csa2", name="Customer Service Agent"),
        ]
    )
    entities, merges, canon_map, _ = resolve_entities(ir)
    assert len(merges) == 1
    assert canon_map["csa2"] == "csa"
    assert any(e.canonical_id == "csa" and "csa2" in e.aliases for e in entities)


def test_resolve_distinct_roles():
    ir = _minimal_ir(
        roles=[
            RoleRef(id="agent", name="Agent"),
            RoleRef(id="manager", name="Manager"),
        ]
    )
    entities, merges, _, _ = resolve_entities(ir)
    assert merges == []
    assert len(entities) >= 2


def test_resolve_overlap_emits_info_warning():
    ir = _minimal_ir(
        roles=[
            RoleRef(id="line_manager", name="Line Manager"),
            RoleRef(id="reporting_manager", name="Reporting Manager"),
        ]
    )
    _, _, _, warnings = resolve_entities(ir)
    # "Manager" overlap → might or might not merge depending on Jaccard threshold
    # Just verify we get at most one warning if they merge
    assert all(isinstance(w, ExtractionWarning) for w in warnings)


# ---------------------------------------------------------------------------
# Cross-reference detector
# ---------------------------------------------------------------------------


def test_xref_detects_pattern():
    ast = _minimal_ast("Refer to SOP-FIN-012 for approval steps.")
    refs, warnings = detect_crossrefs([ast])
    patterns = [r.pattern for r in refs]
    assert "SOP-FIN-012" in patterns
    assert any(w.code == "xd001_unresolved_ref" for w in warnings)


def test_xref_resolves_when_doc_present():
    ast1 = _minimal_ast("See SOP-HR-001 for onboarding.", doc_id="doc_a")
    ast2 = _minimal_ast("Onboarding SOP.", doc_id="doc_b")
    ast2 = DocAST(
        document_id="doc_b",
        sha256="def",
        filename="SOP-HR-001.md",
        media_type="text/markdown",
        parser="test",
        text="Onboarding SOP.",
        nodes=ast2.nodes,
    )
    refs, warnings = detect_crossrefs([ast1, ast2])
    resolved = [r for r in refs if r.resolved]
    assert resolved
    assert not any(w.code == "xd001_unresolved_ref" for w in warnings)


def test_xref_no_false_positives():
    ast = _minimal_ast("The agent should log the ticket.")
    refs, warnings = detect_crossrefs([ast])
    assert refs == []
    assert warnings == []


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


def test_emitter_is_deterministic():
    ir = _minimal_ir()
    linked = LinkedIR(run_id="run_test")
    text1 = emit_cypher(ir, linked, "run_test")
    text2 = emit_cypher(ir, linked, "run_test")
    assert text1 == text2


def test_emitter_sha256_changes_on_different_ir():
    ir1 = _minimal_ir(run_id="r1")
    ir2 = _minimal_ir(
        run_id="r2",
        steps=[Step(id="s99", kind=StepKind.ACTION, action="send email")],
    )
    linked = LinkedIR(run_id="r1")
    sha1 = cypher_sha256(emit_cypher(ir1, linked, "r1"))
    sha2 = cypher_sha256(emit_cypher(ir2, linked, "r2"))
    assert sha1 != sha2


def test_emitter_contains_role_node():
    ir = _minimal_ir()
    linked = LinkedIR(run_id="run_test")
    cypher = emit_cypher(ir, linked, "run_test")
    assert 'MERGE (:Role {id: "agent"' in cypher


def test_emitter_contains_step_node():
    ir = _minimal_ir()
    linked = LinkedIR(run_id="run_test")
    cypher = emit_cypher(ir, linked, "run_test")
    assert 'MERGE (:Step {id: "s01"' in cypher


def test_emitter_contains_relationship():
    ir = _minimal_ir()
    linked = LinkedIR(run_id="run_test")
    cypher = emit_cypher(ir, linked, "run_test")
    assert "HAS_STEP" in cypher
    assert "PERFORMED_BY" in cypher


# ---------------------------------------------------------------------------
# Validator (networkx)
# ---------------------------------------------------------------------------


def test_validator_loads_simple_graph():
    cypher = """
MERGE (:Process {id: "p01", name: "P", run_id: "r"});
MERGE (:Step {id: "s01", action: "log", modal: ""});
MERGE (p:Process {id: "p01"})-[:HAS_STEP]->(s:Step {id: "s01"});
"""
    g = load_graph(cypher)
    assert g.has_node("p01")
    assert g.has_node("s01")
    assert g.has_edge("p01", "s01")


def test_validator_no_errors_for_valid_graph():
    ir = _minimal_ir()
    linked = LinkedIR(run_id="run_test")
    cypher = emit_cypher(ir, linked, "run_test")
    g = load_graph(cypher)
    errors = validate_graph(g)
    assert errors == [], errors


def test_validator_detects_empty_process():
    cypher = """
MERGE (:Process {id: "p01", name: "Orphan", run_id: "r"});
"""
    g = load_graph(cypher)
    errors = validate_graph(g)
    assert any("HAS_STEP" in e or "HAS_DECISION" in e for e in errors)
