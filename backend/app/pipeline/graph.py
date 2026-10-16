"""The top-level LangGraph ``compile`` graph.

Every stage node is wrapped so that it records started/completed/failed events (streamed to the UI)
and stores its output under ``state["artifacts"][stage]``. Layers plug in by adding their handler to
``default_handlers()``; stages without one run the stub.
"""

import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.core.services import Services
from app.models import RunEvent, StageEventStatus
from app.pipeline.stages import STAGES, StageSpec


class CompileState(TypedDict):
    run_id: str
    project_id: str
    document_ids: list[str]
    artifacts: Annotated[dict[str, Any], operator.or_]


@dataclass(frozen=True)
class StageContext:
    run_id: str
    stage: StageSpec
    services: Services

    def report(self, message: str) -> None:
        """Progress message shown under the running stage in the UI."""
        record_event(self.services, self.run_id, self.stage.key, StageEventStatus.PROGRESS, message)


StageHandler = Callable[[CompileState, StageContext], dict[str, Any]]


def default_handlers() -> dict[str, StageHandler]:
    """Real stage implementations, one per built layer (imported lazily: they are heavy)."""
    from app.analyze.stage import run_analyze
    from app.extract.stage import run_extract
    from app.findings.stage import run_findings
    from app.ingest.stage import run_ingest
    from app.link.stage import run_link
    from app.run.stage import run_execute
    from app.testgen.stage import run_testgen

    return {
        "ingest": run_ingest,
        "extract": run_extract,
        "link": run_link,
        "analyze": run_analyze,
        "testgen": run_testgen,
        "execute": run_execute,
        "findings": run_findings,
    }


IMPLEMENTED_STAGES = frozenset(
    {"ingest", "extract", "link", "analyze", "testgen", "execute", "findings"}
)


def stub_handler(state: CompileState, ctx: StageContext) -> dict[str, Any]:
    return {"stub": True, "note": f"Layer {ctx.stage.layer} ({ctx.stage.label}) not built yet"}


def record_event(
    services: Services, run_id: str, stage: str, status: StageEventStatus, message: str = ""
) -> None:
    with services.sessions() as session:
        session.add(RunEvent(run_id=run_id, stage=stage, status=status, message=message))
        session.commit()


def _already_started(services: Services, run_id: str, stage_key: str) -> bool:
    """True when a STARTED event already exists (stage being resumed after interrupt)."""
    from sqlalchemy import func, select

    with services.sessions() as session:
        count = session.scalar(
            select(func.count())
            .select_from(RunEvent)
            .where(
                RunEvent.run_id == run_id,
                RunEvent.stage == stage_key,
                RunEvent.status == StageEventStatus.STARTED,
            )
        )
    return bool(count)


def _node(spec: StageSpec, handler: StageHandler, services: Services):
    def run(state: CompileState) -> dict[str, Any]:
        run_id = state["run_id"]
        # On LangGraph resume from interrupt the node is re-called from the top.
        # Avoid a duplicate STARTED event by checking the DB.
        if not _already_started(services, run_id, spec.key):
            record_event(services, run_id, spec.key, StageEventStatus.STARTED)
        try:
            artifact = handler(state, StageContext(run_id=run_id, stage=spec, services=services))
        except GraphInterrupt:
            # LangGraph interrupt: the stage paused for human review. Let it propagate so
            # LangGraph can checkpoint the interrupt value; do NOT record FAILED.
            raise
        except Exception as exc:
            record_event(
                services, run_id, spec.key, StageEventStatus.FAILED, f"{type(exc).__name__}: {exc}"
            )
            raise
        message = "stub" if artifact.get("stub") else artifact.get("summary", "")
        record_event(services, run_id, spec.key, StageEventStatus.COMPLETED, message)
        return {"artifacts": {spec.key: artifact}}

    run.__name__ = f"stage_{spec.key}"
    return run


def build_compile_graph(
    services: Services,
    checkpointer: BaseCheckpointSaver | None,
    handlers: Mapping[str, StageHandler] | None = None,
) -> CompiledStateGraph:
    handlers = default_handlers() if handlers is None else handlers
    builder = StateGraph(CompileState)
    previous = START
    for spec in STAGES:
        builder.add_node(spec.key, _node(spec, handlers.get(spec.key, stub_handler), services))
        builder.add_edge(previous, spec.key)
        previous = spec.key
    builder.add_edge(previous, END)
    return builder.compile(checkpointer=checkpointer)
