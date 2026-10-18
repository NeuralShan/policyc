"""Rule checks that need the explicit constraints/deadlines of the IR.

TM002  end-to-end deadline cannot be met: step time limits along a path add up to more than allowed
RS004  segregation of duties: the requester can be routed to a step only they could perform, while
       the document forbids acting on one's own request
ST008  mandatory step can be bypassed: a ``must_precede`` rule is violated by some path

All three are deterministic graph/arithmetic checks, each with a witness path.
"""

from __future__ import annotations

import networkx as nx
import z3

from app.analyze.registry import register
from app.extract.textrules import REFERENCE
from app.logic import ConstraintBuilder, display_value, norm_text
from app.schemas.finding import CheckTier, Diagnostic, Severity
from app.schemas.graph import LinkedIR
from app.schemas.ir_sop import (
    ConstraintKind,
    Process,
    SopIR,
    Step,
    StepKind,
    TimeUnit,
)

# Conservative conversion to hours: a working day is counted as 24h (the SOP gives no calendar), so
# the check reports a lower bound on elapsed time rather than inventing an 8-hour day.
_HOURS = {
    TimeUnit.HOURS: 1.0,
    TimeUnit.DAYS: 24.0,
    TimeUnit.CALENDAR_DAYS: 24.0,
    TimeUnit.BUSINESS_DAYS: 24.0,
    TimeUnit.WEEKS: 168.0,
}

_REQUESTER_HINTS = ("requester", "submitter", "claimant", "applicant", "initiator", "employee")
_MAX_PATHS = 3000


def _build_flow_graph(proc: Process) -> nx.DiGraph:
    # Imported lazily so this module registers its checks before the structural ones do.
    from app.analyze.checks.structural import _build_flow_graph as build

    return build(proc)


def _hours(step: Step) -> float:
    if step.sla is None or step.sla.vague:
        return 0.0
    return step.sla.max_duration * _HOURS.get(step.sla.unit, 1.0)


def _label(proc: Process, node_id: str) -> str:
    st = proc.step(node_id)
    if st:
        return f"{st.number + ' ' if st.number else ''}{st.action}"
    dec = proc.decision(node_id)
    return dec.question if dec else node_id


# ---------------------------------------------------------------------------
# TM002 — deadline infeasible
# ---------------------------------------------------------------------------


@register("TM", "Deadline feasibility")
def deadline_checks(ir: SopIR, _linked: LinkedIR | None) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for proc in ir.processes:
        limits: list[tuple[str, float, str | None, str | None, list]] = []
        for dl in proc.deadlines:
            limits.append(
                (
                    dl.description,
                    dl.max_duration * _HOURS.get(dl.unit, 1.0),
                    dl.from_step_id,
                    dl.to_step_id,
                    dl.source_spans,
                )
            )
        if proc.overall_sla and not proc.overall_sla.vague:
            sla = proc.overall_sla
            limits.append(
                (
                    sla.vague_text or "overall SLA",
                    sla.max_duration * _HOURS.get(sla.unit, 1.0),
                    None,
                    None,
                    sla.source_spans,
                )
            )
        if not limits:
            continue

        g = _build_flow_graph(proc)
        entry = proc.entry()
        terminals = {s.id for s in proc.steps if s.kind.value == "terminal"} | {"END"}
        for desc, limit_h, src, dst, spans in limits:
            src = src or entry
            if not src or not g.has_node(src):
                continue
            targets = {dst} if dst and g.has_node(dst) else {t for t in terminals if g.has_node(t)}
            worst: tuple[float, list[str]] | None = None
            count = 0
            for tgt in targets:
                if tgt == src:
                    continue
                for path in nx.all_simple_paths(g, src, tgt, cutoff=80):
                    count += 1
                    total = sum(_hours(p) for n in path if (p := proc.step(n)) is not None)
                    if worst is None or total > worst[0]:
                        worst = (total, path)
                    if count >= _MAX_PATHS:
                        break
            if worst is None or worst[0] <= limit_h:
                continue
            total, path = worst
            parts = [
                f"{_label(proc, n)} {_hours(st):g}h"
                for n in path
                if (st := proc.step(n)) is not None and _hours(st) > 0
            ]
            diags.append(
                Diagnostic(
                    code="TM002",
                    severity=Severity.WARNING,
                    message=(
                        f"Deadline infeasible — “{desc}” allows {limit_h:g}h, but a path through "
                        f"the process needs at least {total:g}h ({' + '.join(parts)})"
                    ),
                    process_id=proc.id,
                    step_id=path[-1] if proc.step(path[-1]) else None,
                    source_spans=spans,
                    evidence={
                        "allowed_hours": limit_h,
                        "path_hours": total,
                        "path": path,
                        "breakdown": parts,
                        "note": "working days counted as 24h (lower bound)",
                    },
                    check_tier=CheckTier.DETERMINISTIC,
                )
            )
    return diags


# ---------------------------------------------------------------------------
# RS004 — segregation of duties / self-approval deadlock
# ---------------------------------------------------------------------------


def _requester_vars(builder: ConstraintBuilder) -> list[str]:
    return [
        v
        for v, k in builder.kinds.items()
        if k == "enum" and any(h in v.lower() for h in _REQUESTER_HINTS)
    ]


def _approver_steps(proc: Process, start: str) -> list[Step]:
    """Steps reachable from ``start`` without passing another decision, in flow order."""
    out: list[Step] = []
    seen: set[str] = set()
    queue = [start]
    decision_ids = {d.id for d in proc.decisions}
    while queue:
        node = queue.pop(0)
        if node in seen or node == "END":
            continue
        seen.add(node)
        st = proc.step(node)
        if st is None:
            continue  # a decision: its own branches are checked separately
        out.append(st)
        queue.extend(t.to_id for t in proc.transitions if t.from_id == node and t.to_id not in decision_ids)
    return out


def _is_approval(step: Step) -> bool:
    text = " ".join([step.action] + [sp.quote for sp in step.source_spans]).lower()
    return step.kind == StepKind.APPROVAL or "approv" in text


@register("RS", "Segregation of duties")
def segregation_checks(ir: SopIR, _linked: LinkedIR | None) -> list[Diagnostic]:
    """RS004: can the requester be routed to an approval only they could perform?

    For every branch of every decision, ask the solver whether the branch condition and
    ``requester == <role of the approving step>`` can hold together while the document forbids
    acting on one's own request.
    """
    diags: list[Diagnostic] = []
    for proc in ir.processes:
        rules = [c for c in proc.constraints if c.kind == ConstraintKind.NO_SELF_ACTION]
        if not rules:
            continue
        builder = ConstraintBuilder()
        for dec in proc.decisions:
            for b in dec.branches:
                builder.scan(b.condition)
        req_vars = _requester_vars(builder)
        if not req_vars:
            continue
        rule = rules[0]
        reported: set[str] = set()
        for dec in proc.decisions:
            for branch in dec.branches:
                for st in _approver_steps(proc, branch.next_step_id):
                    if not (st.actor_role_id and _is_approval(st)) or st.id in reported:
                        continue
                    lit = norm_text(st.actor_role_id)
                    cond = builder.formula(branch.condition)
                    if cond is None:
                        continue
                    for var in req_vars:
                        # only roles the document itself treats as possible requesters
                        if lit not in builder.enum_values.get(var, []):
                            continue
                        solver = z3.Solver()
                        solver.add(*builder.domain(), cond)
                        solver.add(builder._var(var) == builder.enum_values[var].index(lit))
                        if solver.check() != z3.sat:
                            continue
                        facts = builder.facts(solver.model())
                        role = next((r for r in ir.symbols.roles if r.id == st.actor_role_id), None)
                        who = role.name if role else (st.actor_raw or st.actor_role_id)
                        rule_txt = rule.description or "the document forbids acting on one's own request"
                        reported.add(st.id)
                        diags.append(
                            Diagnostic(
                                code="RS004",
                                severity=Severity.ERROR,
                                message=(
                                    f"No eligible approver: when {', '.join(f'{k} = {display_value(v)}' for k, v in sorted(facts.items()))} "
                                    f"the process routes to “{st.action}” ({st.number or st.id}), which "
                                    f"only the {who} performs — but {rule_txt}. "
                                    f"The {who}'s own request can never be completed."
                                ),
                                process_id=proc.id,
                                step_id=st.id,
                                decision_id=dec.id,
                                source_spans=st.source_spans or rule.source_spans,
                                evidence={
                                    "counterexample": facts,
                                    "branch": branch.label,
                                    "stuck_step": st.id,
                                    "rule": rule.description,
                                    "rule_quote": [sp.quote for sp in rule.source_spans][:1],
                                },
                                check_tier=CheckTier.DETERMINISTIC,
                            )
                        )
                        break
    return diags


# ---------------------------------------------------------------------------
# ST008 — mandatory step bypassed (must_precede)
# ---------------------------------------------------------------------------


@register("ST", "Mandatory step ordering")
def ordering_checks(ir: SopIR, _linked: LinkedIR | None) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for proc in ir.processes:
        entry = proc.entry()
        if not entry:
            continue
        g = _build_flow_graph(proc)
        for c in proc.constraints:
            if c.kind != ConstraintKind.MUST_PRECEDE or not (c.before_step_id and c.target_step_id):
                continue
            if not (g.has_node(c.before_step_id) and g.has_node(c.target_step_id)):
                continue
            if c.before_step_id == entry:
                continue
            from app.extract.shortcuts import equivalent_steps

            h = g.copy()
            for equiv in equivalent_steps(proc, c.before_step_id):
                if equiv != c.target_step_id and h.has_node(equiv):
                    h.remove_node(equiv)  # a step doing the same job on another path also satisfies it
            if entry == c.target_step_id:
                path = [entry]
            elif h.has_node(entry) and nx.has_path(h, entry, c.target_step_id):
                path = nx.shortest_path(h, entry, c.target_step_id)
            else:
                continue
            before, target = proc.step(c.before_step_id), proc.step(c.target_step_id)
            diags.append(
                Diagnostic(
                    code="ST008",
                    severity=Severity.ERROR,
                    message=(
                        f"Mandatory step bypassed — “{target.action if target else c.target_step_id}” "
                        f"can be reached without “{before.action if before else c.before_step_id}”: "
                        + " → ".join(_label(proc, n) for n in path)
                    ),
                    process_id=proc.id,
                    step_id=c.target_step_id,
                    source_spans=(target.source_spans if target else []) or c.source_spans,
                    evidence={
                        "path": path,
                        "rule": c.description,
                        "must_precede": [c.before_step_id, c.target_step_id],
                    },
                    check_tier=CheckTier.DETERMINISTIC,
                )
            )
    return diags


# ---------------------------------------------------------------------------
# XD001 — broken internal cross-reference
# ---------------------------------------------------------------------------


@register("XD", "Cross-reference checks")
def reference_checks(ir: SopIR, _linked: LinkedIR | None) -> list[Diagnostic]:
    """A clause that says "see Section 9" when the document has no section 9."""
    diags: list[Diagnostic] = []
    for proc in ir.processes:
        if not proc.section_numbers:
            continue
        known = set(proc.section_numbers) | {s.number for s in proc.steps if s.number}
        reported: set[tuple[str | None, str]] = set()  # one report per clause and reference
        for step in proc.steps:
            text = " ".join([sp.quote for sp in step.source_spans] + [step.action])
            seen: set[str] = set()
            for m in REFERENCE.finditer(text):
                ref = m.group("num")
                if ref in seen or (step.number, ref) in reported:
                    continue
                seen.add(ref)
                reported.add((step.number, ref))
                exists = ref in known or any(k == ref or k.startswith(ref + ".") for k in known)
                if exists:
                    continue
                diags.append(
                    Diagnostic(
                        code="XD001",
                        severity=Severity.WARNING,
                        message=(
                            f"Broken cross-reference: clause {step.number or step.id} refers to "
                            f"“{m.group(0)}”, but the document has no section {ref}"
                        ),
                        process_id=proc.id,
                        step_id=step.id,
                        source_spans=step.source_spans,
                        evidence={"reference": m.group(0), "missing": ref},
                        check_tier=CheckTier.DETERMINISTIC,
                    )
                )
    return diags
