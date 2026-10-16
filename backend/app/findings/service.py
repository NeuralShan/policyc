"""FindingsService: persist and load Layer 9 findings reports."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.services import Services
from app.models import FindingsRecord
from app.schemas.findings import FindingsReport, FindingTriage

log = logging.getLogger(__name__)


def get_findings_service(services: Services) -> FindingsService:
    return services.singleton("findings", lambda: FindingsService(services))


class FindingsService:
    def __init__(self, services: Services) -> None:
        self._services = services

    def save(self, report: FindingsReport) -> FindingsRecord:
        with self._services.sessions() as session:
            record = FindingsRecord(
                run_id=report.run_id,
                report=report.model_dump(mode="json"),
                stats=report.stats,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def load(self, run_id: str) -> FindingsReport | None:
        with self._services.sessions() as session:
            stmt = (
                select(FindingsRecord)
                .where(FindingsRecord.run_id == run_id)
                .order_by(FindingsRecord.created_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            if record is None:
                return None
            return FindingsReport.model_validate(record.report)

    def update_triage(
        self,
        run_id: str,
        finding_id: str,
        triage: FindingTriage,
    ) -> FindingsReport | None:
        """Load the latest report, update one finding's triage state, and re-save."""
        report = self.load(run_id)
        if report is None:
            return None
        for finding in report.findings:
            if finding.id == finding_id:
                finding.triage = triage
                break
        else:
            return None
        report = report.with_stats()
        self.save(report)
        return report
