from collections import Counter

import pytest
from sqlalchemy import select

from app.models import CompileRun, Project, RunEvent, RunStatus
from app.pipeline.checkpointer import open_sqlite_checkpointer
from app.pipeline.executor import RunExecutor
from app.pipeline.graph import build_compile_graph
from app.pipeline.stages import STAGE_KEYS


def make_run(services) -> str:
    with services.sessions() as session:
        project = Project(name="p")
        session.add(project)
        session.flush()
        run = CompileRun(project_id=project.id, document_ids=["doc_1"])
        session.add(run)
        session.commit()
        return run.id


def load_run(services, run_id) -> CompileRun:
    with services.sessions() as session:
        return session.get(CompileRun, run_id)


def stage_events(services, run_id) -> list[tuple[str, str]]:
    with services.sessions() as session:
        query = select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id)
        return [(e.stage, e.status) for e in session.scalars(query)]


def test_failing_stage_marks_run_failed_and_stops_pipeline(services, tmp_path):
    def boom(state, ctx):
        raise RuntimeError("parser exploded")

    checkpointer, conn = open_sqlite_checkpointer(tmp_path / "cp.sqlite")
    graph = build_compile_graph(services, checkpointer, handlers={"extract": boom})
    executor = RunExecutor(services, graph, max_workers=1)
    run_id = make_run(services)
    executor.submit(run_id).result(timeout=10)
    executor.shutdown()
    conn.close()

    run = load_run(services, run_id)
    assert run.status == RunStatus.FAILED
    assert run.error == "RuntimeError: parser exploded"
    assert stage_events(services, run_id) == [
        ("ingest", "started"),
        ("ingest", "completed"),
        ("extract", "started"),
        ("extract", "failed"),
    ]


def test_interrupted_run_resumes_from_checkpoint_without_redoing_stages(services, tmp_path):
    executions = Counter()
    crash = {"link": True}

    def counting(state, ctx):
        executions[ctx.stage.key] += 1
        if crash.pop(ctx.stage.key, False):
            raise RuntimeError("process killed")  # stands in for a crash mid-run
        return {"summary": f"{ctx.stage.key} done", "seen": sorted(state["artifacts"])}

    handlers = dict.fromkeys(STAGE_KEYS, counting)
    checkpointer, conn = open_sqlite_checkpointer(tmp_path / "cp.sqlite")
    graph = build_compile_graph(services, checkpointer, handlers=handlers)
    run_id = make_run(services)
    config = {"configurable": {"thread_id": run_id}}

    # First process: dies inside "link". Leave the run looking like it was still running.
    with pytest.raises(RuntimeError, match="process killed"):
        graph.invoke(
            {"run_id": run_id, "project_id": "p", "document_ids": [], "artifacts": {}}, config
        )
    with services.sessions() as session:
        session.get(CompileRun, run_id).status = RunStatus.RUNNING
        session.commit()

    # Next process start: the executor picks the run up again.
    executor = RunExecutor(services, graph, max_workers=1)
    assert executor.resume_incomplete() == [run_id]
    executor.shutdown()
    conn.close()

    run = load_run(services, run_id)
    assert run.status == RunStatus.SUCCEEDED, run.error
    assert executions["ingest"] == 1 and executions["extract"] == 1  # not re-run
    assert executions["link"] == 2  # failed once, retried once
    assert all(executions[k] == 1 for k in STAGE_KEYS[3:])
    # Later stages see earlier stages' artifacts, including those from before the crash.
    assert run.artifacts["findings"]["seen"] == sorted(STAGE_KEYS[:-1])
    assert run.artifacts["link"]["summary"] == "link done"
