"""Symbol pass: extract roles, artifacts, systems and terms from a DocAST.

This is the first pass of the Layer 2 extraction subgraph.  It builds the SymbolTable (glossary)
that the structure pass uses to anchor actors, artifacts and systems to stable IDs.
"""

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.llm.gateway import CallContext, LLMGateway, LLMOutputError, LLMUnavailable
from app.schemas.docast import DocAST
from app.schemas.ir_sop import (
    ArtifactRef,
    ExtractionWarning,
    RoleRef,
    SymbolTable,
    SystemRef,
    TermDef,
)
from app.schemas.provenance import SourceSpan

# Truncate to avoid blowing the context window on very large SOPs.
MAX_TEXT_CHARS = 12_000


# ---------------------------------------------------------------------------
# LLM reply schema
# ---------------------------------------------------------------------------


class _SymbolEntry(BaseModel):
    id: str
    name: str
    quote: str
    abbreviation: str | None = None
    description: str | None = None
    definition: str | None = None


class SymbolReply(BaseModel):
    roles: list[_SymbolEntry] = Field(default_factory=list)
    artifacts: list[_SymbolEntry] = Field(default_factory=list)
    systems: list[_SymbolEntry] = Field(default_factory=list)
    terms: list[_SymbolEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    """Convert a name to a lowercase_snake_case slug."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "unknown"


def _find_span(ast: DocAST, quote: str) -> SourceSpan | None:
    """Find the first occurrence of *quote* in ast.text and return a SourceSpan."""
    idx = ast.text.find(quote)
    if idx == -1:
        return None
    return SourceSpan(
        document_id=ast.document_id,
        char_start=idx,
        char_end=idx + len(quote),
        quote=quote,
    )


def _normalise_id(raw_id: str, existing: set[str]) -> str:
    """Ensure the id is slug-formatted and unique."""
    base = _slug(raw_id)
    if base not in existing:
        return base
    i = 2
    while f"{base}_{i}" in existing:
        i += 1
    return f"{base}_{i}"


def _grounded_span(entry: _SymbolEntry, ast: DocAST) -> list[SourceSpan]:
    span = _find_span(ast, entry.quote)
    return [span] if span else []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_symbols(
    ast: DocAST,
    llm: LLMGateway,
    context: CallContext,
) -> tuple[SymbolTable, list[ExtractionWarning]]:
    """Run the symbol pass.  Returns (SymbolTable, warnings)."""
    text = ast.text[:MAX_TEXT_CHARS]
    warnings: list[ExtractionWarning] = []

    try:
        reply: SymbolReply = llm.structured(
            "symbol_pass",
            SymbolReply,
            {"filename": ast.filename, "text": text},
            context=context,
        )
    except (LLMUnavailable, LLMOutputError) as exc:
        warnings.append(
            ExtractionWarning(
                code="symbol_pass_failed",
                message=f"symbol extraction unavailable ({exc}); using empty symbol table",
            )
        )
        return SymbolTable(), warnings

    used_ids: set[str] = set()

    def _build_role(e: _SymbolEntry) -> RoleRef | None:
        spans = _grounded_span(e, ast)
        if not spans:
            warnings.append(
                ExtractionWarning(
                    code="symbol_ungrounded",
                    message=f"role {e.name!r}: quote not found in document text",
                )
            )
        rid = _normalise_id(e.id or _slug(e.name), used_ids)
        used_ids.add(rid)
        return RoleRef(
            id=rid, name=e.name, description=e.description, source_spans=spans
        )

    def _build_artifact(e: _SymbolEntry) -> ArtifactRef | None:
        spans = _grounded_span(e, ast)
        if not spans:
            warnings.append(
                ExtractionWarning(
                    code="symbol_ungrounded",
                    message=f"artifact {e.name!r}: quote not found in document text",
                )
            )
        aid = _normalise_id(e.id or _slug(e.name), used_ids)
        used_ids.add(aid)
        return ArtifactRef(
            id=aid, name=e.name, abbreviation=e.abbreviation, source_spans=spans
        )

    def _build_system(e: _SymbolEntry) -> SystemRef | None:
        spans = _grounded_span(e, ast)
        if not spans:
            warnings.append(
                ExtractionWarning(
                    code="symbol_ungrounded",
                    message=f"system {e.name!r}: quote not found in document text",
                )
            )
        sid = _normalise_id(e.id or _slug(e.name), used_ids)
        used_ids.add(sid)
        return SystemRef(id=sid, name=e.name, source_spans=spans)

    def _build_term(e: _SymbolEntry) -> TermDef | None:
        spans = _grounded_span(e, ast)
        tid = _normalise_id(e.id or _slug(e.name), used_ids)
        used_ids.add(tid)
        return TermDef(id=tid, name=e.name, definition=e.definition, source_spans=spans)

    table = SymbolTable(
        roles=[r for e in reply.roles if (r := _build_role(e)) is not None],
        artifacts=[a for e in reply.artifacts if (a := _build_artifact(e)) is not None],
        systems=[s for e in reply.systems if (s := _build_system(e)) is not None],
        terms=[t for e in reply.terms if (t := _build_term(e)) is not None],
    )
    return table, warnings


def symbol_table_json(table: SymbolTable) -> str:
    """Serialise the symbol table for injection into the structure pass prompt."""
    data: dict[str, Any] = {
        "roles": [{"id": r.id, "name": r.name} for r in table.roles],
        "artifacts": [
            {
                "id": a.id,
                "name": a.name,
                **({"abbreviation": a.abbreviation} if a.abbreviation else {}),
            }
            for a in table.artifacts
        ],
        "systems": [{"id": s.id, "name": s.name} for s in table.systems],
        "terms": [{"id": t.id, "name": t.name} for t in table.terms],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)
