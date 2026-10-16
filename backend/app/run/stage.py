"""The ``execute`` pipeline stage: Layer 7 test execution."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.models import SopIRRecord, TestSuiteRecord
from app.pipeline.graph import CompileState, StageContext
from app.run.runner import run_test_suite
from app.run.service import get_runner_service
from app.schemas.ir_sop import SopIR
from app.schemas.testcase import TestSuite

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


def _load_test_suite(services, run_id: str) -> TestSuite | None:
    with services.sessions() as session:
        stmt = (
            select(TestSuiteRecord)
            .where(TestSuiteRecord.run_id == run_id)
            .order_by(TestSuiteRecord.created_at.desc())
            .limit(1)
        )
        record = session.scalars(stmt).first()
        if record is None:
            return None
        return TestSuite.model_validate(record.suite)


def run_execute(state: CompileState, ctx: StageContext) -> dict[str, Any]:
    ir = _load_sop_ir(ctx.services, ctx.run_id)
    if ir is None:
        raise RuntimeError("no approved SopIR found for this run; run extract first")

    suite = _load_test_suite(ctx.services, ctx.run_id)
    if suite is None:
        raise RuntimeError("no test suite found for this run; run testgen first")

    ctx.report(f"running {suite.stats.get('total', 0)} test cases through simulator")

    svc = get_runner_service(ctx.services)
    report = run_test_suite(ir, suite)
    svc.save(report)

    ctx.report(
        f"{report.passed}/{report.total} passed  "
        f"step_coverage={report.coverage.step_coverage_pct:.1f}%  "
        f"branch_coverage={report.coverage.branch_coverage_pct:.1f}%"
    )

    return {
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "skipped": report.skipped,
        "step_coverage_pct": report.coverage.step_coverage_pct,
        "branch_coverage_pct": report.coverage.branch_coverage_pct,
        "summary": (
            f"{report.passed}/{report.total} tests passed, "
            f"step={report.coverage.step_coverage_pct:.1f}% "
            f"branch={report.coverage.branch_coverage_pct:.1f}% coverage"
        ),
    }
