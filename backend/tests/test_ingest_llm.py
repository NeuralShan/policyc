"""Layer 1 LLM enrichments with a fake Gemini: OCR cross-check, profile grounding, diagrams,
and the gateway features they rely on (images, throttling, quota fail-fast)."""

import io

import pytest
from langchain_core.exceptions import ModelRateLimitError
from PIL import Image

from app.core.llm.gateway import CallContext, LLMGateway, LLMUnavailable, RateLimiter
from app.ingest.assemble import ParsedDocument, RawItem, Region, assemble
from app.ingest.diagrams import read_diagrams
from app.ingest.ocr_check import PageBlock, PageReading, verify_ocr
from app.ingest.profile import profile_document
from app.schemas.docast import (
    DiagramEdge,
    DiagramGraph,
    DiagramNode,
    DiagramStatus,
    FigureData,
    NodeKind,
    PageInfo,
    TextSource,
)
from tests.conftest import GOLDEN
from tests.fakes import fake_factory, image_count

CTX = CallContext(run_id=None, stage="ingest")
LOTO = GOLDEN / "LOTO-003_scanned_copy_no_text_layer.pdf"


def gateway(services, responder, models=None, **settings):
    s = services.settings.model_copy(update=settings)
    return LLMGateway(s, services.sessions, services.prompts, fake_factory(responder, models))


def ocr_item(text, kind=NodeKind.LIST_ITEM):
    return RawItem(kind=kind, text=text, regions=[Region(page=2)], text_source=TextSource.OCR)


def test_ocr_cross_check_replaces_a_garbled_safety_step(services):
    parsed = ParsedDocument(
        parser="test",
        pages=[PageInfo(page_no=2, width=595, height=842, text_source=TextSource.OCR)],
        items=[
            ocr_item("2 Procedure", NodeKind.HEADING),
            ocr_item("2.2The machine is shut down using its normal stopping procedure."),
            ocr_item("2e c (aot t ) s   ated."),
            ocr_item("2.4 The authorized employee applies a personal lock and tag."),
        ],
    )
    reading = PageReading(
        blocks=[
            PageBlock(kind="text", text="2 Procedure"),
            PageBlock(
                kind="text",
                text="2.2 The machine is shut down using its normal stopping procedure.",
            ),
            PageBlock(
                kind="text",
                text="2.3 All energy sources (electrical, pneumatic, hydraulic) are isolated.",
            ),
            PageBlock(
                kind="text", text="2.4 The authorized employee applies a personal lock and tag."
            ),
        ]
    )
    models = {}
    llm = gateway(services, lambda schema, messages: reading, models)
    checked, warnings = verify_ocr(parsed, LOTO, llm, CTX)

    assert image_count(models[services.settings.model_flash].calls[0]) == 1  # the page image
    texts = [(i.text, i.text_source) for i in checked.items]
    assert texts[1] == (
        "2.2 The machine is shut down using its normal stopping procedure.",
        TextSource.OCR_VERIFIED,
    )
    fixed = checked.items[2]
    assert fixed.text.startswith("2.3 All energy sources") and fixed.text_source == "vision"
    assert fixed.alt_text == "2e c (aot t ) s   ated."
    assert [w.code for w in warnings] == ["ocr_corrected"]
    assert checked.pages[0].text_source == TextSource.OCR_VERIFIED

    ast = assemble(checked, document_id="d", sha256="0" * 64, filename="x", media_type="x")
    assert ast.nodes[2].number == "2.3"


def test_ocr_cross_check_degrades_when_quota_is_exhausted(services):
    def exhausted(schema, messages):
        raise ModelRateLimitError(
            "429 RESOURCE_EXHAUSTED quotaId GenerateRequestsPerDay 'retryDelay': '3600s'"
        )

    parsed = ParsedDocument(
        parser="test",
        pages=[PageInfo(page_no=2, width=595, height=842, text_source=TextSource.OCR)],
        items=[ocr_item("2.3All energy sources are isolated.")],
    )
    llm = gateway(services, exhausted)
    checked, warnings = verify_ocr(parsed, LOTO, llm, CTX)
    assert checked.items[0].text_source == TextSource.OCR  # unchanged, still marked unverified
    assert [w.code for w in warnings] == ["ocr_unverified"]
    # The flash model is now blocked: the next call fails fast without reaching the API.
    with pytest.raises(LLMUnavailable, match="daily quota"):
        llm.structured("ocr_second_reading", PageReading, images=[b"\x89PNG-other"])
    from sqlalchemy import select

    from app.models import LLMCall

    with services.sessions() as session:
        errors = [c.error for c in session.scalars(select(LLMCall).order_by(LLMCall.id))]
    assert errors[-1] == "skipped: daily quota exhausted"


def test_profile_drops_values_without_evidence(services):
    ast = assemble(
        ParsedDocument(
            parser="t",
            items=[
                RawItem(kind=NodeKind.TITLE, text="Expense Policy"),
                RawItem(kind=NodeKind.PARAGRAPH, text="Version 3.0"),
            ],
            furniture=["EXP-001 · Effective date: 01-Jul-2026"],
        ),
        document_id="d",
        sha256="0" * 64,
        filename="exp.pdf",
        media_type="application/pdf",
    )

    def responder(schema, messages):
        return schema(
            doc_class="normative",
            rationale="Rules and limits.",
            title={"value": "Expense Policy", "quote": "Expense Policy"},
            version={"value": "3.0", "quote": "Version 3.0"},
            effective_date={"value": "2026-07-01", "quote": "Effective date: 01-Jul-2026"},
            owner={"value": "Finance", "quote": "Owner: Finance Department"},  # not in document
        )

    models = {}
    profile, warnings = profile_document(ast, gateway(services, responder, models), CTX)
    assert models.keys() == {services.settings.model_lite}  # profiling uses the lite tier
    assert profile.doc_class == "normative"
    assert (profile.version.value, profile.effective_date.value) == ("3.0", "2026-07-01")
    assert profile.owner is None
    assert [w.code for w in warnings] == ["profile_ungrounded"]


def test_diagram_reading_keeps_valid_edges_only(services):
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buffer, format="PNG")
    buffer.seek(0)
    key = services.storage.put("figures", buffer, ".png", max_bytes=10_000_000).key
    ast = assemble(
        ParsedDocument(
            parser="t",
            items=[
                RawItem(
                    kind=NodeKind.FIGURE,
                    text="Figure 1: Access request flow",
                    figure=FigureData(image_key=key, diagram_status=DiagramStatus.PENDING),
                ),
                RawItem(
                    kind=NodeKind.FIGURE,
                    text="",
                    figure=FigureData(image_key=key, diagram_status=DiagramStatus.SKIPPED),
                ),
            ],
        ),
        document_id="d",
        sha256="0" * 64,
        filename="x.docx",
        media_type="x",
    )
    graph = DiagramGraph(
        nodes=[
            DiagramNode(id="d1", label="Submit request", kind="start"),
            DiagramNode(id="d2", label="Approve?", kind="decision"),
        ],
        edges=[DiagramEdge(source="d1", target="d2"), DiagramEdge(source="d2", target="d9")],
    )
    calls = []

    def responder(schema, messages):
        calls.append(messages)
        return schema(is_process_diagram=True, description="Flowchart.", diagram=graph)

    out, warnings = read_diagrams(ast, services.storage, gateway(services, responder), CTX)
    assert len(calls) == 1  # the skipped (logo-sized) figure is not sent
    figure = out.nodes[0].figure
    assert figure.diagram_status == DiagramStatus.EXTRACTED
    assert [(e.source, e.target) for e in figure.diagram.edges] == [("d1", "d2")]
    assert [w.code for w in warnings] == ["diagram_edges_dropped"]


def test_rate_limiter_spaces_out_calls():
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(round(seconds, 3))
        now[0] += seconds

    limiter = RateLimiter(2, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        limiter.acquire()
    assert sleeps == [60.0]  # the third call waits for the first to age out
    RateLimiter(0, clock=lambda: now[0], sleep=sleep).acquire()  # 0 = unlimited
    assert sleeps == [60.0]


def test_images_are_part_of_the_cache_key(services):
    calls = []

    def responder(schema, messages):
        calls.append(image_count(messages))
        return schema(is_process_diagram=False, description="x")

    llm = gateway(services, responder)
    from app.ingest.diagrams import DiagramReply

    for png in (b"\x89PNG-a", b"\x89PNG-a", b"\x89PNG-b"):
        llm.structured("diagram_reading", DiagramReply, {"caption": "c"}, images=[png])
    assert calls == [1, 1]  # second call with the same image was a cache hit
