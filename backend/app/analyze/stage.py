"""The ``analyze`` pipeline stage: Layer 4 static analysis."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.analyze.service import get_analyzer
from app.link.service import get_linker
from app.models import SopIRRecord
from app.pipeline.graph import CompileState, StageContext
from app.schemas.ir_sop import SopIR

log = logging.getLogger(__name__)


def _load_sop_ir(services, run_id: str) -> SopIR | None:
    with services.sessions() as session:
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


def run_analyze(state: CompileState, ctx: StageContext) -> dict[str, Any]:
    analyzer = get_analyzer(ctx.services)
    linker = get_linker(ctx.services)

    ir = _load_sop_ir(ctx.services, ctx.run_id)
    if ir is None:
        raise RuntimeError("no approved SopIR found for this run; run extract first")

    linked = linker.load(ctx.run_id)  # may be None if link stage was skipped

    ctx.report("running static analysis checks")
    report = analyzer.analyze(ir, linked, ctx.run_id)
    analyzer.save(report)

    ctx.report(
        f"{report.stats.get('total', 0)} diagnostic(s): "
        f"{report.stats.get('total_errors', 0)} error(s), "
        f"{report.stats.get('total_warnings', 0)} warning(s)"
    )

    return {
        "total": report.stats.get("total", 0),
        "total_errors": report.stats.get("total_errors", 0),
        "total_warnings": report.stats.get("total_warnings", 0),
        "total_infos": report.stats.get("total_infos", 0),
        "summary": (
            f"{report.stats.get('total', 0)} diagnostic(s) — "
            f"{report.stats.get('total_errors', 0)} error(s), "
            f"{report.stats.get('total_warnings', 0)} warning(s)"
        ),
    }
