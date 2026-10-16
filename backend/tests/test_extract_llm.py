"""Layer 2 extraction tests using the fake LLM (no network calls)."""


from app.core.llm.gateway import CallContext
from app.extract.structure import extract_structure
from app.extract.symbols import extract_symbols, symbol_table_json
from app.schemas.docast import DocAST, DocNode, NodeKind
from app.schemas.ir_sop import ArtifactRef, ReviewStatus, RoleRef, SymbolTable, SystemRef
from app.schemas.provenance import SourceSpan
from tests.fakes import default_responder, fake_factory

SOP_TEXT = """\
## 1. Roles
- **Agent**: handles requests.

## 2. Procedure
1. The Agent shall log the complaint in CRM within 1 business day.
2. The Agent completes the Form.
"""


def _make_ast(text: str = SOP_TEXT) -> DocAST:
    nodes = [
        DocNode(
            id=f"n{i:04}",
            kind=NodeKind.HEADING if line.startswith("#") else NodeKind.PARAGRAPH,
            level=1 if line.startswith("## ") else None,
            text=line.strip("# ").strip(),
            spans=[
                SourceSpan(
                    document_id="doc_test",
                    char_start=text.find(line.strip("# ").strip()),
                    char_end=text.find(line.strip("# ").strip()) + len(line.strip("# ").strip()),
                    quote=line.strip("# ").strip(),
                )
            ],
        )
        for i, line in enumerate(text.splitlines(), 1)
        if line.strip()
    ]
    return DocAST(
        document_id="doc_test",
        sha256="abc123",
        filename="SOP-CS-014.md",
        media_type="text/markdown",
        parser="test",
        text=text,
        nodes=nodes,
    )


# ---------------------------------------------------------------------------
# Symbol pass
# ---------------------------------------------------------------------------


def test_symbol_pass_returns_roles_artifacts_systems(services):
    ast = _make_ast()
    llm = services.llm
    table, warnings = extract_symbols(ast, llm, CallContext())
    assert len(table.roles) >= 1
    assert table.roles[0].id == "agent"
    assert table.roles[0].name == "Agent"


def test_symbol_pass_ungrounded_quote_emits_warning(settings, tmp_path):
    from app.core.db import run_migrations
    from app.core.services import Services

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(settings.resolved_database_url)

    def bad_responder(schema, messages):
        name = schema.__name__
        if name == "SymbolReply":
            return schema(
                roles=[{"id": "agent", "name": "Agent", "quote": "XYZNOTFOUNDATALL"}],
                artifacts=[],
                systems=[],
                terms=[],
            )
        return default_responder(schema, messages)

    bad_services = Services.build(settings, fake_factory(bad_responder))
    ast = _make_ast()
    llm = bad_services.llm
    _, warnings = extract_symbols(ast, llm, CallContext())
    bad_services.engine.dispose()
    assert any(w.code == "symbol_ungrounded" for w in warnings)


def test_symbol_table_json_is_valid_json(services):
    import json

    ast = _make_ast()
    llm = services.llm
    table, _ = extract_symbols(ast, llm, CallContext())
    data = json.loads(symbol_table_json(table))
    assert "roles" in data
    assert "artifacts" in data


# ---------------------------------------------------------------------------
# Structure pass
# ---------------------------------------------------------------------------


def test_structure_pass_extracts_steps(services):
    ast = _make_ast()
    llm = services.llm
    symbols = SymbolTable(
        roles=[RoleRef(id="agent", name="Agent")],
        artifacts=[ArtifactRef(id="form", name="Form")],
        systems=[SystemRef(id="crm", name="CRM")],
    )
    process, warnings = extract_structure(ast, symbols, llm, CallContext())
    assert process.document_id == "doc_test"
    assert len(process.steps) >= 1
    assert process.steps[0].action == "log the complaint"


def test_structure_pass_unknown_role_id_emits_warning(settings):
    from app.core.db import run_migrations
    from app.core.services import Services

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(settings.resolved_database_url)

    def bad_responder(schema, messages):
        name = schema.__name__
        if name == "StructureReply":
            return schema(
                steps=[
                    {
                        "id": "s01",
                        "kind": "action",
                        "actor_role_id": "nonexistent_role",
                        "modal": "shall",
                        "action": "do something",
                        "source_quote": "Agent",
                    }
                ],
                decisions=[],
                transitions=[],
                references=[],
            )
        return default_responder(schema, messages)

    bad_services = Services.build(settings, fake_factory(bad_responder))
    ast = _make_ast()
    llm = bad_services.llm
    symbols = SymbolTable()
    _, warnings = extract_structure(ast, symbols, llm, CallContext())
    bad_services.engine.dispose()
    assert any(w.code == "validation_error" for w in warnings)


# ---------------------------------------------------------------------------
# Full Extractor service
# ---------------------------------------------------------------------------


def test_extractor_end_to_end(services):
    ast = _make_ast()

    from app.extract.service import get_extractor

    extractor = get_extractor(services)
    ir = extractor.extract([ast], "run_test", CallContext())
    assert ir.run_id == "run_test"
    assert len(ir.processes) == 1
    assert ir.review_status == ReviewStatus.PENDING
    assert ir.extraction_stats["steps"] >= 1


def test_extractor_save_and_load(services):
    ast = _make_ast()
    from app.extract.service import get_extractor

    extractor = get_extractor(services)
    ir = extractor.extract([ast], "run_save_test", CallContext())

    # Need a CompileRun in the DB for the FK constraint
    from app.models import CompileRun, Project

    with services.sessions() as session:
        proj = Project(name="p")
        session.add(proj)
        session.flush()
        run = CompileRun(id="run_save_test", project_id=proj.id, document_ids=["doc_test"])
        session.add(run)
        session.commit()

    record = extractor.save(ir)
    assert record.id.startswith("ir_")

    loaded = extractor.load("run_save_test")
    assert loaded is not None
    assert loaded.run_id == "run_save_test"
    assert loaded.review_status == ReviewStatus.PENDING


def test_extractor_update_review(services):
    ast = _make_ast()
    from app.extract.service import get_extractor

    extractor = get_extractor(services)
    ir = extractor.extract([ast], "run_review_test", CallContext())

    from app.models import CompileRun, Project

    with services.sessions() as session:
        proj = Project(name="p")
        session.add(proj)
        session.flush()
        run = CompileRun(id="run_review_test", project_id=proj.id, document_ids=["doc_test"])
        session.add(run)
        session.commit()

    extractor.save(ir)
    ok = extractor.update_review("run_review_test", ReviewStatus.APPROVED, {})
    assert ok

    loaded = extractor.load("run_review_test")
    assert loaded.review_status == ReviewStatus.APPROVED
