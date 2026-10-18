"""Flow normaliser: turn per-section extractions into one connected, checkable process.

The structure pass reads one section at a time, so nothing links sections together, "otherwise"
branches are over-used, and standing rules (``no one may approve their own claim``) become
dead-end steps.  This pass repairs that *without fixing the document*: gaps the SOP really has
stay visible as findings, and everything the normaliser adds is flagged ``inferred`` so it shows
as dashed in the UI and is never confused with something the document said.

What it does, in order:
 1. fixes conditions (``always`` used as a normal branch, with/without pairs)
 2. extracts standing rules, deadlines and per-step limits from clause text
 3. derives a routing decision from sibling clauses ("below X" / "above X" / "submitted by Y")
 4. links the flow in document order, but never into an exception/trigger clause: if nothing says
    when "claims escalated by the Audit Committee" happens, that clause stays unreachable
 5. sets the entry step
"""

from __future__ import annotations

import re

import networkx as nx

from app.extract.shortcuts import derive_ordering_rules, derive_outcome_branches, derive_shortcuts
from app.extract.textrules import (
    has_reference,
    is_exception_text,
    is_no_self_action,
    is_outcome_text,
    is_separate_flow_heading,
    is_non_operational_heading,
    is_rule_heading,
    parse_applicability,
    parse_deadline,
    top_number,
)
from app.logic import norm_text
from app.schemas.ir_sop import (
    SLA,
    AlwaysCondition,
    CompareCondition,
    Constraint,
    ConstraintKind,
    LogicalCondition,
    Deadline,
    Decision,
    DecisionBranch,
    ExtractionWarning,
    Process,
    Step,
    StepKind,
    SymbolTable,
    TimeUnit,
    Transition,
    TypedValue,
    UnknownCondition,
    ValueType,
)

_OTHERWISE = re.compile(r"\b(?:otherwise|else|all\s+other|any\s+other|default|in\s+all\s+other)\b", re.I)
_WITH = re.compile(r"^\s*(?:with|having|has|have|includes?|including|provided|present)\s+(.+)$", re.I)
_WITHOUT = re.compile(r"^\s*(?:without|lacking|missing|no|not\s+having|absent)\s+(.+)$", re.I)
_POSITIVE_LABEL = re.compile(r"\b(?:with|yes|approved?|valid|pass(?:ed)?|complete|present|true|ok|accepted)\b", re.I)
_PROCESS_ANCHOR = re.compile(r"submission|submit|request|application|filing|start|raised|receipt\s+of\s+the", re.I)

_MAX_ITER = 40


def _text(step: Step) -> str:
    quotes = " ".join(s.quote for s in step.source_spans if s.quote)
    return " ".join(x for x in (quotes, step.action) if x)


def _slug(text: str) -> str:
    return norm_text(text)


# ---------------------------------------------------------------------------
# 1. conditions
# ---------------------------------------------------------------------------


def _label_condition(label: str) -> CompareCondition | None:
    """``With receipts`` / ``Without receipts`` → ``receipts_present = true/false``."""
    for pattern, value in ((_WITHOUT, False), (_WITH, True)):
        m = pattern.match(label or "")
        if m:
            noun = re.sub(r"\b(?:the|a|an|any|all|of|in|claim|claims)\b", " ", m.group(1), flags=re.I)
            var = _slug(noun)
            if var and len(var.split("_")) <= 3:
                return CompareCondition(
                    left=f"{var}_present",
                    op="eq",
                    right=TypedValue(value_type=ValueType.BOOL, bool_value=value),
                )
    return None


def fix_conditions(proc: Process, warnings: list[ExtractionWarning]) -> None:
    """``always`` is only right for "otherwise"; elsewhere derive a condition or mark unknown."""
    for dec in proc.decisions:
        non_always = [b for b in dec.branches if not isinstance(b.condition, AlwaysCondition)]
        for b in dec.branches:
            if not isinstance(b.condition, AlwaysCondition):
                continue
            if _OTHERWISE.search(b.label or "") and non_always:
                continue  # a genuine "otherwise" branch
            quote = " ".join(s.quote for s in b.source_spans)
            derived = parse_applicability(f"{b.label}. {quote}", []) or _label_condition(b.label)
            if derived is not None:
                b.condition = derived
            elif len(dec.branches) > 1:
                b.condition = UnknownCondition(raw_text=b.label or dec.question)
                warnings.append(
                    ExtractionWarning(
                        code="condition_unknown",
                        message=(
                            f"Decision {dec.id}: branch “{b.label}” had no explicit condition, so it "
                            "is treated as unknown rather than 'always'."
                        ),
                        decision_id=dec.id,
                    )
                )
    # two-branch yes/no decisions: labels like "With/Without receipts" define one boolean; otherwise,
    # two booleans on different variables would be treated as independent (false overlap/gap).
    for dec in proc.decisions:
        if len(dec.branches) != 2:
            continue
        b0, b1 = dec.branches
        c0, c1 = _label_condition(b0.label), _label_condition(b1.label)
        if c0 is not None and c1 is not None and c0.left == c1.left and c0.right.bool_value != c1.right.bool_value:
            b0.condition, b1.condition = c0, c1
            continue
        if (
            isinstance(b0.condition, CompareCondition)
            and isinstance(b1.condition, CompareCondition)
            and b0.condition.right.value_type == ValueType.BOOL
            and b1.condition.right.value_type == ValueType.BOOL
            and b0.condition.left != b1.condition.left
        ):
            b1.condition = LogicalCondition(logical_op="not", operands=[b0.condition])
            warnings.append(
                ExtractionWarning(
                    code="condition_assumed_complementary",
                    message=(
                        f"Decision {dec.id}: branches “{b0.label}” and “{b1.label}” were read as "
                        "opposite outcomes of one yes/no question."
                    ),
                    decision_id=dec.id,
                )
            )

    # any decision still having two "always" branches would claim every case matches both
    for dec in proc.decisions:
        always = [b for b in dec.branches if isinstance(b.condition, AlwaysCondition)]
        if len(always) > 1:
            for b in always[:-1] if any(_OTHERWISE.search(x.label or "") for x in always) else always:
                if not _OTHERWISE.search(b.label or ""):
                    b.condition = UnknownCondition(raw_text=b.label or dec.question)


# ---------------------------------------------------------------------------
# 2. rules, deadlines, limits
# ---------------------------------------------------------------------------


def extract_rules(proc: Process, warnings: list[ExtractionWarning]) -> None:
    n_con = len(proc.constraints)
    n_dl = len(proc.deadlines)
    for step in proc.steps:
        if step.kind == StepKind.TERMINAL:
            continue
        text = _text(step)

        if is_no_self_action(text):
            description = step.source_spans[0].quote if step.source_spans else step.action
            if any(c.kind == ConstraintKind.NO_SELF_ACTION and c.description == description for c in proc.constraints):
                step.off_flow = True
                continue
            n_con += 1
            proc.constraints.append(
                Constraint(
                    id=f"c{n_con:02d}",
                    kind=ConstraintKind.NO_SELF_ACTION,
                    description=description,
                    source_spans=step.source_spans,
                )
            )
            step.off_flow = True
            continue

        if step.off_flow:
            continue
        dl = parse_deadline(text)
        has_actor = bool(step.actor_role_id or (step.actor_raw or "").strip())
        if dl is None and step.sla and not step.sla.vague:
            anchor = step.sla.from_event or ""
            if not has_actor and _PROCESS_ANCHOR.search(f"{anchor} {text}"):
                dl = (step.sla.max_duration, step.sla.unit, anchor)
        if dl is None:
            continue
        amount, unit, anchor = dl
        if not has_actor and _PROCESS_ANCHOR.search(f"{anchor or ''} {text}"):
            if any(x.max_duration == amount and x.unit == unit for x in proc.deadlines):
                step.off_flow = True
                continue
            n_dl += 1
            proc.deadlines.append(
                Deadline(
                    id=f"dl{n_dl:02d}",
                    description=(step.source_spans[0].quote if step.source_spans else step.action),
                    max_duration=amount,
                    unit=unit if isinstance(unit, TimeUnit) else TimeUnit(unit),
                    source_spans=step.source_spans,
                )
            )
            step.off_flow = True
        elif step.sla is None:
            step.sla = SLA(max_duration=amount, unit=unit if isinstance(unit, TimeUnit) else TimeUnit(unit))


def apply_section_roles(
    proc: Process, headings: dict[str, str], warnings: list[ExtractionWarning]
) -> None:
    """Drop purpose/scope/definition steps; mark steps under 'Controls'-style headings as rules."""
    nonop = sorted(n for n, t in headings.items() if is_non_operational_heading(t))
    rule_secs = {n for n, t in headings.items() if is_rule_heading(t) and n not in nonop}
    proc.non_operational_numbers = nonop
    dropped = {s.id for s in proc.steps if top_number(s.number) in nonop}
    if dropped:
        proc.steps = [s for s in proc.steps if s.id not in dropped]
        proc.transitions = [
            t for t in proc.transitions if t.from_id not in dropped and t.to_id not in dropped
        ]
        for d in proc.decisions:
            if d.preceding_step_id in dropped:
                d.preceding_step_id = None
            d.branches = [b for b in d.branches if b.next_step_id not in dropped]
        warnings.append(
            ExtractionWarning(
                code="non_operational_dropped",
                message=(
                    f"Ignored {len(dropped)} step(s) from purpose/scope/definition sections "
                    f"({', '.join(sorted(dropped))}): they describe the document, not a procedure."
                ),
            )
        )
    for s in proc.steps:
        if top_number(s.number) in rule_secs and s.kind != StepKind.TERMINAL:
            s.off_flow = True


def strip_off_flow_edges(proc: Process) -> None:
    """Standing rules are not flow nodes: remove any edges the LLM drew into or out of them."""
    off = {s.id for s in proc.steps if s.off_flow}
    if not off:
        return
    proc.transitions = [t for t in proc.transitions if t.from_id not in off and t.to_id not in off]
    broken: set[str] = set()
    for d in proc.decisions:
        if d.preceding_step_id in off:
            d.preceding_step_id = None
        kept = [b for b in d.branches if b.next_step_id not in off]
        if len(kept) < len(d.branches) and len(kept) < 2:
            broken.add(d.id)  # it routed to a rule/exception clause that is no longer a step
        d.branches = kept
    if broken:
        proc.decisions = [d for d in proc.decisions if d.id not in broken]
        proc.transitions = [t for t in proc.transitions if t.to_id not in broken and t.from_id not in broken]
    if proc.entry_step_id in off:
        proc.entry_step_id = None
    # a decision whose branches all pointed at rules is meaningless
    empty = {d.id for d in proc.decisions if not d.branches}
    if empty:
        proc.decisions = [d for d in proc.decisions if d.id not in empty]
        proc.transitions = [t for t in proc.transitions if t.to_id not in empty and t.from_id not in empty]


# ---------------------------------------------------------------------------
# 3. routing decisions from sibling clauses
# ---------------------------------------------------------------------------


def _incoming(proc: Process) -> dict[str, int]:
    count: dict[str, int] = {}
    for t in proc.transitions:
        count[t.to_id] = count.get(t.to_id, 0) + 1
    for d in proc.decisions:
        for b in d.branches:
            count[b.next_step_id] = count.get(b.next_step_id, 0) + 1
    return count


def derive_routing(
    proc: Process, symbols: SymbolTable, ast_headings: dict[str, str], warnings: list[ExtractionWarning]
) -> dict[str, list[str]]:
    """Group consecutive sibling clauses with parseable applicability conditions into a decision.

    Returns {decision_id: [member step ids]}.
    """
    groups: dict[str, list[str]] = {}
    run: list[tuple[Step, object]] = []
    runs: list[list[tuple[Step, object]]] = []

    def flush() -> None:
        if len(run) >= 2:
            runs.append(list(run))
        run.clear()

    prev_top: str | None = None
    for step in proc.steps:
        top = top_number(step.number)
        cond = None
        if not step.off_flow and step.kind != StepKind.TERMINAL:
            cond = parse_applicability(_text(step), symbols.roles)
        if cond is None or (prev_top is not None and top != prev_top):
            flush()
        if cond is not None:
            run.append((step, cond))
            prev_top = top
        else:
            prev_top = top
    flush()

    for members in runs:
        top = top_number(members[0][0].number) or "x"
        dec_id = f"d_route_{top}"
        if proc.decision(dec_id):
            continue
        member_ids = {st.id for st, _ in members}
        # A model-drawn decision over the same sibling clauses is replaced by the deterministic one.
        superseded = [
            d for d in proc.decisions
            if not d.inferred and len({b.next_step_id for b in d.branches} & member_ids) >= 1
            and all(b.next_step_id in member_ids or b.next_step_id == "END" or proc.decision(b.next_step_id)
                    for b in d.branches)
        ]
        entry_pre = None  # the model's idea of the preceding step is unreliable; chaining attaches it
        old_ids = {d.id for d in superseded}
        proc.decisions = [d for d in proc.decisions if d.id not in old_ids]
        heading = ast_headings.get(top, "").strip()
        question = f"{heading}: which route applies?" if heading else "Which route applies?"
        branches = [
            DecisionBranch(
                label=re.sub(r"\s+", " ", step.action)[:80],
                condition=cond,  # type: ignore[arg-type]
                next_step_id=step.id,
                source_spans=step.source_spans,
            )
            for step, cond in members
        ]
        proc.decisions.append(
            Decision(
                id=dec_id,
                question=question,
                preceding_step_id=entry_pre,
                branches=branches,
                source_spans=[sp for step, _ in members for sp in step.source_spans][:1],
                extraction_confidence=0.6,
                inferred=True,
            )
        )
        for t in proc.transitions:
            if t.to_id in old_ids:
                t.to_id = dec_id
        for other in proc.decisions:
            for b in other.branches:
                if b.next_step_id in old_ids:
                    b.next_step_id = dec_id
        groups[dec_id] = [s.id for s, _ in members]
        warnings.append(
            ExtractionWarning(
                code="routing_inferred",
                message=(
                    f"Clauses {', '.join(s.number or s.id for s, _ in members)} apply to different "
                    f"cases, so they were grouped into the routing decision '{dec_id}'."
                ),
                decision_id=dec_id,
            )
        )
    return groups


def routing_groups(proc: Process) -> dict[str, list[str]]:
    """Decisions that fan out to >= 2 steps which are entered only through that decision."""
    incoming = _incoming(proc)
    groups: dict[str, list[str]] = {}
    for d in proc.decisions:
        targets = [b.next_step_id for b in d.branches if proc.step(b.next_step_id)]
        targets = list(dict.fromkeys(targets))
        if len(targets) >= 2 and all(incoming.get(t, 0) == 1 for t in targets):
            groups[d.id] = targets
    return groups


def redirect_into_routing(proc: Process) -> None:
    """Edges that jump straight to one routing alternative must enter via the routing decision."""
    incoming = _incoming(proc)
    for d in proc.decisions:
        if not d.id.startswith("d_route_"):
            continue  # only derived routing hubs; other decisions have legitimate direct entries
        targets = {b.next_step_id for b in d.branches if proc.step(b.next_step_id)}
        if len(targets) < 2:
            continue
        # the decision is the routing hub if its alternatives share a clause section
        tops = {top_number(proc.step(t).number) for t in targets if proc.step(t)}
        if len(tops) != 1:
            continue
        for t in proc.transitions:
            if t.to_id in targets and t.from_id not in targets and t.from_id != d.id:
                t.to_id = d.id
        for other in proc.decisions:
            if other.id == d.id:
                continue
            for b in other.branches:
                if b.next_step_id in targets:
                    b.next_step_id = d.id
    _ = incoming


def fix_decision_cycles(proc: Process) -> None:
    """A decision cannot follow a step that its own branches lead into (the model got the order wrong)."""
    for d in proc.decisions:
        pre = d.preceding_step_id
        if not pre:
            continue
        g = _graph(proc)
        if g.has_edge(pre, d.id):
            g.remove_edge(pre, d.id)
        real = [b for b in d.branches if b.next_step_id in g]
        # a rework branch may legitimately loop back; it is misplaced only if EVERY branch does
        # (a branch that ends the process, or leads elsewhere, proves the order is right)
        if real and pre in g and all(nx.has_path(g, b.next_step_id, pre) for b in real):
            d.preceding_step_id = None


_STOP = {"the", "a", "an", "of", "to", "and", "for", "again", "every", "each", "all", "is", "are", "be", "then"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if w not in _STOP and len(w) > 2}


def link_back_loops(proc: Process, warnings: list[ExtractionWarning]) -> None:
    """"...checked again": a dead-end repeat step loops back to the earlier step it repeats."""
    g = _graph(proc)
    for i, step in enumerate(proc.steps):
        succ = set(g.successors(step.id))
        if step.off_flow or step.kind == StepKind.TERMINAL or (succ and succ != {"END"}):
            continue
        if not re.search(r"\b(?:again|re-?check|re-?submit|re-?review|repeat|re-?verify)", _text(step), re.I):
            continue
        mine = _words(step.action)
        best, score = None, 1
        for prev in proc.steps[:i]:
            if prev.off_flow or prev.id == step.id:
                continue
            overlap = len(mine & _words(prev.action))
            if overlap > score or (overlap == score and best is not None and overlap >= 2):
                best, score = prev, overlap
        if best is not None:
            proc.transitions = [
                t for t in proc.transitions if not (t.from_id == step.id and t.to_id == "END")
            ]
            proc.transitions.append(
                Transition(from_id=step.id, to_id=best.id, label="repeat (inferred)", inferred=True)
            )
            warnings.append(
                ExtractionWarning(
                    code="flow_inferred",
                    message=f"{step.id} repeats an earlier action; looped back to {best.id}.",
                    step_id=step.id,
                )
            )


# ---------------------------------------------------------------------------
# 4. chaining
# ---------------------------------------------------------------------------


def _graph(proc: Process) -> nx.DiGraph:
    g: nx.DiGraph = nx.DiGraph()
    for s in proc.steps:
        g.add_node(s.id)
    for d in proc.decisions:
        g.add_node(d.id)
    g.add_node("END")
    for t in proc.transitions:
        g.add_edge(t.from_id, t.to_id)
    for d in proc.decisions:
        if d.preceding_step_id:
            g.add_edge(d.preceding_step_id, d.id)
        for b in d.branches:
            g.add_edge(d.id, b.next_step_id)
    return g


def _positive(label: str) -> bool:
    return bool(_POSITIVE_LABEL.search(label or ""))


def chain_flow(
    proc: Process,
    groups: dict[str, list[str]],
    warnings: list[ExtractionWarning],
    headings: dict[str, str] | None = None,
) -> None:
    member_of = {sid: did for did, sids in groups.items() for sid in sids}
    order: list[str] = []  # flow units in document order
    for s in proc.steps:
        if s.off_flow:
            continue
        unit = member_of.get(s.id, s.id)
        if unit not in order:
            order.append(unit)
    for d in proc.decisions:  # decisions the LLM produced sit at their preceding step's position
        if d.id not in order and d.preceding_step_id in order:
            pass  # already reachable through the preceding step; not a chain unit
    if not order:
        return
    index = {u: i for i, u in enumerate(order)}

    incoming = _incoming(proc)

    headings = headings or {}

    def is_exception(unit: str) -> bool:
        st = proc.step(unit)
        if not st or incoming.get(unit, 0) != 0:
            return False
        if is_exception_text(_text(st)):
            return True
        # a periodic / exceptional section (audit, recertification, retention...) is its own flow
        return is_separate_flow_heading(headings.get(top_number(st.number) or "", ""))

    entry = proc.entry_step_id or next((u for u in order if not is_exception(u)), order[0])
    proc.entry_step_id = entry

    for _ in range(_MAX_ITER):
        g = _graph(proc)
        reach = {entry} | nx.descendants(g, entry)
        target = next((u for u in order if u not in reach and not is_exception(u)), None)
        if target is None:
            break
        tpos = index[target]

        def owner_pos(node: str) -> int:
            if node in index:
                return index[node]
            dec = proc.decision(node)
            if dec and dec.preceding_step_id in index:
                return index[dec.preceding_step_id]
            st = proc.step(node)
            return index.get(member_of.get(node, node), -1) if st else -1

        dead_ends = [
            s.id
            for s in proc.steps
            if s.id in reach and not s.off_flow and s.kind != StepKind.TERMINAL and g.out_degree(s.id) == 0
            and not has_reference(_text(s))
        ]
        dead_ends = [d for d in dead_ends if owner_pos(d) < tpos]  # never link backwards
        if dead_ends:
            src = max(dead_ends, key=owner_pos)
            proc.transitions.append(
                Transition(from_id=src, to_id=target, label="next clause (inferred)", inferred=True)
            )
            warnings.append(
                ExtractionWarning(
                    code="flow_inferred",
                    message=f"No outgoing flow from {src}; linked to the next clause {target} in document order.",
                    step_id=src,
                )
            )
            continue

        end_edges: list[tuple[int, str, object]] = []
        for t in proc.transitions:
            if t.to_id == "END" and t.from_id in reach:
                end_edges.append((owner_pos(t.from_id), "t", t))
        for d in proc.decisions:
            if d.id in reach:
                for b in d.branches:
                    if b.next_step_id == "END":
                        end_edges.append((owner_pos(d.id), "b", (d, b)))
        end_edges = [e for e in end_edges if e[0] < tpos] or end_edges
        if not end_edges:
            break
        best_pos = max(e[0] for e in end_edges)
        cands = [e for e in end_edges if e[0] == best_pos]
        pick = next((e for e in cands if e[1] == "b" and _positive(e[2][1].label)), cands[-1])  # type: ignore[index]
        if pick[1] == "t":
            pick[2].to_id = target  # type: ignore[union-attr]
            pick[2].inferred = True  # type: ignore[union-attr]
            src = pick[2].from_id  # type: ignore[union-attr]
        else:
            d, b = pick[2]  # type: ignore[misc]
            b.next_step_id = target
            src = d.id
        warnings.append(
            ExtractionWarning(
                code="flow_inferred",
                message=f"{src} ended the process before later clauses; continued into {target}.",
                decision_id=src if proc.decision(src) else None,
                step_id=src if proc.step(src) else None,
            )
        )
    # the last reachable dead end closes the process
    g = _graph(proc)
    reach = {entry} | nx.descendants(g, entry)
    ends = [
        s.id
        for s in proc.steps
        if s.id in reach and not s.off_flow and s.kind != StepKind.TERMINAL and g.out_degree(s.id) == 0
        and not has_reference(_text(s))
    ]
    if ends:
        # the last clause of the document closes the process, even if another branch already ends
        last = max(ends, key=lambda sid: index.get(member_of.get(sid, sid), -1))
        proc.transitions.append(Transition(from_id=last, to_id="END", label="end (inferred)", inferred=True))


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def normalize_structure(
    proc: Process,
    symbols: SymbolTable,
    ast_headings: dict[str, str] | None = None,
    clauses: dict[str, str] | None = None,
) -> list[ExtractionWarning]:
    """Phase A (idempotent): section roles, conditions, rules, routing decisions."""
    warnings: list[ExtractionWarning] = []
    proc.section_numbers = sorted((ast_headings or {}).keys(), key=lambda n: int(n))
    apply_section_roles(proc, ast_headings or {}, warnings)
    fix_conditions(proc, warnings)
    extract_rules(proc, warnings)
    derive_ordering_rules(proc, warnings, clauses or {})
    derive_shortcuts(proc, warnings, clauses or {})
    strip_off_flow_edges(proc)
    derive_routing(proc, symbols, ast_headings or {}, warnings)
    derive_outcome_branches(proc, warnings, clauses or {})
    fix_conditions(proc, warnings)
    redirect_into_routing(proc)
    fix_decision_cycles(proc)
    return warnings


def converge_routing(proc: Process, warnings: list[ExtractionWarning]) -> None:
    """Alternatives of one routing decision rejoin the same next step.

    If some alternatives have an outgoing flow and the others have none, the model drew only part
    of the picture; the missing ones inherit the common successor (flagged inferred).
    """
    for dec_id, members in routing_groups(proc).items():
        succ = {t.to_id for t in proc.transitions if t.from_id in members}
        succ |= {d.id for d in proc.decisions if d.preceding_step_id in members}
        if len(succ) > 1:
            continue
        if succ:
            target = next(iter(succ))
        else:
            # none of the alternatives has a next step: they all rejoin the clause that follows them
            last = max(i for i, s in enumerate(proc.steps) if s.id in members)
            after = next(
                (
                    s.id
                    for s in proc.steps[last + 1 :]
                    if not s.off_flow and s.id not in members and not is_exception_text(_text(s))
                ),
                None,
            )
            target = after or "END"
        for m in members:
            member = proc.step(m)
            if member is not None and has_reference(_text(member)):
                continue  # hands off to another section: leave it open, it is a finding
            has_out = any(t.from_id == m for t in proc.transitions) or any(
                d.preceding_step_id == m for d in proc.decisions
            )
            if not has_out:
                proc.transitions.append(
                    Transition(from_id=m, to_id=target, label="rejoins (inferred)", inferred=True)
                )
                warnings.append(
                    ExtractionWarning(
                        code="flow_inferred",
                        message=f"{m} is an alternative of {dec_id}; it continues to {target} like its siblings.",
                        step_id=m,
                    )
                )


def rejoin_dead_ends(proc: Process, warnings: list[ExtractionWarning]) -> None:
    """A dead-end step whose every predecessor also reaches the same later step is a joiner that
    the model drew around: it rejoins that step (flagged inferred)."""
    g = _graph(proc)
    for s in proc.steps:
        if s.off_flow or s.kind == StepKind.TERMINAL or g.out_degree(s.id) > 0 or has_reference(_text(s)):
            continue
        preds = [p for p in g.predecessors(s.id) if proc.step(p)]
        if len(preds) < 2:
            continue
        common = None
        for p in preds:
            others = {n for n in g.successors(p) if n not in (s.id, "END") and proc.step(n)}
            common = others if common is None else common & others
        if common:
            order = {st.id: i for i, st in enumerate(proc.steps)}
            target = min(common, key=lambda n: order.get(n, 10**6))
            proc.transitions.append(Transition(from_id=s.id, to_id=target, label="rejoins (inferred)", inferred=True))
            warnings.append(
                ExtractionWarning(
                    code="flow_inferred",
                    message=f"{s.id} had no next step although its predecessors continue to {target}; it rejoins there.",
                    step_id=s.id,
                )
            )


def close_outcomes(proc: Process, warnings: list[ExtractionWarning]) -> None:
    """A branch target with no next step that names an outcome (reject, approve, open the account)
    ends the process: link it to END (flagged inferred)."""
    groups = {m for members in routing_groups(proc).values() for m in members}
    targets = {b.next_step_id for d in proc.decisions for b in d.branches}
    g = _graph(proc)
    for s in proc.steps:
        if (
            s.id in targets
            and s.id not in groups
            and not s.off_flow
            and g.out_degree(s.id) == 0
            and not has_reference(_text(s))
            and is_outcome_text(s.action)
        ):
            proc.transitions.append(Transition(from_id=s.id, to_id="END", label="outcome (inferred)", inferred=True))
            warnings.append(
                ExtractionWarning(
                    code="flow_inferred",
                    message=f"{s.id} names an outcome and has no next step; the process ends there.",
                    step_id=s.id,
                )
            )


def finalize_flow(proc: Process, headings: dict[str, str] | None = None) -> list[ExtractionWarning]:
    """Phase B: link repeat steps, chain the flow in document order, set the entry."""
    warnings: list[ExtractionWarning] = []
    strip_off_flow_edges(proc)
    redirect_into_routing(proc)
    fix_decision_cycles(proc)
    converge_routing(proc, warnings)
    link_back_loops(proc, warnings)
    rejoin_dead_ends(proc, warnings)
    close_outcomes(proc, warnings)
    chain_flow(proc, routing_groups(proc), warnings, headings)
    return warnings


def normalize_flow(
    proc: Process,
    symbols: SymbolTable,
    ast_headings: dict[str, str] | None = None,
    clauses: dict[str, str] | None = None,
) -> list[ExtractionWarning]:
    """Both phases without the LLM flow pass in between (used by tests and offline repair)."""
    return normalize_structure(proc, symbols, ast_headings, clauses) + finalize_flow(proc, ast_headings)
