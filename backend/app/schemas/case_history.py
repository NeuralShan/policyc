"""Layer 8 case-history schema: uploaded event log from real case data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

EVENTLOG_VERSION = 1


class ColumnMap(BaseModel):
    """Which CSV column names map to the required semantic fields."""

    case_id: str = "case_id"
    activity: str = "activity"
    timestamp: str = "timestamp"
    resource: str | None = None   # optional actor/role column


class CaseEvent(BaseModel):
    case_id: str
    activity: str
    timestamp: datetime | None = None
    resource: str | None = None
    attributes: dict[str, Any] = {}


class EventLog(BaseModel):
    version: int = EVENTLOG_VERSION
    run_id: str
    source_filename: str
    column_map: ColumnMap
    cases: dict[str, list[CaseEvent]] = {}   # case_id → events in timestamp order
    stats: dict[str, Any] = {}

    def with_stats(self) -> EventLog:
        total_events = sum(len(evts) for evts in self.cases.values())
        unique_activities = {e.activity for evts in self.cases.values() for e in evts}
        self.stats = {
            "total_cases": len(self.cases),
            "total_events": total_events,
            "unique_activities": len(unique_activities),
        }
        return self
