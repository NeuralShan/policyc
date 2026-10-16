"""ST: Structural checks (ST001–ST003, ST006–ST007) using networkx.

ST001 unreachable step
ST002 dead end (step/decision with no outgoing edges and not terminal)
ST003 loop with no exit
ST006 process has no trigger
ST007 process has no terminal outcome
"""

from __future__ import annotations

import networkx as nx

from app.analyze.registry import register
from app.schemas.finding import CheckTier, Diagnostic, Severity
from app.schemas.graph import LinkedIR
from app.schemas.ir_sop import Process, SopIR, StepKind


def _build_flow_graph(proc: Process) -> nx.DiGraph:
    """Build a directed graph from a process's steps, decisions, transitions."""
    g: nx.DiGraph = nx.DiGraph()

    for step in proc.steps:
        g.add_node(step.id, kind="step", obj=step)
    for dec in proc.decisions:
        g.add_node(dec.id, kind="decision", obj=dec)
    g.add_node("END", kind="terminal")

    for t in proc.transitions:
        if not g.has_node(t.from_id):
            g.add_node(t.from_id, kind="unknown")
        if not g.has_node(t.to_id):
            g.add_node(t.to_id, kind="unknown")
        g.add_edge(t.from_id, t.to_id)

    for dec in proc.decisions:
        for branch in dec.branches:
            nxt = branch.next_step_id
            if not g.has_node(nxt):
                g.add_node(nxt, kind="unknown")
            g.add_edge(dec.id, nxt)

    return g


def _first_step_id(proc: Process) -> str | None:
    """Heuristic: first step in declaration order (often also first in flow)."""
    return proc.steps[0].id if proc.steps else None


@register("ST", "Structural checks")
def structural_checks(ir: SopIR, _linked: LinkedIR | None) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    for proc in ir.processes:
        g = _build_flow_graph(proc)
        first_id = _first_step_id(proc)

        # ST006 — no trigger
        if proc.trigger is None:
            diags.append(
                Diagnostic(
                    code="ST006",
                    severity=Severity.WARNING,
                    message=(
                        f"Process '{proc.name}' has no trigger / entry criteria defined"
                    ),
                    process_id=proc.id,
                    check_tier=CheckTier.DETERMINISTIC,
                )
            )

        # ST007 — no terminal outcome
        terminal_steps = [
            s for s in proc.steps if s.kind == StepKind.TERMINAL
        ]
        has_end_edge = "END" in g.nodes and any(g.predecessors("END"))
        if not terminal_steps and not has_end_edge:
            diags.append(
                Diagnostic(
                    code="ST007",
                    severity=Severity.WARNING,
                    message=(
                        f"Process '{proc.name}' has no terminal outcome (no TERMINAL step "
                        "and no transition to END)"
                    ),
                    process_id=proc.id,
                    check_tier=CheckTier.DETERMINISTIC,
                )
            )

        # ST001 — unreachable step: no predecessors AND not the first step
        step_and_dec_ids = {s.id for s in proc.steps} | {d.id for d in proc.decisions}
        for node_id in step_and_dec_ids:
            if g.in_degree(node_id) == 0 and node_id != first_id:
                data = g.nodes.get(node_id, {})
                obj = data.get("obj")
                spans = getattr(obj, "source_spans", []) if obj else []
                diags.append(
                    Diagnostic(
                        code="ST001",
                        severity=Severity.WARNING,
                        message=(
                            f"Step/decision '{node_id}' in process '{proc.name}' "
                            "is unreachable (no incoming transition)"
                        ),
                        process_id=proc.id,
                        step_id=node_id if node_id in {s.id for s in proc.steps} else None,
                        decision_id=(
                            node_id if node_id in {d.id for d in proc.decisions} else None
                        ),
                        source_spans=spans,
                        check_tier=CheckTier.DETERMINISTIC,
                    )
                )

        # ST002 — dead end: node with no outgoing edges and not terminal/END
        terminal_ids = {s.id for s in proc.steps if s.kind == StepKind.TERMINAL} | {"END"}
        for node_id in step_and_dec_ids:
            if g.out_degree(node_id) == 0 and node_id not in terminal_ids:
                data = g.nodes.get(node_id, {})
                obj = data.get("obj")
                spans = getattr(obj, "source_spans", []) if obj else []
                diags.append(
                    Diagnostic(
                        code="ST002",
                        severity=Severity.WARNING,
                        message=(
                            f"Step/decision '{node_id}' in process '{proc.name}' "
                            "is a dead end (no outgoing transition)"
                        ),
                        process_id=proc.id,
                        step_id=node_id if node_id in {s.id for s in proc.steps} else None,
                        decision_id=(
                            node_id if node_id in {d.id for d in proc.decisions} else None
                        ),
                        source_spans=spans,
                        check_tier=CheckTier.DETERMINISTIC,
                    )
                )

        # ST003 — cycle with no exit to END
        if g.number_of_nodes() > 1:
            try:
                cycles = list(nx.simple_cycles(g))
            except nx.NetworkXNoCycle:
                cycles = []
            for cycle in cycles:
                cycle_set = set(cycle)
                # check if any node in the cycle can reach END
                can_exit = any(
                    nx.has_path(g, n, "END")
                    for n in cycle_set
                    if g.has_node("END")
                )
                if not can_exit:
                    diags.append(
                        Diagnostic(
                            code="ST003",
                            severity=Severity.ERROR,
                            message=(
                                f"Process '{proc.name}' has a loop with no exit: "
                                f"{' → '.join(cycle)}"
                            ),
                            process_id=proc.id,
                            evidence={"cycle": cycle},
                            check_tier=CheckTier.DETERMINISTIC,
                        )
                    )

    return diags
