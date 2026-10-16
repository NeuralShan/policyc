"""ORM models (persistence). Domain schemas that travel between stages live in ``app.schemas``."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, utcnow


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"  # interrupted for human review (e.g. IR review checkpoint)
    SUCCEEDED = "succeeded"
    FAILED = "failed"


TERMINAL_RUN_STATUSES = {RunStatus.SUCCEEDED, RunStatus.FAILED}


class StageEventStatus(StrEnum):
    STARTED = "started"
    PROGRESS = "progress"  # informational message while a stage runs
    COMPLETED = "completed"
    FAILED = "failed"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("prj"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Document.uploaded_at"
    )
    runs: Mapped[list["CompileRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="CompileRun.created_at"
    )


class Document(Base):
    """An uploaded source document. Content-addressed: one row per distinct file per project."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("project_id", "sha256"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("doc"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(127))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(255))
    uploaded_at: Mapped[datetime] = mapped_column(default=utcnow)

    project: Mapped[Project] = relationship(back_populates="documents")
    asts: Mapped[list["DocumentAST"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class ParseCache(Base):
    """Deterministic parser output per (file content, parser version). Scans take minutes to OCR."""

    __tablename__ = "parse_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))
    parser: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DocumentAST(Base):
    """A DocAST produced by an ingest run. The latest one per document is the current view."""

    __tablename__ = "doc_asts"
    __table_args__ = (Index("ix_doc_asts_document_created", "document_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ast"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("compile_runs.id", ondelete="SET NULL"), index=True
    )
    parser: Mapped[str] = mapped_column(String(100))
    complete: Mapped[bool]
    stats: Mapped[dict[str, Any]] = mapped_column(JSON)
    ast: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    document: Mapped[Document] = relationship(back_populates="asts")


class CompileRun(Base):
    __tablename__ = "compile_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("run"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    status: Mapped[RunStatus] = mapped_column(String(16), default=RunStatus.QUEUED)
    document_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    project: Mapped[Project] = relationship(back_populates="runs")
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunEvent.id"
    )


class RunEvent(Base):
    """Append-only log of stage transitions; streamed to the UI over SSE."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("compile_runs.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(32))
    status: Mapped[StageEventStatus] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    run: Mapped[CompileRun] = relationship(back_populates="events")

    __table_args__ = (Index("ix_run_events_run_id_id", "run_id", "id"),)


class LLMCacheEntry(Base):
    """Cached structured LLM response, keyed by a hash of everything that determines the output."""

    __tablename__ = "llm_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(100))
    prompt_id: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[int]
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SopIRRecord(Base):
    """Extracted SOP IR for one run.  The latest per run_id is the live IR."""

    __tablename__ = "sop_irs"
    __table_args__ = (Index("ix_sop_irs_run_id_created", "run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ir"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("compile_runs.id", ondelete="CASCADE"), index=True
    )
    document_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(16), default="pending")
    ir: Mapped[dict[str, Any]] = mapped_column(JSON)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DiagnosticsRecord(Base):
    """Static-analysis diagnostics produced by Layer 4."""

    __tablename__ = "diagnostics"
    __table_args__ = (Index("ix_diagnostics_run_id_created", "run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("dgn"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("compile_runs.id", ondelete="CASCADE"), index=True
    )
    report: Mapped[dict[str, Any]] = mapped_column(JSON)   # DiagnosticsReport JSON
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class LinkedIRRecord(Base):
    """Linked IR produced by Layer 3 (entity resolution + graph emission)."""

    __tablename__ = "linked_irs"
    __table_args__ = (Index("ix_linked_irs_run_id_created", "run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("lnk"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("compile_runs.id", ondelete="CASCADE"), index=True
    )
    linked: Mapped[dict[str, Any]] = mapped_column(JSON)  # LinkedIR JSON
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class CypherArtifactRecord(Base):
    """The .cypher file emitted by Layer 3. Deterministic: same IR → same SHA-256."""

    __tablename__ = "cypher_artifacts"
    __table_args__ = (Index("ix_cypher_artifacts_run_id_created", "run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("cyp"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("compile_runs.id", ondelete="CASCADE"), index=True
    )
    sha256: Mapped[str] = mapped_column(String(64))
    cypher_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ExecutionTraceRecord(Base):
    """One simulation run produced by Layer 5."""

    __tablename__ = "execution_traces"
    __table_args__ = (Index("ix_execution_traces_run_id_created", "run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("trc"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("compile_runs.id", ondelete="CASCADE"), index=True
    )
    scenario_id: Mapped[str] = mapped_column(String(64))
    process_id: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    trace: Mapped[dict[str, Any]] = mapped_column(JSON)   # ExecutionTrace JSON
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TestSuiteRecord(Base):
    """Generated test suite produced by Layer 6."""

    __tablename__ = "test_suites"
    __table_args__ = (Index("ix_test_suites_run_id_created", "run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("tst"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("compile_runs.id", ondelete="CASCADE"), index=True
    )
    suite: Mapped[dict[str, Any]] = mapped_column(JSON)   # TestSuite JSON
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FindingsRecord(Base):
    """Aggregated findings report produced by Layer 9."""

    __tablename__ = "findings_reports"
    __table_args__ = (Index("ix_findings_reports_run_id_created", "run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("fnd"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("compile_runs.id", ondelete="CASCADE"), index=True
    )
    report: Mapped[dict[str, Any]] = mapped_column(JSON)   # FindingsReport JSON
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class CaseHistoryRecord(Base):
    """Uploaded case-history event log for Layer 8 reality checking."""

    __tablename__ = "case_histories"
    __table_args__ = (Index("ix_case_histories_run_id_created", "run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("csh"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("compile_runs.id", ondelete="CASCADE"), index=True
    )
    source_filename: Mapped[str] = mapped_column(String(255))
    event_log: Mapped[dict[str, Any]] = mapped_column(JSON)   # EventLog JSON
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class RealityRecord(Base):
    """Conformance-checking report produced by Layer 8."""

    __tablename__ = "reality_reports"
    __table_args__ = (Index("ix_reality_reports_run_id_created", "run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rea"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("compile_runs.id", ondelete="CASCADE"), index=True
    )
    report: Mapped[dict[str, Any]] = mapped_column(JSON)   # RealityReport JSON
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TestRunRecord(Base):
    """Test execution report produced by Layer 7."""

    __tablename__ = "test_runs"
    __table_args__ = (Index("ix_test_runs_run_id_created", "run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("trn"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("compile_runs.id", ondelete="CASCADE"), index=True
    )
    report: Mapped[dict[str, Any]] = mapped_column(JSON)   # TestRunReport JSON
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class LLMCall(Base):
    """One row per gateway call (cache hits included), for token accounting and audit."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(32), index=True)
    stage: Mapped[str | None] = mapped_column(String(32))
    tier: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(100))
    prompt_id: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[int]
    cache_key: Mapped[str] = mapped_column(String(64))
    cache_hit: Mapped[bool]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    latency_ms: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
