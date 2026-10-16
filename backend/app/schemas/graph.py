"""Layer 3 linked-IR schema.

Produced by the link stage; sits on top of SopIR and records the results of
entity resolution, cross-reference detection and graph emission.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.ir_sop import ExtractionWarning

LINKED_IR_VERSION = 1


class CanonicalEntity(BaseModel):
    """One entity after cross-document deduplication."""

    canonical_id: str
    kind: Literal["role", "artifact", "system", "term"]
    name: str
    aliases: list[str] = Field(default_factory=list)  # IDs merged into this one
    source_doc_ids: list[str] = Field(default_factory=list)


class EntityMerge(BaseModel):
    """Record that ``loser_id`` was merged into ``winner_id``."""

    winner_id: str
    loser_id: str
    winner_name: str
    loser_name: str
    confidence: float
    method: Literal["exact", "overlap"]


class CrossRef(BaseModel):
    """A cross-document reference detected in source text."""

    pattern: str  # e.g. "SOP-FIN-012"
    source_doc_id: str
    char_start: int
    char_end: int
    resolved: bool
    target_doc_id: str | None = None


class GraphStats(BaseModel):
    nodes: int = 0
    edges: int = 0
    processes: int = 0
    steps: int = 0
    decisions: int = 0
    roles: int = 0
    artifacts: int = 0
    systems: int = 0
    merges: int = 0
    cross_refs: int = 0
    unresolved_refs: int = 0
    warnings: int = 0


class LinkedIR(BaseModel):
    version: int = LINKED_IR_VERSION
    run_id: str
    sop_ir_id: str = ""
    canonical_entities: list[CanonicalEntity] = Field(default_factory=list)
    entity_merges: list[EntityMerge] = Field(default_factory=list)
    cross_refs: list[CrossRef] = Field(default_factory=list)
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    stats: GraphStats = Field(default_factory=GraphStats)
    cypher_sha256: str | None = None  # hex digest of the emitted .cypher for determinism check

    def graph_data(self, ir_json: dict[str, Any]) -> dict[str, Any]:
        """Derive React-Flow-compatible {nodes, edges} from stored IR JSON."""
        nodes: list[dict] = []
        edges: list[dict] = []

        symbols = ir_json.get("symbols") or {}
        for role in symbols.get("roles", []):
            nodes.append({"id": role["id"], "type": "role", "data": {"label": role["name"]}})
        for art in symbols.get("artifacts", []):
            nodes.append({"id": art["id"], "type": "artifact", "data": {"label": art["name"]}})
        for sys in symbols.get("systems", []):
            nodes.append({"id": sys["id"], "type": "system", "data": {"label": sys["name"]}})

        for proc in ir_json.get("processes", []):
            proc_id = proc["id"]
            nodes.append({"id": proc_id, "type": "process", "data": {"label": proc["name"]}})
            for step in proc.get("steps", []):
                sid = step["id"]
                nodes.append(
                    {
                        "id": sid,
                        "type": "step",
                        "data": {
                            "label": step.get("action", sid),
                            "modal": step.get("modal"),
                        },
                    }
                )
                edges.append({"id": f"{proc_id}->{sid}", "source": proc_id, "target": sid})
                if step.get("actor_role_id"):
                    edges.append(
                        {
                            "id": f"{sid}->role-{step['actor_role_id']}",
                            "source": sid,
                            "target": step["actor_role_id"],
                            "label": "PERFORMED_BY",
                        }
                    )
            for dec in proc.get("decisions", []):
                did = dec["id"]
                nodes.append(
                    {
                        "id": did,
                        "type": "decision",
                        "data": {"label": dec.get("question", did)},
                    }
                )
                edges.append({"id": f"{proc_id}->{did}", "source": proc_id, "target": did})
            for trans in proc.get("transitions", []):
                edges.append(
                    {
                        "id": f"tr-{trans['from_id']}->{trans['to_id']}",
                        "source": trans["from_id"],
                        "target": trans["to_id"],
                        "label": trans.get("label") or "",
                    }
                )
        return {"nodes": nodes, "edges": edges}
