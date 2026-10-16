"""Cross-reference detector.

Finds patterns like "SOP-CS-014", "POL-FIN-012", "PBK-SEC-001" in source text
and records whether they resolve to a known document in the run.
"""

from __future__ import annotations

import re

from app.schemas.docast import DocAST
from app.schemas.graph import CrossRef
from app.schemas.ir_sop import ExtractionWarning

_XREF_RE = re.compile(
    r"\b(SOP|POL|PBK|SLA|CTL|PRC)-[A-Z0-9][\w-]+",
    re.IGNORECASE,
)


def detect_crossrefs(
    asts: list[DocAST],
) -> tuple[list[CrossRef], list[ExtractionWarning]]:
    """Scan all document texts for cross-document reference patterns.

    A reference resolves if the pattern (case-insensitive prefix) matches the
    filename of another document in the same run.
    """
    # Build a lookup: normalised filename stem → doc_id
    stem_to_doc: dict[str, str] = {}
    for ast in asts:
        stem = ast.filename.rsplit(".", 1)[0].upper()
        stem_to_doc[stem] = ast.document_id

    cross_refs: list[CrossRef] = []
    warnings: list[ExtractionWarning] = []
    seen: set[tuple[str, str, int]] = set()  # (source_doc_id, pattern, char_start) dedup

    for ast in asts:
        for match in _XREF_RE.finditer(ast.text):
            pattern = match.group(0).upper()
            start, end = match.start(), match.end()

            key = (ast.document_id, pattern, start)
            if key in seen:
                continue
            seen.add(key)

            target_doc_id = stem_to_doc.get(pattern)
            resolved = target_doc_id is not None and target_doc_id != ast.document_id

            cross_refs.append(
                CrossRef(
                    pattern=pattern,
                    source_doc_id=ast.document_id,
                    char_start=start,
                    char_end=end,
                    resolved=resolved,
                    target_doc_id=target_doc_id if resolved else None,
                )
            )

            if not resolved:
                warnings.append(
                    ExtractionWarning(
                        code="xd001_unresolved_ref",
                        severity="warning",
                        message=(
                            f"Cross-document reference '{pattern}' in "
                            f"'{ast.filename}' could not be resolved to any document in the run"
                        ),
                        source_quote=pattern,
                    )
                )

    return cross_refs, warnings
