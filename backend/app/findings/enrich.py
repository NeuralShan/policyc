"""Finding enrichment: witness, clause quote, suggested fix, fingerprint, merged proofs.

The aggregator clusters raw signals; this pass makes each finding self-explanatory and comparable
across runs.  Runtime test failures that reproduce a static finding (a conflicting scenario proves
an overlapping rule, an undetermined scenario proves a missing branch) are folded into that
finding as proof instead of being listed twice.
"""

from __future__ import annotations

import hashlib
import re

from app.logic import display_value
from app.schemas.findings import AggregatedFinding, FindingsReport, RiskScore
from app.schemas.ir_sop import Decision, Process, SopIR, Step
from app.schemas.taxonomy import TAXONOMY

# runtime code -> static code it proves, matched on the same decision / step
_DECISION_LEVEL = {"ST004", "ST005", "EX001", "EX002"}
_PROVES = {"EX001": "ST004", "EX002": "ST005", "RS006": "RS004"}
_SAME_CODE_PROOF = {"ST008"}  # a runtime ST008 failure proves the static ST008 on the same step


def _find_process(ir: SopIR, process_id: str | None) -> Process | None:
    if process_id:
        proc = next((p for p in ir.processes if p.id == process_id), None)
        if proc:
            return proc
    return ir.processes[0] if ir.processes else None


def _node_numbers(proc: Process, node_id: str | None) -> list[str]:
    if not node_id:
        return []
    st = proc.step(node_id)
    if st:
        return [st.number] if st.number else [st.id]
    dec = proc.decision(node_id)
    if dec:
        nums = []
        for b in dec.branches:
            tgt = proc.step(b.next_step_id)
            if tgt:
                nums.append(tgt.number or tgt.id)
        return sorted(set(nums)) or [dec.id]
    return [node_id]


def _involved(proc: Process, f: AggregatedFinding) -> list[str]:
    ids: list[str] = []
    if f.step_id:
        ids.append(f.step_id)
    if f.decision_id:
        ids.append(f.decision_id)
        dec = proc.decision(f.decision_id)
        if dec:
            ids.extend(b.next_step_id for b in dec.branches if proc.step(b.next_step_id))
    for ev in f.evidence:
        for key in ("path", "must_precede"):
            val = ev.data.get(key)
            if isinstance(val, list):
                ids.extend(str(x) for x in val)
        if ev.data.get("stuck_step"):
            ids.append(str(ev.data["stuck_step"]))
    return [i for i in dict.fromkeys(ids)]


def _witness(f: AggregatedFinding) -> dict:
    for ev in f.evidence:
        if ev.data.get("counterexample"):
            return {"kind": "counterexample", "facts": ev.data["counterexample"]}
    for ev in f.evidence:
        if ev.data.get("facts"):
            return {"kind": "scenario", "facts": ev.data["facts"], "test_id": ev.test_id,
                    "outcome": ev.data.get("outcome")}
    for ev in f.evidence:
        if ev.data.get("path"):
            return {"kind": "path", "path": ev.data["path"]}
    for ev in f.evidence:
        if ev.data.get("breakdown"):
            return {"kind": "arithmetic", "allowed_hours": ev.data.get("allowed_hours"),
                    "path_hours": ev.data.get("path_hours"), "breakdown": ev.data["breakdown"]}
    return {}


def _facts_text(facts: dict) -> str:
    return ", ".join(f"{k} = {display_value(v)}" for k, v in sorted(facts.items()))


def _fix(f: AggregatedFinding, proc: Process | None) -> str | None:
    facts = f.witness.get("facts") if f.witness.get("kind") in ("counterexample", "scenario") else None
    when = f" when {_facts_text(facts)}" if facts else ""
    dec = proc.decision(f.decision_id) if proc and f.decision_id else None
    step = proc.step(f.step_id) if proc and f.step_id else None
    match f.code:
        case "ST004" | "EX001":
            return (
                f"Add a rule (or an “otherwise” rule) that says what happens{when}. "
                "Make the thresholds meet exactly, e.g. “up to and including” on one side."
            )
        case "ST005" | "EX002":
            return (
                f"State which rule takes precedence{when}, or tighten the conditions so only one "
                "route applies to each case."
            )
        case "ST001":
            return "Add the clause that says when this step happens, or remove the step if it is obsolete."
        case "ST002":
            return "Say what happens after this step: the next step, a decision, or the end of the process."
        case "ST003":
            return "Add an exit condition or a retry limit so the loop cannot run forever."
        case "ST008":
            return "Require the mandatory step on every path, including the exception route."
        case "RS001" | "RS002":
            return "Name the role that performs this step (a specific job title, not “staff” or “the team”)."
        case "RS004" | "RS006":
            who = step.actor_raw or step.actor_role_id if step else "that role"
            return (
                f"Name an alternate approver for the {who}'s own requests (for example the CFO or a "
                "committee) so these requests can be completed."
            )
        case "TM001":
            return "Add a time limit (SLA) for this step."
        case "TM002":
            return "Shorten the step time limits or extend the overall deadline so they are consistent."
        case "TM003":
            return "Replace vague wording (“promptly”) with a measurable limit such as “within 2 working days”."
        case "XD001":
            return "Add the referenced section, or correct the reference to a section that exists."
        case _:
            return None
    _ = dec


def _fingerprint(f: AggregatedFinding, proc: Process | None) -> str:
    node = (f.decision_id or f.step_id) if f.code in _DECISION_LEVEL else (f.step_id or f.decision_id)
    nums = _node_numbers(proc, node) if proc else [node or ""]
    key = f"{f.code}|{','.join(nums)}"
    if f.code in ("ST005",) and f.evidence:
        pair = f.evidence[0].data.get("branches")
        if isinstance(pair, list):
            key += "|" + "&".join(sorted(re.sub(r"\W+", "", str(x))[:24] for x in pair))
    return key + "|" + hashlib.sha1(key.encode()).hexdigest()[:6]


def _primary_span(f: AggregatedFinding, proc: Process | None) -> None:
    for ev in f.evidence:
        if ev.source_quote:
            f.clause_quote, f.document_id = ev.source_quote, ev.document_id
            f.char_start, f.char_end = ev.char_start, ev.char_end
            return
    if proc is None:
        return
    spans = []
    if f.decision_id and (dec := proc.decision(f.decision_id)):
        spans = dec.source_spans or [
            sp for b in dec.branches if (t := proc.step(b.next_step_id)) for sp in t.source_spans
        ]
    elif f.step_id and (st := proc.step(f.step_id)):
        spans = st.source_spans
    if spans:
        sp = spans[0]
        f.clause_quote, f.document_id, f.char_start, f.char_end = (
            sp.quote, sp.document_id, sp.char_start, sp.char_end,
        )


def _clause_ref(f: AggregatedFinding, proc: Process | None) -> str | None:
    if proc is None:
        return None
    node = (f.decision_id or f.step_id) if f.code in _DECISION_LEVEL else (f.step_id or f.decision_id)
    nums = _node_numbers(proc, node)
    nums = [n for n in nums if n and not n.startswith(("s", "d")) or re.match(r"^\d", n or "")]
    return ", ".join(nums) if nums else None


def enrich(report: FindingsReport, ir: SopIR | None) -> FindingsReport:
    # 1. fold runtime proofs into the static finding they reproduce
    by_key: dict[tuple[str, str | None], AggregatedFinding] = {}
    for f in report.findings:
        by_key.setdefault((f.code, f.decision_id or f.step_id), f)
    keep: list[AggregatedFinding] = []
    for f in report.findings:
        target_code = _PROVES.get(f.code)
        static = None
        if target_code:
            static = by_key.get((target_code, f.decision_id or f.step_id))
            if static is None and f.code == "RS006":
                static = next(
                    (g for g in report.findings if g.code == "RS004" and g.step_id == f.step_id), None
                )
        if static is not None and static is not f:
            static.evidence.extend(f.evidence)
            static.reproduced_by_tests += max(1, len(f.evidence))
            static.risk = RiskScore.compute(
                likelihood=1.0, impact=static.risk.impact, confidence=static.risk.confidence_weight
            )
            continue
        keep.append(f)
    report.findings = keep

    # 2. per-finding fields
    for f in report.findings:
        proc = _find_process(ir, f.process_id) if ir else None
        gap = TAXONOMY.get(f.code)
        if gap and f.title in (f.code, ""):
            f.title = gap.title
        f.message = next((ev.message for ev in f.evidence if ev.kind == "diagnostic"), None) or (
            f.evidence[0].message if f.evidence else f.title
        )
        f.witness = _witness(f)
        _primary_span(f, proc)
        f.clause_ref = _clause_ref(f, proc)
        if proc is not None:
            f.involved_node_ids = _involved(proc, f)
        f.suggested_fix = _fix(f, proc)
        f.fingerprint = _fingerprint(f, proc)
        if not f.reproduced_by_tests:
            f.reproduced_by_tests = sum(1 for ev in f.evidence if ev.kind == "test_failure")

    report.findings.sort(key=lambda x: -x.risk.total)
    for rank, f in enumerate(report.findings, start=1):
        f.rank = rank
    return report.with_stats()


__all__ = ["enrich"]
_ = (Decision, Step)
