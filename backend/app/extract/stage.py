"""The ``extract`` pipeline stage: extract the SOP IR from ingested DocASTs.

Reads the DocAST produced by the ingest stage, runs the full extraction pipeline, stores the
SopIR, then raises a LangGraph interrupt so the human can review before the link stage continues.
"""

import logging
from typing import Any

from langgraph.types import interrupt

from app.core.llm.gateway import CallContext
from app.extract.service import get_extractor
from app.models import CompileRun, DocumentAST, SopIRRecord
from app.pipeline.graph import CompileState, StageContext
from app.schemas.docast import DocAST
from app.schemas.ir_sop import ReviewStatus

log = logging.getLogger(__name__)


def _load_ir_record(services, run_id: str):
    """Return the latest SopIRRecord for a run, or None if none exists yet."""
    from sqlalchemy import select


    with services.sessions() as session:
        stmt = (
            select(SopIRRecord)
            .where(SopIRRecord.run_id == run_id)
            .order_by(SopIRRecord.created_at.desc())
            .limit(1)
        )
        return session.scalars(stmt).first()


def _load_asts(state: CompileState, ctx: StageContext) -> list[DocAST]:
    """Load the latest DocAST for every document in the run."""
    from sqlalchemy import select

    asts: list[DocAST] = []
    with ctx.services.sessions() as session:
        for doc_id in state["document_ids"]:
            stmt = (
                select(DocumentAST)
                .where(DocumentAST.document_id == doc_id)
                .order_by(DocumentAST.created_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            if record is None:
                log.warning("no DocAST for document %s; skipping", doc_id)
                continue
            asts.append(DocAST.model_validate(record.ast))
    return asts


def run_extract(state: CompileState, ctx: StageContext) -> dict[str, Any]:
    extractor = get_extractor(ctx.services)
    context = CallContext(run_id=ctx.run_id, stage=ctx.stage.key)

    # Idempotent: on LangGraph resume, the node is re-called from the top.
    # Re-use the existing IR record instead of extracting again.
    existing_record = _load_ir_record(ctx.services, ctx.run_id)
    if existing_record is None:
        asts = _load_asts(state, ctx)
        if not asts:
            raise RuntimeError("no DocASTs available for extraction")

        def progress(msg: str) -> None:
            ctx.report(msg)

        ctx.report(f"extracting from {len(asts)} document(s)")
        base_ir = None
        with ctx.services.sessions() as session:
            run_row = session.get(CompileRun, ctx.run_id)
            base_run_id = run_row.base_run_id if run_row else None
        if base_run_id:
            base_ir = extractor.load(base_run_id)  # incremental recompile of a revision
        ir = extractor.extract(asts, ctx.run_id, context, progress, base_ir=base_ir)
        if not any(p.steps for p in ir.processes):
            raise RuntimeError(
                "No procedure steps were found in the document. PolicyC compiles procedures and "
                "policies (who does what, in which order, under which conditions); this text "
                "looks purely descriptive."
            )
        failed = [w for w in ir.warnings if w.code == "structure_pass_failed"]
        if failed:
            # A section that could not be read would silently disappear from the model, and every
            # downstream result (including a "fixed" diff) would be misleading: stop instead.
            raise RuntimeError(
                f"Extraction failed for {len(failed)} section(s) ({failed[0].message}). "
                "Nothing was analysed, because partial results would be misleading. "
                "Re-run once the model is available."
            )
        existing_record = extractor.save(ir)
        stats = ir.extraction_stats
    else:
        stats = existing_record.stats or {}

    ctx.report(
        f"{stats.get('steps', 0)} steps, {stats.get('decisions', 0)} decisions, "
        f"{stats.get('warnings', 0)} warning(s) — awaiting human review"
    )

    record = existing_record
    ir_warnings = record.ir.get("warnings", [])

    # Pause for human review unless the run was started with auto_approve.
    # The graph resumes with the reviewer's decision.
    review_decision: dict = {"approved": True, "overrides": {}} if state.get("auto_approve") else interrupt(
        {
            "ir_id": record.id,
            "run_id": ctx.run_id,
            "stats": stats,
            "warnings": ir_warnings,
            "message": (
                "Review the extracted SOP IR.  Approve to continue, or Reject to re-extract."
            ),
        }
    )

    approved = review_decision.get("approved", False)
    overrides = review_decision.get("overrides", {})

    if not approved:
        raise RuntimeError("IR rejected by reviewer; re-run needed")

    # Persist the approval
    extractor.update_review(ctx.run_id, ReviewStatus.APPROVED, overrides)

    return {
        "ir_id": record.id,
        "review_status": ReviewStatus.APPROVED,
        "summary": (
            f"{stats.get('steps', 0)} steps, {stats.get('decisions', 0)} decisions extracted"
        ),
        **stats,
    }
