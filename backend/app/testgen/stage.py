"""The ``testgen`` pipeline stage: Layer 6 test generation."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.models import SopIRRecord
from app.pipeline.graph import CompileState, StageContext
from app.schemas.ir_sop import SopIR
from app.testgen.service import get_testgen

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


def run_testgen(state: CompileState, ctx: StageContext) -> dict[str, Any]:
    tg = get_testgen(ctx.services)

    ir = _load_sop_ir(ctx.services, ctx.run_id)
    if ir is None:
        raise RuntimeError("no approved SopIR found for this run; run extract first")

    ctx.report("generating test cases (boundary + branch + fault injection)")
    suite = tg.generate(ir, ctx.run_id)
    tg.save(suite)

    ctx.report(
        f"{suite.stats.get('total', 0)} test cases: "
        f"{suite.stats.get('boundary', 0)} boundary, "
        f"{suite.stats.get('branch', 0)} branch, "
        f"{suite.stats.get('fault', 0)} fault, "
        f"{suite.stats.get('path', 0)} path"
    )

    return {
        "total": suite.stats.get("total", 0),
        "boundary": suite.stats.get("boundary", 0),
        "branch": suite.stats.get("branch", 0),
        "fault": suite.stats.get("fault", 0),
        "path": suite.stats.get("path", 0),
        "summary": (
            f"{suite.stats.get('total', 0)} test cases generated "
            f"({suite.stats.get('boundary', 0)} boundary, "
            f"{suite.stats.get('branch', 0)} branch, "
            f"{suite.stats.get('fault', 0)} fault)"
        ),
    }
