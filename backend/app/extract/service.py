"""Extractor: top-level service for Layer 2 (semantic extraction).

Orchestrates: symbol pass → structure pass → grounding check → diagram merge → IR assembly.
"""

import logging
import re
from typing import Any

from app.core.llm.gateway import CallContext, LLMGateway
from app.core.services import Services
from app.extract.diagram_merge import check_diagram_vs_text
from app.extract.grounding import check_grounding
from app.extract.flow import finalize_flow, normalize_structure
from app.extract.flowpass import apply_flow_pass
from app.extract.structure import clause_texts, extract_structure, section_headings
from app.extract.symbols import extract_symbols
from app.schemas.docast import DiagramStatus, DocAST
from app.schemas.ir_sop import ExtractionWarning, ReviewStatus, SopIR, SymbolTable

log = logging.getLogger(__name__)


def document_key(filename: str) -> str:
    """Stable key for a document across its revisions (ignores ``_revN`` and the extension)."""
    return re.sub(r"(_rev\d+)?\.[A-Za-z0-9]+$", "", filename)


def get_extractor(services: Services) -> "Extractor":
    return services.singleton("extractor", lambda: Extractor(services))


class Extractor:
    def __init__(self, services: Services) -> None:
        self._services = services

    def extract(
        self,
        asts: list[DocAST],
        run_id: str,
        context: CallContext,
        progress=None,
        base_ir: SopIR | None = None,
    ) -> SopIR:
        """Run the full extraction pipeline over all documents in the run.

        With ``base_ir`` (a revision of an earlier run) the compile is incremental: symbols, the
        extraction of every unchanged section and the flow-pass reply are replayed, and only
        sections whose text changed go back to the model.
        """
        llm: LLMGateway = self._services.llm

        all_warnings: list[ExtractionWarning] = []
        symbols = SymbolTable()
        raw_sections: dict[str, dict] = {}
        flow_replies: dict = {}

        # --- Symbol pass (over all documents) ---
        if base_ir is not None and base_ir.symbols.all_ids():
            symbols = base_ir.symbols.model_copy(deep=True)
            if progress:
                progress("symbols: reused from the previous revision")
        for ast in asts if not (base_ir is not None and base_ir.symbols.all_ids()) else []:
            if progress:
                progress(f"symbol pass: {ast.filename}")
            doc_symbols, sym_warnings = extract_symbols(ast, llm, context)
            all_warnings.extend(sym_warnings)
            # Merge symbol tables (later docs add to earlier ones)
            symbols.roles.extend(r for r in doc_symbols.roles if r.id not in symbols.all_ids())
            symbols.artifacts.extend(
                a for a in doc_symbols.artifacts if a.id not in symbols.all_ids()
            )
            symbols.systems.extend(s for s in doc_symbols.systems if s.id not in symbols.all_ids())
            symbols.terms.extend(t for t in doc_symbols.terms if t.id not in symbols.all_ids())

        log.info(
            "symbol pass: %d roles, %d artifacts, %d systems, %d terms",
            len(symbols.roles),
            len(symbols.artifacts),
            len(symbols.systems),
            len(symbols.terms),
        )

        # --- Structure pass (one process per procedural document) ---
        from app.schemas.docast import DocClass

        processes = []
        for ast in asts:
            # Only purely descriptive documents are skipped. A "normative" policy (rules, limits,
            # approvals) is exactly what PolicyC compiles, and the profiler often files SOPs there.
            if ast.profile and ast.profile.doc_class == DocClass.DESCRIPTIVE:
                log.info(
                    "skipping structure pass for %s (class=%s)", ast.filename, ast.profile.doc_class
                )
                continue
            if progress:
                progress(f"structure pass: {ast.filename}")
            doc_key = document_key(ast.filename)
            raw_sections[doc_key] = {}
            process, struct_warnings = extract_structure(
                ast,
                symbols,
                llm,
                context,
                reuse=(base_ir.raw_sections.get(doc_key) if base_ir else None),
                record=raw_sections[doc_key],
            )
            all_warnings.extend(struct_warnings)

            # --- Flow pass (LLM, whole document) then deterministic flow normaliser ---
            if progress:
                progress(f"flow pass: {ast.filename}")
            headings = section_headings(ast)
            clauses = clause_texts(ast)
            all_warnings.extend(normalize_structure(process, symbols, headings, clauses))
            all_warnings.extend(
                apply_flow_pass(
                    ast,
                    process,
                    symbols,
                    llm,
                    context,
                    reuse=(base_ir.flow_replies.get(doc_key) if base_ir else None),
                    record=flow_replies,
                    key=doc_key,
                )
            )
            all_warnings.extend(normalize_structure(process, symbols, headings, clauses))
            all_warnings.extend(finalize_flow(process, headings))

            # --- Grounding check ---
            grounding_warnings = check_grounding(process, ast)
            all_warnings.extend(grounding_warnings)

            # --- Diagram merge ---
            for node in ast.nodes:
                if (
                    node.figure
                    and node.figure.diagram_status == DiagramStatus.EXTRACTED
                    and node.figure.diagram
                ):
                    xd_warnings = check_diagram_vs_text(ast, process, node.figure.diagram)
                    all_warnings.extend(xd_warnings)

            processes.append(process)

        stats: dict[str, int] = {
            "roles": len(symbols.roles),
            "artifacts": len(symbols.artifacts),
            "systems": len(symbols.systems),
            "terms": len(symbols.terms),
            "processes": len(processes),
            "steps": sum(len(p.steps) for p in processes),
            "decisions": sum(len(p.decisions) for p in processes),
            "warnings": len(all_warnings),
        }

        ir = SopIR(
            run_id=run_id,
            document_ids=[ast.document_id for ast in asts],
            symbols=symbols,
            processes=processes,
            warnings=all_warnings,
            review_status=ReviewStatus.PENDING,
            extraction_stats=stats,
            raw_sections=raw_sections,
            flow_replies=flow_replies,
        )
        return ir

    def save(self, ir: SopIR) -> "Any":
        """Persist the SopIR to the database and return the ORM record."""
        from app.models import SopIRRecord

        with self._services.sessions() as session:
            record = SopIRRecord(
                run_id=ir.run_id,
                document_ids=ir.document_ids,
                ir=ir.model_dump(mode="json"),
                review_status=ir.review_status,
                stats=ir.extraction_stats,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def load(self, run_id: str) -> SopIR | None:
        """Load the latest SopIR for a run from the database."""
        from sqlalchemy import select

        from app.models import SopIRRecord

        with self._services.sessions() as session:
            stmt = (
                select(SopIRRecord)
                .where(SopIRRecord.run_id == run_id)
                .order_by(SopIRRecord.created_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            if record is None:
                return None
            return SopIR.model_validate(record.ir)

    def update_review(self, run_id: str, review_status: ReviewStatus, overrides: dict) -> bool:
        """Update the review status and overrides for an IR record.  Returns True if found."""
        from sqlalchemy import select

        from app.models import SopIRRecord

        with self._services.sessions() as session:
            stmt = (
                select(SopIRRecord)
                .where(SopIRRecord.run_id == run_id)
                .order_by(SopIRRecord.created_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            if record is None:
                return False
            record.review_status = review_status
            # Merge overrides into the stored IR
            ir_data = record.ir.copy()
            ir_data["review_status"] = review_status
            ir_data["review_overrides"] = overrides
            record.ir = ir_data
            session.commit()
            return True
