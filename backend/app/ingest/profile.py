"""Document profile: what kind of document this is, plus control metadata (code, version, owner...).

The model must back every metadata value with a verbatim quote. Quotes are checked against the
document text and running headers/footers; a value whose quote isn't found is dropped with a
``profile_ungrounded`` warning instead of being trusted.
"""

import re

from pydantic import BaseModel, Field

from app.core.llm.gateway import CallContext, LLMGateway, LLMOutputError, LLMUnavailable
from app.schemas.docast import DocAST, DocClass, DocumentProfile, GroundedValue, IngestWarning

EXCERPT_CHARS = 6000
FIELDS = ("title", "document_code", "version", "effective_date", "owner")


class ProfileReply(BaseModel):
    doc_class: DocClass = Field(
        description="procedural: steps/actors/sequence (SOPs, playbooks); normative: rules, "
        "limits, obligations (policies); descriptive: facts, results (reports); mixed; other"
    )
    rationale: str = Field(description="One sentence: why this class")
    title: GroundedValue | None = None
    document_code: GroundedValue | None = Field(default=None, description="e.g. 'PRC-006'")
    version: GroundedValue | None = None
    effective_date: GroundedValue | None = None
    owner: GroundedValue | None = Field(default=None, description="Owning role or department")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def profile_document(
    ast: DocAST, llm: LLMGateway, context: CallContext
) -> tuple[DocumentProfile | None, list[IngestWarning]]:
    furniture = "\n".join(ast.furniture)
    try:
        reply = llm.structured(
            "document_profile",
            ProfileReply,
            {
                "filename": ast.filename,
                "furniture": furniture or "(none)",
                "excerpt": ast.text[:EXCERPT_CHARS],
            },
            context=context,
        )
    except (LLMUnavailable, LLMOutputError) as exc:
        return None, [
            IngestWarning(
                code="profile_pending",
                message=f"document not profiled ({exc}); it will be retried on the next run",
            )
        ]

    haystack = _squash(f"{ast.text}\n{furniture}\n{ast.filename}")
    warnings: list[IngestWarning] = []
    grounded: dict[str, GroundedValue | None] = {}
    for name in FIELDS:
        value: GroundedValue | None = getattr(reply, name)
        if value is not None and _squash(value.quote) not in haystack:
            warnings.append(
                IngestWarning(
                    code="profile_ungrounded",
                    message=f"{name} {value.value!r} dropped: quote {value.quote!r} not found",
                )
            )
            value = None
        grounded[name] = value
    profile = DocumentProfile(
        doc_class=reply.doc_class,
        rationale=reply.rationale,
        model=llm.model_name(llm.prompts.get("document_profile").tier),
        **grounded,
    )
    return profile, warnings
