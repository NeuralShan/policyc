"""The ``extract`` pipeline stage: extract the SOP IR from ingested DocASTs.

Reads the DocAST produced by the ingest stage, runs the full extraction pipeline, stores the
SopIR, then raises a LangGraph interrupt so the human can review before the link stage continues.
"""

import logging
from typing import Any

from langgraph.types import interrupt

from app.core.llm.gateway import CallContext
from app.extract.service import get_extractor
from app.models import DocumentAST, SopIRRecord
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
        ir = extractor.extract(asts, ctx.run_id, context, progress)
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

    # Pause for human review.  The graph will resume with the reviewer's decision.
    review_decision: dict = interrupt(
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
