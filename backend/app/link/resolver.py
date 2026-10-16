"""Entity resolver: deduplicate roles/artifacts/systems across multiple SOP documents.

Uses Jaccard token-overlap similarity.  No LLM calls — pure string comparison.

Thresholds
----------
≥ 0.95  exact / near-exact  → auto-merge (method="exact")
0.60 – 0.95  substantial overlap → auto-merge (method="overlap") with lower confidence
< 0.60  treated as distinct entities
"""

from __future__ import annotations

import re

from app.schemas.graph import CanonicalEntity, EntityMerge
from app.schemas.ir_sop import ExtractionWarning, SopIR

_EXACT_THRESHOLD = 0.95
_OVERLAP_THRESHOLD = 0.60


def _tokens(name: str) -> frozenset[str]:
    return frozenset(re.findall(r"\b\w+\b", name.lower()))


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _merge_list(
    items: list,
    kind: str,
    canonical_map: dict[str, str],  # loser_id → winner_id (mutated in place)
) -> tuple[list[CanonicalEntity], list[EntityMerge]]:
    """Deduplicate a flat list of refs (roles / artifacts / systems / terms)."""
    entities: list[CanonicalEntity] = []
    merges: list[EntityMerge] = []

    for item in items:
        item_id: str = item.id
        item_name: str = item.name
        doc_id: str = getattr(item, "source_doc_id", "")

        matched = False
        for ent in entities:
            score = _jaccard(item_name, ent.name)
            if score >= _OVERLAP_THRESHOLD:
                method = "exact" if score >= _EXACT_THRESHOLD else "overlap"
                merges.append(
                    EntityMerge(
                        winner_id=ent.canonical_id,
                        loser_id=item_id,
                        winner_name=ent.name,
                        loser_name=item_name,
                        confidence=round(score, 3),
                        method=method,
                    )
                )
                canonical_map[item_id] = ent.canonical_id
                if item_id not in ent.aliases:
                    ent.aliases.append(item_id)
                if doc_id and doc_id not in ent.source_doc_ids:
                    ent.source_doc_ids.append(doc_id)
                matched = True
                break

        if not matched:
            canonical_map[item_id] = item_id
            entities.append(
                CanonicalEntity(
                    canonical_id=item_id,
                    kind=kind,
                    name=item_name,
                    source_doc_ids=[doc_id] if doc_id else [],
                )
            )

    return entities, merges


def resolve_entities(
    ir: SopIR,
) -> tuple[list[CanonicalEntity], list[EntityMerge], dict[str, str], list[ExtractionWarning]]:
    """Resolve entities in the IR and return canonical entities + merge records.

    Returns
    -------
    (canonical_entities, merges, canonical_map, warnings)
    canonical_map maps every original entity ID to its canonical ID.
    """
    symbols = ir.symbols
    canonical_map: dict[str, str] = {}
    all_entities: list[CanonicalEntity] = []
    all_merges: list[EntityMerge] = []

    role_ents, role_merges = _merge_list(symbols.roles, "role", canonical_map)
    art_ents, art_merges = _merge_list(symbols.artifacts, "artifact", canonical_map)
    sys_ents, sys_merges = _merge_list(symbols.systems, "system", canonical_map)
    term_ents, term_merges = _merge_list(symbols.terms, "term", canonical_map)

    all_entities = role_ents + art_ents + sys_ents + term_ents
    all_merges = role_merges + art_merges + sys_merges + term_merges

    warnings: list[ExtractionWarning] = []
    for merge in all_merges:
        if merge.method == "overlap":
            warnings.append(
                ExtractionWarning(
                    code="entity_merge_overlap",
                    severity="info",
                    message=(
                        f"Merged '{merge.loser_name}' (id={merge.loser_id}) into "
                        f"'{merge.winner_name}' (id={merge.winner_id}) "
                        f"[confidence={merge.confidence:.2f}]"
                    ),
                )
            )

    return all_entities, all_merges, canonical_map, warnings
