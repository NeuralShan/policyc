"""The ``ingest`` pipeline stage: every document in the run becomes a DocAST."""

import logging
from typing import Any

from app.core.llm.gateway import CallContext
from app.ingest.service import ast_stats, get_ingestor
from app.models import Document
from app.pipeline.graph import CompileState, StageContext

log = logging.getLogger(__name__)


def run_ingest(state: CompileState, ctx: StageContext) -> dict[str, Any]:
    ingestor = get_ingestor(ctx.services)
    context = CallContext(run_id=ctx.run_id, stage=ctx.stage.key)
    doc_ids = state["document_ids"]
    results: list[dict[str, Any]] = []

    for i, doc_id in enumerate(doc_ids, start=1):
        with ctx.services.sessions() as session:
            document = session.get(Document, doc_id)
        if document is None:
            results.append({"document_id": doc_id, "error": "document no longer exists"})
            continue
        label = f"[{i}/{len(doc_ids)}] {document.filename}"
        try:
            ast = ingestor.ingest(
                document, context, lambda msg, label=label: ctx.report(f"{label}: {msg}")
            )
            record = ingestor.save(ast, ctx.run_id)
        except Exception as exc:
            log.exception("ingest failed for %s", doc_id)
            ctx.report(f"{label}: failed: {exc}")
            results.append(
                {
                    "document_id": doc_id,
                    "filename": document.filename,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        results.append(
            {
                "document_id": doc_id,
                "filename": document.filename,
                "ast_id": record.id,
                "complete": record.complete,
                **ast_stats(ast),
            }
        )
        ctx.report(f"{label}: {record.stats['nodes']} nodes, {len(ast.warnings)} warning(s)")

    ok = [r for r in results if "error" not in r]
    if not ok:
        raise RuntimeError("no document could be ingested")
    failed = len(results) - len(ok)
    summary = (
        f"{len(ok)} document(s): {sum(r['nodes'] for r in ok)} nodes, "
        f"{sum(r['tables'] for r in ok)} tables, {sum(r['figures'] for r in ok)} figures"
    )
    warnings = sum(r["warnings"] for r in ok)
    if warnings:
        summary += f", {warnings} warning(s)"
    if failed:
        summary += f"; {failed} failed"
    return {"summary": summary, "documents": results}
