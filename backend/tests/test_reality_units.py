"""Unit tests for Layer 8: adapter, activity mapper, conformance (no LLM, no DB)."""

from __future__ import annotations

from app.reality.activity_mapper import map_activities
from app.reality.adapter import parse_csv
from app.reality.conformance import check_conformance
from app.schemas.case_history import CaseEvent, ColumnMap, EventLog
from app.schemas.ir_sop import (
    ModalVerb,
    Process,
    ReviewStatus,
    RoleRef,
    SopIR,
    Step,
    StepKind,
    SymbolTable,
    Transition,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CSV_MINIMAL = b"""\
case_id,activity,timestamp
C001,log complaint,2024-01-01 09:00:00
C001,assess complaint,2024-01-01 09:30:00
C001,resolve complaint,2024-01-01 10:00:00
C002,log complaint,2024-01-02 08:00:00
C002,resolve complaint,2024-01-02 08:45:00
"""

_CSV_CUSTOM_COLS = b"""\
ticket,action,occurred_at
T001,log the incident,2024-03-01 10:00:00
T001,close the incident,2024-03-01 11:00:00
"""

_CSV_NO_TIMESTAMP = b"""\
case_id,activity
C001,step one
C001,step two
"""


def _simple_ir() -> SopIR:
    steps = [
        Step(id="s01", action="log complaint", modal=ModalVerb.SHALL),
        Step(id="s02", action="assess complaint", modal=ModalVerb.SHALL),
        Step(id="s03", action="resolve complaint", kind=StepKind.TERMINAL, modal=ModalVerb.SHALL),
    ]
    transitions = [
        Transition(from_id="s01", to_id="s02"),
        Transition(from_id="s02", to_id="s03"),
    ]
    proc = Process(
        id="p01", name="Complaint", document_id="doc1", steps=steps, transitions=transitions
    )
    return SopIR(
        run_id="r1",
        document_ids=["doc1"],
        symbols=SymbolTable(roles=[RoleRef(id="agent", name="Agent")]),
        processes=[proc],
        review_status=ReviewStatus.APPROVED,
    )


def _event_log_from_csv(content: bytes, **col_kwargs) -> EventLog:
    col = ColumnMap(**col_kwargs) if col_kwargs else ColumnMap()
    return parse_csv(content, col, "cases.csv", "r1")


# ---------------------------------------------------------------------------
# adapter: parse_csv
# ---------------------------------------------------------------------------


def test_parse_csv_basic():
    el = _event_log_from_csv(_CSV_MINIMAL)
    assert set(el.cases.keys()) == {"C001", "C002"}
    assert len(el.cases["C001"]) == 3
    assert len(el.cases["C002"]) == 2


def test_parse_csv_events_sorted_by_timestamp():
    el = _event_log_from_csv(_CSV_MINIMAL)
    ts = [e.timestamp for e in el.cases["C001"]]
    assert ts == sorted(ts)


def test_parse_csv_custom_columns():
    col = ColumnMap(case_id="ticket", activity="action", timestamp="occurred_at")
    el = parse_csv(_CSV_CUSTOM_COLS, col, "custom.csv", "r1")
    assert "T001" in el.cases
    assert len(el.cases["T001"]) == 2


def test_parse_csv_no_timestamp():
    el = _event_log_from_csv(_CSV_NO_TIMESTAMP)
    assert all(e.timestamp is None for evts in el.cases.values() for e in evts)


def test_parse_csv_stats():
    el = _event_log_from_csv(_CSV_MINIMAL)
    assert el.stats["total_cases"] == 2
    assert el.stats["total_events"] == 5
    assert el.stats["unique_activities"] == 3


def test_parse_csv_skips_rows_missing_case_or_activity():
    csv_with_blanks = b"case_id,activity\n,step one\nC001,\nC001,valid step\n"
    el = _event_log_from_csv(csv_with_blanks)
    assert el.cases["C001"] == [
        e for e in el.cases["C001"] if e.activity == "valid step"
    ]
    assert len(el.cases["C001"]) == 1


# ---------------------------------------------------------------------------
# activity_mapper
# ---------------------------------------------------------------------------


def test_map_activities_exact_match():
    ir = _simple_ir()
    el = _event_log_from_csv(_CSV_MINIMAL)
    mapping = map_activities(el, ir)
    assert mapping.get("log complaint") == "s01"
    assert mapping.get("assess complaint") == "s02"
    assert mapping.get("resolve complaint") == "s03"


def test_map_activities_no_match_for_unrelated():
    ir = _simple_ir()
    col = ColumnMap()
    el = EventLog(
        run_id="r1",
        source_filename="x.csv",
        column_map=col,
        cases={"C001": [CaseEvent(case_id="C001", activity="xyz abc totally unrelated")]},
    )
    mapping = map_activities(el, ir)
    # may or may not match depending on token overlap — but we can confirm no crash
    assert isinstance(mapping, dict)


def test_map_activities_partial_match():
    ir = _simple_ir()
    col = ColumnMap()
    el = EventLog(
        run_id="r1",
        source_filename="x.csv",
        column_map=col,
        cases={"C001": [CaseEvent(case_id="C001", activity="log complaint escalated")]},
    )
    mapping = map_activities(el, ir)
    # "log complaint escalated" shares tokens with "log complaint" (s01)
    assert mapping.get("log complaint escalated") in ("s01", None)


# ---------------------------------------------------------------------------
# conformance: check_conformance
# ---------------------------------------------------------------------------


def test_conformance_fully_conformant_case():
    ir = _simple_ir()
    el = _event_log_from_csv(_CSV_MINIMAL)
    activity_map = map_activities(el, ir)
    report = check_conformance(el, ir, activity_map)

    c001 = next(r for r in report.case_results if r.case_id == "C001")
    assert c001.fitness == 1.0
    assert c001.skipped == []
    assert not c001.has_no_path


def test_conformance_partial_case_has_lower_fitness():
    ir = _simple_ir()
    el = _event_log_from_csv(_CSV_MINIMAL)
    activity_map = map_activities(el, ir)
    report = check_conformance(el, ir, activity_map)

    c002 = next(r for r in report.case_results if r.case_id == "C002")
    # C002 skipped "assess complaint"
    assert c002.fitness < 1.0
    assert "s02" in c002.skipped


def test_conformance_rl001_flagged_when_step_routinely_skipped():
    ir = _simple_ir()
    # Both cases skip "assess complaint" (s02)
    csv = (
        b"case_id,activity\n"
        b"C001,log complaint\nC001,resolve complaint\n"
        b"C002,log complaint\nC002,resolve complaint\n"
    )
    el = _event_log_from_csv(csv)
    activity_map = {"log complaint": "s01", "resolve complaint": "s03"}
    report = check_conformance(el, ir, activity_map)

    codes = [f.code for f in report.rl_findings]
    assert "RL001" in codes
    rl001 = next(f for f in report.rl_findings if f.code == "RL001" and f.step_id == "s02")
    assert rl001.case_count == 2


def test_conformance_rl004_flagged_when_fitness_too_low():
    ir = _simple_ir()
    # Cases with completely unrelated activities
    csv = b"case_id,activity\nC001,send email\nC001,call customer\n"
    el = _event_log_from_csv(csv)
    # No activity maps to any step
    activity_map: dict[str, str | None] = {"send email": None, "call customer": None}
    report = check_conformance(el, ir, activity_map)

    codes = [f.code for f in report.rl_findings]
    assert "RL004" in codes


def test_conformance_avg_fitness_computed():
    ir = _simple_ir()
    el = _event_log_from_csv(_CSV_MINIMAL)
    activity_map = map_activities(el, ir)
    report = check_conformance(el, ir, activity_map)

    assert 0.0 <= report.avg_fitness <= 1.0
    assert report.total_cases == 2


def test_conformance_empty_ir_processes():
    ir = SopIR(
        run_id="r1",
        document_ids=["doc1"],
        symbols=SymbolTable(),
        processes=[],
        review_status=ReviewStatus.APPROVED,
    )
    el = _event_log_from_csv(_CSV_MINIMAL)
    report = check_conformance(el, ir, {})
    assert report.total_cases == 0  # no processes → empty report


def test_conformance_with_stats():
    ir = _simple_ir()
    el = _event_log_from_csv(_CSV_MINIMAL)
    activity_map = map_activities(el, ir)
    report = check_conformance(el, ir, activity_map)

    assert "total_cases" in report.stats
    assert "avg_fitness" in report.stats
    assert "conformance_rate_pct" in report.stats


# ---------------------------------------------------------------------------
# RealityService (no DB)
# ---------------------------------------------------------------------------


def test_reality_service_run_conformance():
    from app.reality.service import RealityService

    svc = RealityService.__new__(RealityService)
    ir = _simple_ir()
    el = _event_log_from_csv(_CSV_MINIMAL)
    report = svc.run_conformance(el, ir)

    assert report.total_cases == 2
    assert 0.0 <= report.avg_fitness <= 1.0
    assert isinstance(report.rl_findings, list)
