"""Ingestion of one document: parse (cached) -> OCR cross-check -> assemble -> diagrams -> profile.

Only the deterministic parse is cached here. LLM enrichments go through the gateway's response
cache, so re-ingesting costs nothing once they succeed, and anything that failed (for example on an
exhausted free-tier quota) is simply attempted again next run.
"""

import hashlib
import logging
from collections.abc import Callable
from pathlib import Path

from app.core.llm.gateway import CallContext
from app.core.services import Services
from app.ingest.assemble import ParsedDocument, assemble
from app.ingest.diagrams import read_diagrams
from app.ingest.capabilities import LITE_MESSAGE, can_parse, full_parsing
from app.ingest.docling_parser import DoclingParser
from app.ingest.ocr_check import verify_ocr
from app.ingest.profile import profile_document
from app.ingest.text_parser import PARSER_NAME as TEXT_PARSER
from app.ingest.text_parser import parse_text
from app.models import Document, DocumentAST, ParseCache
from app.schemas.docast import DiagramStatus, DocAST, IngestWarning, NodeKind, TextSource

log = logging.getLogger(__name__)
Progress = Callable[[str], None]


def ast_stats(ast: DocAST) -> dict:
    figures = [n for n in ast.nodes if n.kind == NodeKind.FIGURE]
    return {
        "pages": len(ast.pages),
        "nodes": len(ast.nodes),
        "headings": sum(n.kind in (NodeKind.TITLE, NodeKind.HEADING) for n in ast.nodes),
        "tables": sum(n.kind == NodeKind.TABLE for n in ast.nodes),
        "figures": len(figures),
        "diagrams": sum(
            f.figure is not None and f.figure.diagram_status == DiagramStatus.EXTRACTED
            for f in figures
        ),
        "ocr_pages": sum(p.text_source != TextSource.NATIVE for p in ast.pages),
        "vision_corrected": sum(n.text_source == TextSource.VISION for n in ast.nodes),
        "warnings": len(ast.warnings),
        "doc_class": ast.profile.doc_class if ast.profile else None,
    }


class Ingestor:
    def __init__(self, services: Services):
        self.services = services
        self.docling = DoclingParser(services.settings, services.storage)

    def source_path(self, document: Document) -> Path:
        return self.services.storage.path(document.storage_key)

    def parser_name(self, document: Document) -> str:
        if document.media_type == "text/plain" or (
            document.media_type == "text/markdown" and not full_parsing()
        ):
            return TEXT_PARSER  # lite mode reads Markdown with the built-in text parser
        if not can_parse(document.media_type):
            raise RuntimeError(LITE_MESSAGE)
        return self.docling.name

    def parse(self, document: Document) -> ParsedDocument:
        parser = self.parser_name(document)
        key = hashlib.sha256(f"{document.sha256}|{parser}".encode()).hexdigest()
        with self.services.sessions() as session:
            cached = session.get(ParseCache, key)
            if cached is not None:
                return ParsedDocument.model_validate(cached.payload)
        path = self.source_path(document)
        if parser == TEXT_PARSER:
            parsed = parse_text(path)
        else:
            parsed = self.docling.parse(path, document.media_type)
        with self.services.sessions() as session:
            session.merge(
                ParseCache(
                    key=key,
                    sha256=document.sha256,
                    parser=parser,
                    payload=parsed.model_dump(mode="json"),
                )
            )
            session.commit()
        return parsed

    def ingest(self, document: Document, context: CallContext, progress: Progress) -> DocAST:
        settings, llm = self.services.settings, self.services.llm
        progress("parsing")
        parsed = self.parse(document)
        warnings: list[IngestWarning] = []

        ocr_pages = [p.page_no for p in parsed.pages if p.text_source == TextSource.OCR]
        if ocr_pages and settings.ocr_vision_check:
            progress(f"cross-checking OCR on page(s) {', '.join(map(str, ocr_pages))}")
            parsed, found = verify_ocr(parsed, self.source_path(document), llm, context)
            warnings += found
        elif ocr_pages:
            warnings.append(
                IngestWarning(
                    code="ocr_single_reader",
                    message="scanned pages read by local OCR only (vision cross-check disabled)",
                )
            )

        ast = assemble(
            parsed,
            document_id=document.id,
            sha256=document.sha256,
            filename=document.filename,
            media_type=document.media_type,
        )
        if any(n.figure and n.figure.diagram_status == DiagramStatus.PENDING for n in ast.nodes):
            progress("reading diagrams")
            ast, found = read_diagrams(ast, self.services.storage, llm, context)
            warnings += found
        progress("profiling")
        profile, found = profile_document(ast, llm, context)
        warnings += found
        return ast.model_copy(update={"profile": profile, "warnings": warnings})

    def save(self, ast: DocAST, run_id: str | None) -> DocumentAST:
        with self.services.sessions() as session:
            record = DocumentAST(
                document_id=ast.document_id,
                run_id=run_id,
                parser=ast.parser,
                complete=ast.is_complete,
                stats=ast_stats(ast),
                ast=ast.model_dump(mode="json"),
            )
            session.add(record)
            session.commit()
            return record


def get_ingestor(services: Services) -> Ingestor:
    """One Ingestor per Services instance: Docling loads its models once and keeps them."""
    return services.singleton("ingestor", lambda: Ingestor(services))
