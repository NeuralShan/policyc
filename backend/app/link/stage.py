"""The ``link`` pipeline stage: entity resolution, cross-reference detection, .cypher emission."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.link.service import get_linker
from app.models import DocumentAST, SopIRRecord
from app.pipeline.graph import CompileState, StageContext
from app.schemas.docast import DocAST
from app.schemas.ir_sop import SopIR

log = logging.getLogger(__name__)


def _load_sop_ir(services, run_id: str) -> tuple[SopIR, str] | tuple[None, None]:
    """Load the latest approved SopIRRecord for the run."""
    with services.sessions() as session:
        stmt = (
            select(SopIRRecord)
            .where(SopIRRecord.run_id == run_id)
            .order_by(SopIRRecord.created_at.desc())
            .limit(1)
        )
        record = session.scalars(stmt).first()
        if record is None:
            return None, None
        return SopIR.model_validate(record.ir), record.id


def _load_asts(state: CompileState, services) -> list[DocAST]:
    asts: list[DocAST] = []
    with services.sessions() as session:
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


def run_link(state: CompileState, ctx: StageContext) -> dict[str, Any]:
    linker = get_linker(ctx.services)

    ir, sop_ir_id = _load_sop_ir(ctx.services, ctx.run_id)
    if ir is None:
        raise RuntimeError("no approved SopIR found for this run; run extract first")

    asts = _load_asts(state, ctx.services)
    if not asts:
        raise RuntimeError("no DocASTs available for linking")

    ctx.report(f"resolving entities across {len(asts)} document(s)")
    linked, cypher_text = linker.link(asts, ir, ctx.run_id, sop_ir_id or "")

    sha_short = linked.cypher_sha256[:12] if linked.cypher_sha256 else "?"
    ctx.report(
        f"{linked.stats.nodes} nodes  {linked.stats.edges} edges  "
        f"{linked.stats.merges} merge(s)  sha256={sha_short}…"
    )

    linker.save(linked, cypher_text)

    return {
        "linked_ir_id": None,  # filled after save; stats are enough for the run artifact
        "nodes": linked.stats.nodes,
        "edges": linked.stats.edges,
        "merges": linked.stats.merges,
        "cross_refs": linked.stats.cross_refs,
        "unresolved_refs": linked.stats.unresolved_refs,
        "warnings": linked.stats.warnings,
        "cypher_sha256": linked.cypher_sha256,
        "summary": (
            f"{linked.stats.nodes} graph nodes, {linked.stats.edges} edges, "
            f"{linked.stats.merges} entity merge(s)"
        ),
    }
