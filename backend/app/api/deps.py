from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.services import Services
from app.models import CompileRun, Document, Project
from app.pipeline.executor import RunExecutor


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


def get_project(project_id: str, session: SessionDep) -> Project:
    return get_or_404(session, Project, project_id)


def get_document(document_id: str, session: SessionDep) -> Document:
    return get_or_404(session, Document, document_id)


def get_run(run_id: str, session: SessionDep) -> CompileRun:
    return get_or_404(session, CompileRun, run_id)


def get_existing_run_id(run_id: str, services: ServicesDep) -> str:
    """404-checks a run without holding a session open (for long-lived streaming responses)."""
    with services.sessions() as session:
        get_or_404(session, CompileRun, run_id)
    return run_id


ProjectDep = Annotated[Project, Depends(get_project)]
DocumentDep = Annotated[Document, Depends(get_document)]
RunDep = Annotated[CompileRun, Depends(get_run)]
RunIdDep = Annotated[str, Depends(get_existing_run_id)]
