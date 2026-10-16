"""Request/response models for the HTTP API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import RunStatus, StageEventStatus


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class ProjectOut(_ORM):
    id: str
    name: str
    description: str
    created_at: datetime


class ProjectSummary(ProjectOut):
    document_count: int
    run_count: int


class DocumentOut(_ORM):
    id: str
    project_id: str
    filename: str
    media_type: str
    sha256: str
    size_bytes: int
    uploaded_at: datetime


class DocumentUploadOut(DocumentOut):
    duplicate: bool = Field(description="An identical file was already in the project")


class ParseSummary(BaseModel):
    ast_id: str
    run_id: str | None
    created_at: datetime
    complete: bool
    stats: dict[str, Any]


class DocumentWithParse(DocumentOut):
    parsed: ParseSummary | None = Field(description="Latest ingest result, if any")


class RunCreate(BaseModel):
    document_ids: list[str] | None = Field(
        default=None, description="Documents to compile; all project documents if omitted"
    )


class RunEventOut(_ORM):
    id: int
    stage: str
    status: StageEventStatus
    message: str
    created_at: datetime


class RunOut(_ORM):
    id: str
    project_id: str
    status: RunStatus
    document_ids: list[str]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunDetail(RunOut):
    artifacts: dict[str, Any]
    events: list[RunEventOut]


class StageOut(BaseModel):
    key: str
    label: str
    layer: int
    compiler_analogy: str
    description: str
    implemented: bool
