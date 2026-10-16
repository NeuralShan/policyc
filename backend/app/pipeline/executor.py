"""Runs compile graphs in background threads.

In-process for now (no Redis/Docker needed). A run's LangGraph ``thread_id`` is its run id, so a
run interrupted by a restart resumes from its last checkpoint instead of starting over.
"""

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select

from app.core.db import utcnow
from app.core.services import Services
from app.models import CompileRun, RunStatus

log = logging.getLogger(__name__)


class RunExecutor:
    def __init__(self, services: Services, graph: CompiledStateGraph, max_workers: int):
        self._services = services
        self._graph = graph
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="compile")

    def submit(self, run_id: str) -> Future:
        return self._pool.submit(self._execute, run_id)

    def resume_incomplete(self) -> list[str]:
        """Re-submit runs left queued or running by a previous process."""
        with self._services.sessions() as session:
            run_ids = session.scalars(
                select(CompileRun.id)
                .where(CompileRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]))
                .order_by(CompileRun.created_at)
            ).all()
        for run_id in run_ids:
            log.info("resuming compile run %s", run_id)
            self.submit(run_id)
        return list(run_ids)

    def shutdown(self) -> None:
        # Runs not yet started stay "queued" in the database and resume on next startup.
        self._pool.shutdown(wait=True, cancel_futures=True)

    def resume(self, run_id: str, decision: dict) -> "Future":
        """Resume a PAUSED run with the human reviewer's decision."""
        return self._pool.submit(self._resume_with_decision, run_id, decision)

    def _execute(self, run_id: str) -> None:
        with self._services.sessions() as session:
            run = session.get(CompileRun, run_id)
            if run is None:
                log.warning("compile run %s vanished before it started", run_id)
                return
            run.status = RunStatus.RUNNING
            run.started_at = run.started_at or utcnow()
            session.commit()
            initial = {
                "run_id": run.id,
                "project_id": run.project_id,
                "document_ids": list(run.document_ids),
                "artifacts": {},
            }

        config: Any = {"configurable": {"thread_id": run_id}}
        try:
            if self._graph.checkpointer.get_tuple(config) is None:
                final = self._graph.invoke(initial, config)
            elif self._graph.get_state(config).next:
                final = self._graph.invoke(None, config)  # resume after the last checkpoint
            else:
                final = self._graph.get_state(config).values  # finished before a crash

            # Check if the graph paused at a human-review interrupt
            snapshot = self._graph.get_state(config)
            if snapshot.next:
                log.info("compile run %s paused for human review", run_id)
                self._finish(run_id, RunStatus.PAUSED, artifacts=final.get("artifacts", {}))
            else:
                self._finish(run_id, RunStatus.SUCCEEDED, artifacts=final.get("artifacts", {}))
        except Exception as exc:
            log.exception("compile run %s failed", run_id)
            self._finish(run_id, RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}")

    def _resume_with_decision(self, run_id: str, decision: dict) -> None:
        from langgraph.types import Command

        with self._services.sessions() as session:
            run = session.get(CompileRun, run_id)
            if run is None:
                log.warning("resume: compile run %s not found", run_id)
                return
            run.status = RunStatus.RUNNING
            session.commit()

        config: Any = {"configurable": {"thread_id": run_id}}
        try:
            final = self._graph.invoke(Command(resume=decision), config)
            snapshot = self._graph.get_state(config)
            if snapshot.next:
                self._finish(run_id, RunStatus.PAUSED, artifacts=final.get("artifacts", {}))
            else:
                self._finish(run_id, RunStatus.SUCCEEDED, artifacts=final.get("artifacts", {}))
        except Exception as exc:
            log.exception("compile run %s failed after resume", run_id)
            self._finish(run_id, RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}")

    def _finish(
        self,
        run_id: str,
        status: RunStatus,
        *,
        artifacts: dict | None = None,
        error: str | None = None,
    ) -> None:
        with self._services.sessions() as session:
            run = session.get(CompileRun, run_id)
            if run is None:
                return
            run.status = status
            run.finished_at = utcnow()
            run.error = error
            if artifacts is not None:
                run.artifacts = artifacts
            session.commit()
