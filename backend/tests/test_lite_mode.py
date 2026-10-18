"""Lightweight deployment (no Docling): text/markdown parse, PDF/DOCX are refused politely."""

import pytest

from app.ingest import capabilities, service


@pytest.fixture
def lite(monkeypatch):
    monkeypatch.setattr(capabilities, "full_parsing", lambda: False)
    monkeypatch.setattr(service, "full_parsing", lambda: False)


def test_capabilities_in_lite_mode(lite):
    assert capabilities.can_parse("text/markdown") and capabilities.can_parse("text/plain")
    assert not capabilities.can_parse("application/pdf")
    assert not capabilities.can_parse("application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def test_upload_pdf_is_rejected_with_a_clear_message_and_md_is_accepted(client, lite):
    project = client.post("/api/projects", json={"name": "p", "description": ""}).json()["id"]
    bad = client.post(f"/api/projects/{project}/documents", files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
    assert bad.status_code == 415 and "lightweight mode" in bad.json()["detail"]
    ok = client.post(f"/api/projects/{project}/documents", files={"files": ("a.md", b"1 Purpose\n1.1 Do it.\n", "text/markdown")})
    assert ok.status_code == 201


def test_markdown_is_parsed_with_the_text_parser_in_lite_mode(lite, services):
    from app.models import Document

    doc = Document(project_id="p", filename="a.md", media_type="text/markdown", sha256="x", size_bytes=1, storage_key="k")
    ingestor = service.Ingestor(services)
    assert ingestor.parser_name(doc) == service.TEXT_PARSER


def test_me_reports_the_parsing_mode(client):
    assert client.get("/api/me").json()["parsing"] in {"full", "lite"}
