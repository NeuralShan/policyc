from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import ProjectDep, SessionDep
from app.models import CompileRun, Document, Project
from app.schemas.api import ProjectCreate, ProjectOut, ProjectSummary

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", status_code=201)
def create_project(body: ProjectCreate, session: SessionDep) -> ProjectOut:
    project = Project(name=body.name.strip(), description=body.description.strip())
    session.add(project)
    session.commit()
    return ProjectOut.model_validate(project)


@router.get("")
def list_projects(session: SessionDep) -> list[ProjectSummary]:
    doc_counts = (
        select(Document.project_id, func.count().label("n"))
        .group_by(Document.project_id)
        .subquery()
    )
    run_counts = (
        select(CompileRun.project_id, func.count().label("n"))
        .group_by(CompileRun.project_id)
        .subquery()
    )
    rows = session.execute(
        select(Project, func.coalesce(doc_counts.c.n, 0), func.coalesce(run_counts.c.n, 0))
        .outerjoin(doc_counts, doc_counts.c.project_id == Project.id)
        .outerjoin(run_counts, run_counts.c.project_id == Project.id)
        .order_by(Project.created_at.desc())
    ).all()
    return [
        ProjectSummary(
            **ProjectOut.model_validate(p).model_dump(), document_count=docs, run_count=runs
        )
        for p, docs, runs in rows
    ]


@router.get("/{project_id}")
def get_project(project: ProjectDep) -> ProjectSummary:
    return ProjectSummary(
        **ProjectOut.model_validate(project).model_dump(),
        document_count=len(project.documents),
        run_count=len(project.runs),
    )
