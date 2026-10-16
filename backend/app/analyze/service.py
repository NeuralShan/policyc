"""Analyzer service: top-level orchestrator for Layer 4 static analysis."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.analyze.registry import all_checks
from app.core.services import Services
from app.models import DiagnosticsRecord
from app.schemas.finding import DiagnosticsReport
from app.schemas.graph import LinkedIR
from app.schemas.ir_sop import SopIR

log = logging.getLogger(__name__)


def get_analyzer(services: Services) -> Analyzer:
    return services.singleton("analyzer", lambda: Analyzer(services))


class Analyzer:
    def __init__(self, services: Services) -> None:
        self._services = services

    def analyze(
        self,
        ir: SopIR,
        linked: LinkedIR | None,
        run_id: str,
    ) -> DiagnosticsReport:
        """Run all registered checks and return a collated report."""
        checks = all_checks()
        all_diags = []
        for check in checks:
            try:
                diags = check.fn(ir, linked)
                all_diags.extend(diags)
            except Exception:
                log.exception("check %s (%s) raised an exception", check.code_prefix, check.label)

        report = DiagnosticsReport(run_id=run_id, diagnostics=all_diags).with_stats()
        log.info(
            "analyze: %d diagnostics  errors=%d  warnings=%d  infos=%d",
            report.stats.get("total", 0),
            report.stats.get("total_errors", 0),
            report.stats.get("total_warnings", 0),
            report.stats.get("total_infos", 0),
        )
        return report

    def save(self, report: DiagnosticsReport) -> DiagnosticsRecord:
        with self._services.sessions() as session:
            record = DiagnosticsRecord(
                run_id=report.run_id,
                report=report.model_dump(mode="json"),
                stats=report.stats,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def load(self, run_id: str) -> DiagnosticsReport | None:
        with self._services.sessions() as session:
            stmt = (
                select(DiagnosticsRecord)
                .where(DiagnosticsRecord.run_id == run_id)
                .order_by(DiagnosticsRecord.created_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            if record is None:
                return None
            return DiagnosticsReport.model_validate(record.report)
