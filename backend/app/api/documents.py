from pathlib import PurePath

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import DocumentDep, ProjectDep, ServicesDep, SessionDep
from app.core.storage import UploadTooLarge
from app.ingest.capabilities import LITE_MESSAGE, can_parse
from app.models import Document, DocumentAST
from app.schemas.api import DocumentOut, DocumentUploadOut, DocumentWithParse, ParseSummary
from app.schemas.docast import DocAST

router = APIRouter(prefix="/api", tags=["documents"])

# Source documents accepted for compilation. The media type is derived from the extension, never
# from the client-supplied Content-Type.
SOURCE_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".txt": "text/plain",
}


def _display_name(raw: str | None) -> str:
    # Keep only the final path component; browsers on Windows may send full paths.
    name = PurePath((raw or "").replace("\\", "/")).name.strip()
    return name[:255] or "upload"


def _upload_out(doc: Document, duplicate: bool) -> DocumentUploadOut:
    return DocumentUploadOut(**DocumentOut.model_validate(doc).model_dump(), duplicate=duplicate)


@router.post("/projects/{project_id}/documents", status_code=201)
def upload_documents(
    project: ProjectDep, files: list[UploadFile], services: ServicesDep, session: SessionDep
) -> list[DocumentUploadOut]:
    # Validate every file type before storing anything, so a bad file rejects the whole batch.
    batch = []
    for upload in files:
        filename = _display_name(upload.filename)
        suffix = PurePath(filename).suffix.lower()
        if suffix not in SOURCE_MEDIA_TYPES:
            allowed = ", ".join(sorted(SOURCE_MEDIA_TYPES))
            raise HTTPException(415, f"{filename}: unsupported file type (allowed: {allowed})")
        if not can_parse(SOURCE_MEDIA_TYPES[suffix]):
            raise HTTPException(415, f"{filename}: {LITE_MESSAGE}")
        batch.append((upload, filename, suffix))

    results: list[DocumentUploadOut] = []
    new_keys: list[str] = []
    try:
        for upload, filename, suffix in batch:
            try:
                stored = services.storage.put(
                    project.id, upload.file, suffix, services.settings.max_upload_bytes
                )
            except UploadTooLarge as exc:
                raise HTTPException(413, f"{filename}: {exc}") from exc

            existing = session.scalar(
                select(Document).where(
                    Document.project_id == project.id, Document.sha256 == stored.sha256
                )
            )
            if existing is not None:
                results.append(_upload_out(existing, duplicate=True))
                continue
            new_keys.append(stored.key)
            doc = Document(
                project_id=project.id,
                filename=filename,
                media_type=SOURCE_MEDIA_TYPES[suffix],
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                storage_key=stored.key,
            )
            session.add(doc)
            session.flush()
            results.append(_upload_out(doc, duplicate=False))
        session.commit()
    except BaseException:
        session.rollback()
        for key in new_keys:
            services.storage.delete(key)
        raise
    return results


def _latest_ast(session, document_id: str) -> DocumentAST | None:
    return session.scalar(
        select(DocumentAST)
        .where(DocumentAST.document_id == document_id)
        .order_by(DocumentAST.created_at.desc())
        .limit(1)
    )


def _with_parse(session, doc: Document) -> DocumentWithParse:
    record = _latest_ast(session, doc.id)
    parsed = None
    if record is not None:
        parsed = ParseSummary(
            ast_id=record.id,
            run_id=record.run_id,
            created_at=record.created_at,
            complete=record.complete,
            stats=record.stats,
        )
    return DocumentWithParse(**DocumentOut.model_validate(doc).model_dump(), parsed=parsed)


@router.get("/projects/{project_id}/documents")
def list_documents(project: ProjectDep, session: SessionDep) -> list[DocumentWithParse]:
    return [_with_parse(session, d) for d in project.documents]


@router.get("/documents/{document_id}")
def get_document(document: DocumentDep, session: SessionDep) -> DocumentWithParse:
    return _with_parse(session, document)


@router.get("/documents/{document_id}/ast")
def document_ast(document: DocumentDep, session: SessionDep) -> DocAST:
    """The latest DocAST for the document (404 until a compile run has ingested it)."""
    record = _latest_ast(session, document.id)
    if record is None:
        raise HTTPException(404, "document not ingested yet; run a compile first")
    return DocAST.model_validate(record.ast)


@router.get("/documents/{document_id}/figures/{node_id}", response_class=FileResponse)
def figure_image(
    document: DocumentDep, node_id: str, services: ServicesDep, session: SessionDep
) -> FileResponse:
    record = _latest_ast(session, document.id)
    if record is None:
        raise HTTPException(404, "document not ingested yet")
    try:
        node = DocAST.model_validate(record.ast).node(node_id)
    except KeyError as exc:
        raise HTTPException(404, f"no node {node_id}") from exc
    if node.figure is None or not node.figure.image_key:
        raise HTTPException(404, f"node {node_id} has no image")
    path = services.storage.path(node.figure.image_key)
    if not path.is_file():
        raise HTTPException(410, "stored image is missing")
    return FileResponse(path, media_type="image/png")


@router.get("/documents/{document_id}/file", response_class=FileResponse)
def document_file(document: DocumentDep, services: ServicesDep) -> FileResponse:
    path = services.storage.path(document.storage_key)
    if not path.is_file():
        raise HTTPException(410, "stored file is missing")
    return FileResponse(
        path,
        media_type=document.media_type,
        filename=document.filename,
        content_disposition_type="inline",
    )


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document: DocumentDep, services: ServicesDep, session: SessionDep) -> None:
    key = document.storage_key
    session.delete(document)
    session.commit()
    services.storage.delete(key)  # key is unique per (project, content), so nothing else uses it
