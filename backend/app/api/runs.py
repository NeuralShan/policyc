import asyncio
from collections.abc import AsyncIterable
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from sqlalchemy import select

from app.analyze.service import get_analyzer
from app.api.deps import ExecutorDep, ProjectDep, RunDep, RunIdDep, ServicesDep, SessionDep
from app.api.insight import ReadRun
from app.core.services import Services
from app.findings.service import get_findings_service
from app.link.service import get_linker
from app.model.service import get_simulator
from app.models import (
    TERMINAL_RUN_STATUSES,
    CompileRun,
    RunEvent,
    RunStatus,
    SopIRRecord,
)
from app.reality.service import get_reality_service
from app.run.service import get_runner_service
from app.schemas.api import RunCreate, RunDetail, RunEventOut, RunOut
from app.schemas.findings import FindingTriage
from app.testgen.service import get_testgen

router = APIRouter(prefix="/api", tags=["runs"])

POLL_INTERVAL_S = 0.5


@router.post("/projects/{project_id}/runs", status_code=202)
def start_run(
    project: ProjectDep, body: RunCreate, session: SessionDep, executor: ExecutorDep
) -> RunOut:
    project_doc_ids = [d.id for d in project.documents]
    if body.document_ids is None:
        document_ids = project_doc_ids
    else:
        unknown = sorted(set(body.document_ids) - set(project_doc_ids))
        if unknown:
            raise HTTPException(422, f"documents not in this project: {', '.join(unknown)}")
        document_ids = list(dict.fromkeys(body.document_ids))
    if not document_ids:
        raise HTTPException(422, "upload at least one document before compiling")

    if body.base_run_id is not None and session.get(CompileRun, body.base_run_id) is None:
        raise HTTPException(422, f"base run {body.base_run_id} not found")
    run = CompileRun(
        project_id=project.id,
        document_ids=document_ids,
        auto_approve=body.auto_approve,
        base_run_id=body.base_run_id,
        note="Replay of an earlier extraction" if body.base_run_id else None,
    )
    session.add(run)
    session.commit()
    executor.submit(run.id)
    return RunOut.model_validate(run)


@router.get("/projects/{project_id}/runs")
def list_runs(project: ProjectDep, session: SessionDep) -> list[RunOut]:
    runs = session.scalars(
        select(CompileRun)
        .where(CompileRun.project_id == project.id)
        .order_by(CompileRun.created_at.desc())
    ).all()
    return [RunOut.model_validate(r) for r in runs]


@router.get("/runs/{run_id}")
def get_run(run: RunDep) -> RunDetail:
    return RunDetail.model_validate(run)


def _poll(services: Services, run_id: str, after_id: int) -> tuple[list[RunEventOut], str]:
    with services.sessions() as session:
        status = session.scalar(select(CompileRun.status).where(CompileRun.id == run_id))
        events = session.scalars(
            select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.id > after_id)
            .order_by(RunEvent.id)
        ).all()
        return [RunEventOut.model_validate(e) for e in events], status


class IRReviewDecision(BaseModel):
    approved: bool
    overrides: dict[str, Any] = {}


class IRReviewOut(BaseModel):
    ir_id: str
    review_status: str
    stats: dict[str, Any]
    warnings: list[dict[str, Any]]
    ir: dict[str, Any]


@router.get("/runs/{run_id}/ir")
def get_run_ir(run: RunDep, services: ServicesDep) -> IRReviewOut:
    """Return the extracted SopIR for a paused run (for the IR Review UI)."""
    with services.sessions() as session:
        stmt = (
            select(SopIRRecord)
            .where(SopIRRecord.run_id == run.id)
            .order_by(SopIRRecord.created_at.desc())
            .limit(1)
        )
        record = session.scalars(stmt).first()
    if record is None:
        raise HTTPException(404, "No IR found for this run")
    return IRReviewOut(
        ir_id=record.id,
        review_status=record.review_status,
        stats=record.stats or {},
        warnings=record.ir.get("warnings", []),
        ir=record.ir,
    )


@router.post("/runs/{run_id}/ir/review", status_code=202)
def review_ir(
    run: RunDep,
    body: IRReviewDecision,
    services: ServicesDep,
    executor: ExecutorDep,
) -> RunOut:
    """Approve or reject the extracted IR and resume the compile run."""
    if run.status != RunStatus.PAUSED:
        raise HTTPException(409, f"Run is not paused (status={run.status})")
    executor.resume(run.id, {"approved": body.approved, "overrides": body.overrides})
    # Return the run with RUNNING status (executor will update it asynchronously)
    with services.sessions() as session:
        session.get(CompileRun, run.id).status = RunStatus.RUNNING
        session.commit()
        updated = session.get(CompileRun, run.id)
        return RunOut.model_validate(updated)


class GraphOut(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    stats: dict[str, Any]
    warnings: list[dict[str, Any]]
    cypher_sha256: str | None


@router.get("/runs/{run_id}/graph")
def get_run_graph(run: RunDep, services: ServicesDep) -> GraphOut:
    """Return the linked graph in React-Flow-compatible format."""
    linker = get_linker(services)
    linked = linker.load(run.id)
    if linked is None:
        raise HTTPException(404, "No linked graph found for this run")

    # Load the SopIR to derive graph_data
    with services.sessions() as session:
        stmt = (
            select(SopIRRecord)
            .where(SopIRRecord.run_id == run.id)
            .order_by(SopIRRecord.created_at.desc())
            .limit(1)
        )
        ir_record = session.scalars(stmt).first()
    if ir_record is None:
        raise HTTPException(404, "No SopIR found for this run")

    graph_data = linked.graph_data(ir_record.ir)
    return GraphOut(
        nodes=graph_data["nodes"],
        edges=graph_data["edges"],
        stats=linked.stats.model_dump(),
        warnings=[w.model_dump() for w in linked.warnings],
        cypher_sha256=linked.cypher_sha256,
    )


@router.get("/runs/{run_id}/cypher", response_class=PlainTextResponse)
def get_run_cypher(run: RunDep, services: ServicesDep) -> str:
    """Return the emitted .cypher file as plain text."""
    linker = get_linker(services)
    cypher = linker.load_cypher(run.id)
    if cypher is None:
        raise HTTPException(404, "No .cypher artifact found for this run")
    return cypher


@router.get("/runs/{run_id}/diagnostics")
def get_run_diagnostics(run: RunDep, services: ServicesDep) -> dict[str, Any]:
    """Return Layer 4 static-analysis diagnostics for the run."""
    analyzer = get_analyzer(services)
    report = analyzer.load(run.id)
    if report is None:
        raise HTTPException(404, "No diagnostics found for this run")
    return report.model_dump(mode="json")


class SimulateRequest(BaseModel):
    scenario_id: str = "sc_default"
    description: str = "Ad-hoc simulation"
    process_id: str | None = None
    facts: dict[str, Any] = {}
    actor_overrides: dict[str, str | None] = {}
    system_overrides: dict[str, bool] = {}


@router.post("/runs/{run_id}/simulate", status_code=201)
def simulate_run(run: ReadRun, body: SimulateRequest, services: ServicesDep) -> dict[str, Any]:
    """Run the process simulator with the given scenario and return the trace.

    Simulating only reads the model, so it is allowed on read-only demo runs too."""
    from app.schemas.trace import Scenario

    sim = get_simulator(services)
    scenario = Scenario(
        id=body.scenario_id,
        description=body.description,
        process_id=body.process_id,
        facts=body.facts,
        actor_overrides=body.actor_overrides,
        system_overrides=body.system_overrides,
    )
    trace = sim.run(run.id, scenario)
    sim.save(trace)
    return trace.model_dump(mode="json")


@router.get("/runs/{run_id}/testcases")
def get_run_testcases(run: RunDep, services: ServicesDep) -> dict[str, Any]:
    """Return the generated test suite for the run."""
    tg = get_testgen(services)
    suite = tg.load(run.id)
    if suite is None:
        raise HTTPException(404, "No test suite found for this run")
    return suite.model_dump(mode="json")


@router.get("/runs/{run_id}/traces")
def list_run_traces(run: RunDep, services: ServicesDep) -> list[dict[str, Any]]:
    """List all simulation traces for the run (summary: id, scenario_id, outcome)."""
    sim = get_simulator(services)
    records = sim.list_traces(run.id)
    return [
        {
            "id": r.id,
            "scenario_id": r.scenario_id,
            "process_id": r.process_id,
            "outcome": r.outcome,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]


@router.get("/runs/{run_id}/testrun")
def get_run_testrun(run: RunDep, services: ServicesDep) -> dict[str, Any]:
    """Return the Layer 7 test-run report for the run."""
    svc = get_runner_service(services)
    report = svc.load(run.id)
    if report is None:
        raise HTTPException(404, "No test-run report found for this run")
    return report.model_dump(mode="json")


@router.post("/runs/{run_id}/case-history", status_code=201)
async def upload_case_history(
    run: RunDep,
    services: ServicesDep,
    file: Annotated[Any, "UploadFile"],
    case_id_col: str = "case_id",
    activity_col: str = "activity",
    timestamp_col: str = "timestamp",
    resource_col: str | None = None,
) -> dict[str, Any]:
    """Upload a CSV case-history file and store it as an EventLog for this run.

    Pass column-mapping via query parameters:
      ``case_id_col``, ``activity_col``, ``timestamp_col``, ``resource_col``
    """
    from pathlib import PurePath

    from fastapi import UploadFile

    from app.reality.adapter import parse_csv
    from app.schemas.case_history import ColumnMap

    if not isinstance(file, UploadFile):
        raise HTTPException(422, "Provide a CSV file as multipart/form-data 'file' field")

    filename = PurePath((file.filename or "cases.csv").replace("\\", "/")).name
    content = await file.read()

    column_map = ColumnMap(
        case_id=case_id_col,
        activity=activity_col,
        timestamp=timestamp_col,
        resource=resource_col,
    )

    svc = get_reality_service(services)
    event_log = parse_csv(content, column_map, filename, run.id)
    svc.save_event_log(event_log)

    return {
        "source_filename": event_log.source_filename,
        "stats": event_log.stats,
        "column_map": event_log.column_map.model_dump(),
    }


@router.get("/runs/{run_id}/case-history")
def get_case_history(run: RunDep, services: ServicesDep) -> dict[str, Any]:
    """Return the stored EventLog summary for this run."""
    svc = get_reality_service(services)
    el = svc.load_event_log(run.id)
    if el is None:
        raise HTTPException(404, "No case history found for this run")
    return {
        "source_filename": el.source_filename,
        "stats": el.stats,
        "column_map": el.column_map.model_dump(),
    }


@router.post("/runs/{run_id}/reality", status_code=201)
def run_reality_check(run: RunDep, services: ServicesDep) -> dict[str, Any]:
    """Run conformance checking on the uploaded case history and return the report."""
    from sqlalchemy import select as sa_select

    from app.models import SopIRRecord
    from app.schemas.ir_sop import SopIR

    svc = get_reality_service(services)
    event_log = svc.load_event_log(run.id)
    if event_log is None:
        raise HTTPException(404, "No case history found; upload a CSV first")

    with services.sessions() as session:
        stmt = (
            sa_select(SopIRRecord)
            .where(SopIRRecord.run_id == run.id)
            .order_by(SopIRRecord.created_at.desc())
            .limit(1)
        )
        ir_record = session.scalars(stmt).first()
    if ir_record is None:
        raise HTTPException(404, "No SopIR found for this run; run extract first")

    ir = SopIR.model_validate(ir_record.ir)
    report = svc.run_conformance(event_log, ir)
    svc.save_report(report)
    return report.model_dump(mode="json")


@router.get("/runs/{run_id}/reality")
def get_reality_report(run: RunDep, services: ServicesDep) -> dict[str, Any]:
    """Return the latest saved conformance report for this run."""
    svc = get_reality_service(services)
    report = svc.load_report(run.id)
    if report is None:
        raise HTTPException(404, "No reality report found for this run")
    return report.model_dump(mode="json")


@router.get("/runs/{run_id}/findings")
def get_run_findings(run: RunDep, services: ServicesDep) -> dict[str, Any]:
    """Return the Layer 9 aggregated findings report for the run."""
    svc = get_findings_service(services)
    report = svc.load(run.id)
    if report is None:
        raise HTTPException(404, "No findings report found for this run")
    return report.model_dump(mode="json")


class TriageUpdate(BaseModel):
    triage: FindingTriage


@router.patch("/runs/{run_id}/findings/{finding_id}/triage")
def update_finding_triage(
    run: RunDep,
    finding_id: str,
    body: TriageUpdate,
    services: ServicesDep,
) -> dict[str, Any]:
    """Update the triage state of one finding (open/accepted/false_positive/wont_fix/fixed)."""
    svc = get_findings_service(services)
    report = svc.update_triage(run.id, finding_id, body.triage)
    if report is None:
        raise HTTPException(404, "Finding not found or no findings report for this run")
    return report.model_dump(mode="json")


@router.get("/runs/{run_id}/events", response_class=EventSourceResponse)
async def stream_run_events(
    run_id: RunIdDep,
    services: ServicesDep,
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterable[ServerSentEvent]:
    """Stage events as Server-Sent Events. Reconnecting clients resume via ``Last-Event-ID``."""
    after_id = last_event_id or 0
    while True:
        events, status = await asyncio.to_thread(_poll, services, run_id, after_id)
        for event in events:
            yield ServerSentEvent(
                data=event.model_dump(mode="json"), event="stage", id=str(event.id)
            )
            after_id = event.id
        if not events and status in TERMINAL_RUN_STATUSES | {RunStatus.PAUSED}:
            yield ServerSentEvent(data={"status": status}, event="end")
            return
        await asyncio.sleep(POLL_INTERVAL_S)
