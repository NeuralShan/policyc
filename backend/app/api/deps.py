from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import User, UserDep, assert_can_write, get_current_user
from app.core.services import Services
from app.models import CompileRun, Document, Project
from app.pipeline.executor import RunExecutor

__all__ = ["CurrentUser", "assert_can_write", "check_project_access"]

CurrentUser = UserDep
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_services(request: Request) -> Services:
    return request.app.state.services


def get_executor(request: Request) -> RunExecutor:
    return request.app.state.executor


def get_session(services: Annotated[Services, Depends(get_services)]) -> Iterator[Session]:
    with services.sessions() as session:
        yield session


ServicesDep = Annotated[Services, Depends(get_services)]
ExecutorDep = Annotated[RunExecutor, Depends(get_executor)]
SessionDep = Annotated[Session, Depends(get_session)]


def get_or_404[T](session: Session, model: type[T], id_: str) -> T:
    obj = session.get(model, id_)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} {id_} not found")
    return obj


def check_project_access(user: User, project: Project, method: str = "GET") -> None:
    """Central ownership rule (no-op while auth is disabled).

    Public projects (owner_uid NULL, e.g. bundled demos) are readable by everyone and read-only
    for everyone. Private projects are visible, and writable, only to their owner (404 otherwise).
    Any write by a guest is 401 "Sign in required".
    """
    if user.open_access:
        return
    write = method.upper() not in _SAFE_METHODS
    if write:
        assert_can_write(user)
    if project.owner_uid is None:
        if write:
            raise HTTPException(status_code=403, detail="Demo projects are read-only")
        return
    if project.owner_uid != user.uid:
        raise HTTPException(status_code=404, detail=f"Project {project.id} not found")


def get_project(
    project_id: str,
    session: SessionDep,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> Project:
    project = get_or_404(session, Project, project_id)
    check_project_access(user, project, request.method)
    return project


def get_document(
    document_id: str,
    session: SessionDep,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> Document:
    doc = get_or_404(session, Document, document_id)
    check_project_access(user, get_or_404(session, Project, doc.project_id), request.method)
    return doc


def get_run(
    run_id: str,
    session: SessionDep,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> CompileRun:
    run = get_or_404(session, CompileRun, run_id)
    check_project_access(user, get_or_404(session, Project, run.project_id), request.method)
    return run


def get_existing_run_id(
    run_id: str,
    services: ServicesDep,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> str:
    """404-checks a run without holding a session open (for long-lived streaming responses)."""
    with services.sessions() as session:
        run = get_or_404(session, CompileRun, run_id)
        check_project_access(user, get_or_404(session, Project, run.project_id), request.method)
    return run_id


ProjectDep = Annotated[Project, Depends(get_project)]
DocumentDep = Annotated[Document, Depends(get_document)]
RunDep = Annotated[CompileRun, Depends(get_run)]
RunIdDep = Annotated[str, Depends(get_existing_run_id)]
