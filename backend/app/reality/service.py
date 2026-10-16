"""RealityService: persist and load Layer 8 case history and conformance reports."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.services import Services
from app.models import CaseHistoryRecord, RealityRecord
from app.reality.activity_mapper import map_activities
from app.reality.conformance import check_conformance
from app.schemas.case_history import EventLog
from app.schemas.ir_sop import SopIR
from app.schemas.reality import RealityReport

log = logging.getLogger(__name__)


def get_reality_service(services: Services) -> RealityService:
    return services.singleton("reality", lambda: RealityService(services))


class RealityService:
    def __init__(self, services: Services) -> None:
        self._services = services

    def save_event_log(self, event_log: EventLog) -> CaseHistoryRecord:
        with self._services.sessions() as session:
            record = CaseHistoryRecord(
                run_id=event_log.run_id,
                source_filename=event_log.source_filename,
                event_log=event_log.model_dump(mode="json"),
                stats=event_log.stats,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def load_event_log(self, run_id: str) -> EventLog | None:
        with self._services.sessions() as session:
            stmt = (
                select(CaseHistoryRecord)
                .where(CaseHistoryRecord.run_id == run_id)
                .order_by(CaseHistoryRecord.created_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            if record is None:
                return None
            return EventLog.model_validate(record.event_log)

    def run_conformance(self, event_log: EventLog, ir: SopIR) -> RealityReport:
        activity_map = map_activities(event_log, ir)
        return check_conformance(event_log, ir, activity_map)

    def save_report(self, report: RealityReport) -> RealityRecord:
        with self._services.sessions() as session:
            record = RealityRecord(
                run_id=report.run_id,
                report=report.model_dump(mode="json"),
                stats=report.stats,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def load_report(self, run_id: str) -> RealityReport | None:
        with self._services.sessions() as session:
            stmt = (
                select(RealityRecord)
                .where(RealityRecord.run_id == run_id)
                .order_by(RealityRecord.created_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            if record is None:
                return None
            return RealityReport.model_validate(record.report)
