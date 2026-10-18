"""ST004 / ST005 — Decision branch checks using Z3.

ST004  decision missing a branch (fewer than 2 branches, or Z3 finds an input no branch covers)
ST005  overlapping branches (Z3 finds an input satisfying two branches simultaneously)

Branch conditions over numbers, booleans and enum-like values are modelled exactly (see
``app.logic``).  An "otherwise" (``always``) branch is the complement of the other branches, so it
never overlaps them and it makes the decision exhaustive.  A vague/unknown condition cannot be
proved either way, so the decision is skipped rather than reported falsely.
"""

from __future__ import annotations

import logging

import z3

from app.analyze.registry import register
from app.logic import ConstraintBuilder, describe_condition, display_value, same_outcome
from app.schemas.finding import CheckTier, Diagnostic, Severity
from app.schemas.graph import LinkedIR
from app.schemas.ir_sop import AlwaysCondition, Decision, Process, SopIR

log = logging.getLogger(__name__)


def _readable(facts: dict) -> str:
    return ", ".join(f"{k} = {display_value(v)}" for k, v in sorted(facts.items()))


def _check_decision(dec: Decision, proc_id: str, proc: Process | None = None) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    # ST004 — fewer than 2 branches
    if len(dec.branches) < 2:
        diags.append(
            Diagnostic(
                code="ST004",
                severity=Severity.ERROR,
                message=(
                    f"Decision '{dec.id}' ('{dec.question}') has only "
                    f"{len(dec.branches)} branch(es) — at least 2 required"
                ),
                process_id=proc_id,
                decision_id=dec.id,
                source_spans=dec.source_spans,
                check_tier=CheckTier.DETERMINISTIC,
            )
        )
        return diags

    builder = ConstraintBuilder()
    for b in dec.branches:
        builder.scan(b.condition)

    explicit: list[tuple[int, z3.BoolRef]] = []
    always_idx: list[int] = []
    for i, b in enumerate(dec.branches):
        if isinstance(b.condition, AlwaysCondition):
            always_idx.append(i)
            continue
        f = builder.formula(b.condition)
        if f is None:
            log.debug("decision %s: skipping Z3 (un-translatable branch %r)", dec.id, b.label)
            return diags
        explicit.append((i, f))

    domain = builder.domain()

    # ST005 — two or more unconditional branches contradict each other
    if len(always_idx) > 1:
        labels = [dec.branches[i].label for i in always_idx]
        diags.append(
            Diagnostic(
                code="ST005",
                severity=Severity.ERROR,
                message=(
                    f"Decision '{dec.id}' ('{dec.question}'): branches {labels} are all "
                    "unconditional, so every case matches all of them"
                ),
                process_id=proc_id,
                decision_id=dec.id,
                source_spans=dec.source_spans,
                evidence={"branches": labels},
                check_tier=CheckTier.DETERMINISTIC,
            )
        )

    # ST005 — overlapping explicit branches: ∃ input satisfying bi ∧ bj
    for a in range(len(explicit)):
        for c in range(a + 1, len(explicit)):
            (i, fi), (j, fj) = explicit[a], explicit[c]
            if same_outcome(proc, dec.branches[i].next_step_id, dec.branches[j].next_step_id):
                continue  # redundant rules agreeing on the outcome are not a conflict
            s = z3.Solver()
            s.add(*domain, fi, fj)
            if s.check() == z3.sat:
                facts = builder.facts(s.model())
                bi, bj = dec.branches[i], dec.branches[j]
                diags.append(
                    Diagnostic(
                        code="ST005",
                        severity=Severity.ERROR,
                        message=(
                            f"Decision '{dec.id}': branch '{bi.label}' "
                            f"({describe_condition(bi.condition)}) and branch '{bj.label}' "
                            f"({describe_condition(bj.condition)}) overlap — e.g. when "
                            f"{_readable(facts)} both apply"
                        ),
                        process_id=proc_id,
                        decision_id=dec.id,
                        source_spans=dec.source_spans,
                        evidence={
                            "counterexample": facts,
                            "branches": [bi.label, bj.label],
                            "conditions": [
                                describe_condition(bi.condition),
                                describe_condition(bj.condition),
                            ],
                            "targets": [bi.next_step_id, bj.next_step_id],
                        },
                        check_tier=CheckTier.DETERMINISTIC,
                    )
                )

    # ST004 — non-exhaustive: ¬(b1 ∨ … ∨ bn) satisfiable (an "otherwise" branch closes the gap)
    if explicit and not always_idx:
        s = z3.Solver()
        s.add(*domain, z3.Not(z3.Or(*[f for _, f in explicit])))
        if s.check() == z3.sat:
            facts = builder.facts(s.model())
            diags.append(
                Diagnostic(
                    code="ST004",
                    severity=Severity.ERROR,
                    message=(
                        f"Decision '{dec.id}' ('{dec.question}') is non-exhaustive: "
                        f"no branch applies when {_readable(facts)}"
                    ),
                    process_id=proc_id,
                    decision_id=dec.id,
                    source_spans=dec.source_spans,
                    evidence={
                        "counterexample": facts,
                        "conditions": [describe_condition(b.condition) for b in dec.branches],
                    },
                    check_tier=CheckTier.DETERMINISTIC,
                )
            )

    return diags


@register("ST", "Decision branch checks (Z3)")
def decision_checks(ir: SopIR, _linked: LinkedIR | None) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for proc in ir.processes:
        for dec in proc.decisions:
            diags.extend(_check_decision(dec, proc.id, proc))
    return diags
