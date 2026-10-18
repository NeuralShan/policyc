from fastapi import APIRouter
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, ProjectDep, SessionDep, assert_can_write
from app.models import CompileRun, Document, Project
from app.schemas.api import ProjectCreate, ProjectOut, ProjectSummary

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", status_code=201)
def create_project(body: ProjectCreate, session: SessionDep, user: CurrentUser) -> ProjectOut:
    assert_can_write(user)
    project = Project(
        name=body.name.strip(), description=body.description.strip(), owner_uid=user.uid
    )
    session.add(project)
    session.commit()
    return ProjectOut.model_validate(project)


@router.get("")
def list_projects(session: SessionDep, user: CurrentUser) -> list[ProjectSummary]:
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
    query = (
        select(Project, func.coalesce(doc_counts.c.n, 0), func.coalesce(run_counts.c.n, 0))
        .outerjoin(doc_counts, doc_counts.c.project_id == Project.id)
        .outerjoin(run_counts, run_counts.c.project_id == Project.id)
        .order_by(Project.created_at.desc())
    )
    if not user.open_access:  # public (demo) projects plus the caller's own
        query = query.where(or_(Project.owner_uid.is_(None), Project.owner_uid == user.uid))
    rows = session.execute(query).all()
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
