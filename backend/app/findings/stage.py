"""The ``findings`` pipeline stage: Layer 9 gap aggregation and ranking."""

from __future__ import annotations

import logging
from typing import Any

from app.analyze.service import get_analyzer
from app.findings.aggregator import aggregate
from app.findings.service import get_findings_service
from app.pipeline.graph import CompileState, StageContext
from app.reality.service import get_reality_service
from app.run.service import get_runner_service

log = logging.getLogger(__name__)


def run_findings(state: CompileState, ctx: StageContext) -> dict[str, Any]:
    run_id = ctx.run_id

    # Load outputs from previous layers (all optional — findings runs best-effort)
    analyzer = get_analyzer(ctx.services)
    diagnostics = analyzer.load(run_id)

    runner_svc = get_runner_service(ctx.services)
    test_run = runner_svc.load(run_id)

    reality_svc = get_reality_service(ctx.services)
    reality = reality_svc.load_report(run_id)

    ctx.report(
        f"aggregating: {len(diagnostics.diagnostics) if diagnostics else 0} diagnostics, "
        f"{test_run.failed if test_run else 0} test failures, "
        f"{len(reality.rl_findings) if reality else 0} RL findings"
    )

    report = aggregate(run_id, diagnostics, test_run, reality)
    svc = get_findings_service(ctx.services)
    svc.save(report)

    ctx.report(
        f"{report.stats.get('total', 0)} findings  "
        f"open={report.stats.get('open', 0)}  "
        f"top={report.findings[0].code if report.findings else '—'}"
    )

    return {
        "total": report.stats.get("total", 0),
        "open": report.stats.get("open", 0),
        "summary": (
            f"{report.stats.get('total', 0)} findings aggregated "
            f"({report.stats.get('open', 0)} open)"
        ),
    }
