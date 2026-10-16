"""Docling over every golden document (slow: model loading and OCR take minutes).

uv run pytest -m slow
"""

import pytest

from app.core.config import Settings
from app.core.db import run_migrations
from app.core.services import Services
from app.eval.golden import load_cases
from app.eval.ingest_report import golden_files, transient_document
from app.ingest.assemble import assemble
from app.ingest.service import get_ingestor
from app.ingest.span_check import check_spans
from app.schemas.docast import DiagramStatus, DocAST, NodeKind, TextSource
from tests.conftest import GOLDEN
from tests.fakes import fake_factory

pytestmark = pytest.mark.slow
FILES = golden_files(GOLDEN)


@pytest.fixture(scope="module")
def services(tmp_path_factory):
    settings = Settings(_env_file=None, data_dir=tmp_path_factory.mktemp("golden") / "data")
    settings.data_dir.mkdir(parents=True)
    run_migrations(settings.resolved_database_url)
    built = Services.build(settings, fake_factory())
    yield built
    built.engine.dispose()


@pytest.fixture(scope="module")
def parsed(services) -> dict[str, tuple[DocAST, object]]:
    ingestor = get_ingestor(services)
    out = {}
    for path in FILES:
        doc = transient_document(services, path)
        ast = assemble(
            ingestor.parse(doc),
            document_id=doc.id,
            sha256=doc.sha256,
            filename=doc.filename,
            media_type=doc.media_type,
        )
        out[path.name] = (ast, services.storage.path(doc.storage_key))
    return out


@pytest.mark.parametrize("name", [p.name for p in FILES])
def test_structure_invariants(parsed, name):
    ast, _ = parsed[name]
    assert ast.nodes, "nothing parsed"
    pages = {p.page_no: p for p in ast.pages}
    seen: dict[str, NodeKind] = {}
    for node in ast.nodes:
        for span in node.spans:
            assert ast.text[span.char_start : span.char_end] == span.quote == node.text
            if span.bbox is not None:
                page = pages[span.page]
                assert 0 <= span.bbox.x0 <= span.bbox.x1 <= page.width + 1
                assert 0 <= span.bbox.y0 <= span.bbox.y1 <= page.height + 1
        if node.parent_id is not None:
            assert seen[node.parent_id] in (NodeKind.TITLE, NodeKind.HEADING)
        seen[node.id] = node.kind


@pytest.mark.parametrize(
    "name", [p.name for p in FILES if p.suffix == ".pdf" and "scanned" not in p.name]
)
def test_span_accuracy_on_text_pdfs(parsed, name):
    ast, path = parsed[name]
    report = check_spans(ast, path)
    assert report.checked >= 20
    assert report.accuracy >= 0.95, report.failures[:3]


def test_every_golden_quote_is_in_the_parsed_text(parsed):
    squash = " ".join
    for case in load_cases(GOLDEN):
        for finding in case.manifest.expected_findings:
            if finding.quote:
                ast, _ = parsed[finding.document]
                assert squash(finding.quote.split()) in squash(ast.text.split()), finding


def test_numbered_clauses_in_purchase_procedure(parsed):
    ast, _ = parsed["PRC-006_Purchase_Requisition_and_PO_Approval_Procedure_v3.0.pdf"]
    numbers = [n.number for n in ast.nodes if n.kind == NodeKind.LIST_ITEM]
    assert numbers == ["1.1", "2.1", "3.1", "3.2", "3.3", "4.1", "4.2", "4.3", "4.4", "5.1", "5.2"]
    assert sum(n.kind == NodeKind.TABLE for n in ast.nodes) == 4
    assert ast.nodes[0].kind == NodeKind.FIGURE  # logo, skipped for diagram analysis
    assert ast.nodes[0].figure.diagram_status == DiagramStatus.SKIPPED
    assert any("Page 2 of 2" in f for f in ast.furniture)


def test_scanned_pdf_is_ocrd(parsed):
    ast, _ = parsed["LOTO-003_scanned_copy_no_text_layer.pdf"]
    assert [p.text_source for p in ast.pages] == [TextSource.OCR, TextSource.OCR]
    numbers = [n.number for n in ast.nodes if n.kind == NodeKind.LIST_ITEM]
    assert {"2.1", "2.2", "2.4", "2.5", "4.3"} <= set(numbers)
    assert all(n.text_source == TextSource.OCR for n in ast.nodes if n.kind != NodeKind.FIGURE)


def test_docx_figure_is_queued_for_diagram_reading(parsed):
    ast, _ = parsed["SOP-IT-021.docx"]
    figures = [n for n in ast.nodes if n.kind == NodeKind.FIGURE]
    assert len(figures) == 1
    assert figures[0].text == "Figure 1: Access request flow"
    assert figures[0].figure.image_key and figures[0].figure.diagram_status == "pending"
    assert [n.number for n in ast.nodes if n.text.startswith("2.")][:5] == [
        "2.1",
        "2.2",
        "2.3",
        "2.4",
        "2.5",
    ]
