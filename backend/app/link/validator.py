"""networkx-based in-memory graph loader and structural validator.

Parses the emitted .cypher text into a networkx DiGraph and runs basic
structural checks:
- every node referenced in a relationship exists as a declared node
- every Process has at least one HAS_STEP or HAS_DECISION edge
- no self-loops
"""

from __future__ import annotations

import re

import networkx as nx

# Match: MERGE (:Label {id: "some-id"});
_NODE_RE = re.compile(
    r'MERGE\s*\(:(\w+)\s*\{[^}]*?id:\s*"([^"]+)"[^}]*\}\)',
    re.IGNORECASE,
)

# Match: MERGE (alias:Label {id: "id"})-[:REL...]->(alias2:Label2 {id: "id2"});
# Also: MERGE (n {id: "id"})-[:REL]->(m {id: "id2"});
_REL_RE = re.compile(
    r'MERGE\s*\([^)]*\{[^}]*id:\s*"([^"]+)"[^}]*\}\)'
    r'\s*-\[:(\w+)[^\]]*\]->\s*'
    r'\([^)]*\{[^}]*id:\s*"([^"]+)"[^}]*\}\)',
    re.IGNORECASE,
)


def load_graph(cypher_text: str) -> nx.DiGraph:
    """Parse MERGE statements from .cypher text and build a networkx DiGraph."""
    g: nx.DiGraph = nx.DiGraph()

    for line in cypher_text.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue

        node_match = _NODE_RE.search(line)
        if node_match and "-[:" not in line:
            label, node_id = node_match.group(1), node_match.group(2)
            if not g.has_node(node_id):
                g.add_node(node_id, label=label)
            continue

        rel_match = _REL_RE.search(line)
        if rel_match:
            from_id, rel_type, to_id = (
                rel_match.group(1),
                rel_match.group(2),
                rel_match.group(3),
            )
            if not g.has_node(from_id):
                g.add_node(from_id, label="Unknown")
            if not g.has_node(to_id):
                g.add_node(to_id, label="Unknown")
            g.add_edge(from_id, to_id, rel=rel_type)

    return g


def validate_graph(g: nx.DiGraph) -> list[str]:
    """Return a list of structural error strings (empty = valid)."""
    errors: list[str] = []

    # Self-loops
    for node in nx.nodes_with_selfloops(g):
        errors.append(f"Self-loop on node {node!r}")

    # Dangling references: nodes whose label is "Unknown"
    for node, data in g.nodes(data=True):
        if data.get("label") == "Unknown":
            errors.append(f"Node {node!r} referenced in relationship but never declared")

    # Every Process node must have at least one outgoing HAS_STEP or HAS_DECISION edge
    process_nodes = [n for n, d in g.nodes(data=True) if d.get("label") == "Process"]
    for proc in process_nodes:
        outgoing_rels = {g[proc][nb]["rel"] for nb in g.successors(proc)}
        if not outgoing_rels & {"HAS_STEP", "HAS_DECISION"}:
            errors.append(f"Process {proc!r} has no HAS_STEP or HAS_DECISION edges")

    return errors
