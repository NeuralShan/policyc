"""SimulatorService: orchestrates the process simulator for Layer 5."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.services import Services
from app.model.simulator import simulate
from app.models import ExecutionTraceRecord, SopIRRecord
from app.schemas.ir_sop import SopIR
from app.schemas.trace import ExecutionTrace, Scenario

log = logging.getLogger(__name__)


def get_simulator(services: Services) -> SimulatorService:
    return services.singleton("simulator", lambda: SimulatorService(services))


class SimulatorService:
    def __init__(self, services: Services) -> None:
        self._services = services

    def _load_ir(self, run_id: str) -> SopIR | None:
        with self._services.sessions() as session:
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

    def run(self, run_id: str, scenario: Scenario) -> ExecutionTrace:
        ir = self._load_ir(run_id)
        if ir is None:
            raise ValueError(f"no approved SopIR for run {run_id!r}")
        trace = simulate(ir, scenario)
        log.info(
            "simulate run=%s scenario=%s process=%s outcome=%s elapsed=%.1fs",
            run_id,
            scenario.id,
            trace.process_id,
            trace.outcome,
            trace.elapsed_s,
        )
        return trace

    def save(self, trace: ExecutionTrace) -> ExecutionTraceRecord:
        with self._services.sessions() as session:
            record = ExecutionTraceRecord(
                run_id=trace.run_id,
                scenario_id=trace.scenario_id,
                process_id=trace.process_id,
                outcome=trace.outcome,
                trace=trace.model_dump(mode="json"),
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def load(self, run_id: str, scenario_id: str) -> ExecutionTrace | None:
        with self._services.sessions() as session:
            stmt = (
                select(ExecutionTraceRecord)
                .where(
                    ExecutionTraceRecord.run_id == run_id,
                    ExecutionTraceRecord.scenario_id == scenario_id,
                )
                .order_by(ExecutionTraceRecord.created_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            if record is None:
                return None
            return ExecutionTrace.model_validate(record.trace)

    def list_traces(self, run_id: str) -> list[ExecutionTraceRecord]:
        with self._services.sessions() as session:
            stmt = (
                select(ExecutionTraceRecord)
                .where(ExecutionTraceRecord.run_id == run_id)
                .order_by(ExecutionTraceRecord.created_at.desc())
            )
            return list(session.scalars(stmt).all())
