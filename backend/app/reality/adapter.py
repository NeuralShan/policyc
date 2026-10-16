"""CSV → EventLog adapter for Layer 8 case history."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

from app.schemas.case_history import CaseEvent, ColumnMap, EventLog


def _parse_timestamp(value: str) -> datetime | None:
    if not value or not value.strip():
        return None
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(value.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue
    return None


def parse_csv(
    content: bytes,
    column_map: ColumnMap,
    filename: str,
    run_id: str,
) -> EventLog:
    """Parse a CSV file into an EventLog using the given column mapping."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    cases: dict[str, list[CaseEvent]] = {}

    for row in reader:
        case_id = str(row.get(column_map.case_id, "")).strip()
        activity = str(row.get(column_map.activity, "")).strip()
        if not case_id or not activity:
            continue

        ts_raw = row.get(column_map.timestamp, "")
        timestamp = _parse_timestamp(ts_raw) if ts_raw else None

        resource = None
        if column_map.resource:
            resource = row.get(column_map.resource, "").strip() or None

        extra: dict[str, Any] = {
            k: v for k, v in row.items()
            if k not in (column_map.case_id, column_map.activity, column_map.timestamp)
            and (column_map.resource is None or k != column_map.resource)
        }

        event = CaseEvent(
            case_id=case_id,
            activity=activity,
            timestamp=timestamp,
            resource=resource,
            attributes=extra,
        )
        cases.setdefault(case_id, []).append(event)

    # Sort each case's events by timestamp (events without timestamps keep insertion order)
    for case_id, events in cases.items():
        if any(e.timestamp is not None for e in events):
            cases[case_id] = sorted(events, key=lambda e: (e.timestamp is None, e.timestamp))

    return EventLog(
        run_id=run_id,
        source_filename=filename,
        column_map=column_map,
        cases=cases,
    ).with_stats()
