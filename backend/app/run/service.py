"""TestRunService: persist and load Layer 7 test-run reports."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.services import Services
from app.models import TestRunRecord
from app.schemas.testrun import TestRunReport

log = logging.getLogger(__name__)


def get_runner_service(services: Services) -> TestRunService:
    return services.singleton("test_runner", lambda: TestRunService(services))


class TestRunService:
    def __init__(self, services: Services) -> None:
        self._services = services

    def save(self, report: TestRunReport) -> TestRunRecord:
        with self._services.sessions() as session:
            record = TestRunRecord(
                run_id=report.run_id,
                report=report.model_dump(mode="json"),
                stats=report.stats,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def load(self, run_id: str) -> TestRunReport | None:
        with self._services.sessions() as session:
            stmt = (
                select(TestRunRecord)
                .where(TestRunRecord.run_id == run_id)
                .order_by(TestRunRecord.created_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            if record is None:
                return None
            return TestRunReport.model_validate(record.report)
