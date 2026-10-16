"""Linker service: top-level orchestrator for Layer 3.

Resolves entities, detects cross-references, emits the .cypher file and
validates the resulting graph with networkx.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.services import Services
from app.link.emitter import cypher_sha256, emit_cypher
from app.link.resolver import resolve_entities
from app.link.validator import load_graph, validate_graph
from app.link.xref import detect_crossrefs
from app.models import CypherArtifactRecord, LinkedIRRecord
from app.schemas.docast import DocAST
from app.schemas.graph import GraphStats, LinkedIR
from app.schemas.ir_sop import ExtractionWarning, SopIR

log = logging.getLogger(__name__)


def get_linker(services: Services) -> Linker:
    return services.singleton("linker", lambda: Linker(services))


class Linker:
    def __init__(self, services: Services) -> None:
        self._services = services

    def link(
        self,
        asts: list[DocAST],
        ir: SopIR,
        run_id: str,
        sop_ir_id: str = "",
    ) -> tuple[LinkedIR, str]:
        """Run the full linking pipeline.

        Returns (linked_ir, cypher_text).
        """
        all_warnings: list[ExtractionWarning] = []

        # 1. Entity resolution
        canonical_entities, entity_merges, _canonical_map, resolver_warnings = resolve_entities(ir)
        all_warnings.extend(resolver_warnings)

        # 2. Cross-reference detection
        cross_refs, xref_warnings = detect_crossrefs(asts)
        all_warnings.extend(xref_warnings)

        # 3. Emit .cypher (deterministic)
        linked_partial = LinkedIR(
            run_id=run_id,
            sop_ir_id=sop_ir_id,
            canonical_entities=canonical_entities,
            entity_merges=entity_merges,
            cross_refs=cross_refs,
            warnings=all_warnings,
        )
        cypher_text = emit_cypher(ir, linked_partial, run_id)
        sha = cypher_sha256(cypher_text)

        # 4. Validate with networkx
        graph = load_graph(cypher_text)
        graph_errors = validate_graph(graph)
        for err in graph_errors:
            all_warnings.append(
                ExtractionWarning(
                    code="graph_validation_error",
                    severity="error",
                    message=err,
                )
            )
        if graph_errors:
            log.warning("graph validation produced %d error(s)", len(graph_errors))

        # 5. Build stats
        node_counts: dict[str, int] = {}
        for _, data in graph.nodes(data=True):
            label = data.get("label", "Unknown")
            node_counts[label] = node_counts.get(label, 0) + 1

        stats = GraphStats(
            nodes=graph.number_of_nodes(),
            edges=graph.number_of_edges(),
            processes=node_counts.get("Process", 0),
            steps=node_counts.get("Step", 0),
            decisions=node_counts.get("Decision", 0),
            roles=node_counts.get("Role", 0),
            artifacts=node_counts.get("Artifact", 0),
            systems=node_counts.get("System", 0),
            merges=len(entity_merges),
            cross_refs=len(cross_refs),
            unresolved_refs=sum(1 for r in cross_refs if not r.resolved),
            warnings=len(all_warnings),
        )

        linked = LinkedIR(
            run_id=run_id,
            sop_ir_id=sop_ir_id,
            canonical_entities=canonical_entities,
            entity_merges=entity_merges,
            cross_refs=cross_refs,
            warnings=all_warnings,
            stats=stats,
            cypher_sha256=sha,
        )

        log.info(
            "link: %d nodes  %d edges  %d merges  %d xrefs  %d warnings",
            stats.nodes,
            stats.edges,
            stats.merges,
            stats.cross_refs,
            stats.warnings,
        )
        return linked, cypher_text

    def save(
        self,
        linked: LinkedIR,
        cypher_text: str,
    ) -> tuple[LinkedIRRecord, CypherArtifactRecord]:
        with self._services.sessions() as session:
            linked_record = LinkedIRRecord(
                run_id=linked.run_id,
                linked=linked.model_dump(mode="json"),
                stats=linked.stats.model_dump(),
            )
            session.add(linked_record)

            cypher_record = CypherArtifactRecord(
                run_id=linked.run_id,
                sha256=linked.cypher_sha256 or "",
                cypher_text=cypher_text,
            )
            session.add(cypher_record)
            session.commit()
            session.refresh(linked_record)
            session.refresh(cypher_record)
            return linked_record, cypher_record

    def load(self, run_id: str) -> LinkedIR | None:
        with self._services.sessions() as session:
            stmt = (
                select(LinkedIRRecord)
                .where(LinkedIRRecord.run_id == run_id)
                .order_by(LinkedIRRecord.created_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            if record is None:
                return None
            return LinkedIR.model_validate(record.linked)

    def load_cypher(self, run_id: str) -> str | None:
        with self._services.sessions() as session:
            stmt = (
                select(CypherArtifactRecord)
                .where(CypherArtifactRecord.run_id == run_id)
                .order_by(CypherArtifactRecord.created_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            return record.cypher_text if record else None

    def load_record(self, run_id: str) -> LinkedIRRecord | None:
        with self._services.sessions() as session:
            stmt = (
                select(LinkedIRRecord)
                .where(LinkedIRRecord.run_id == run_id)
                .order_by(LinkedIRRecord.created_at.desc())
                .limit(1)
            )
            return session.scalars(stmt).first()
