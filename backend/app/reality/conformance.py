"""Lightweight token-replay conformance checker (no pm4py dependency).

Algorithm
---------
For each case:
1. Map case activities → step IDs via the activity_map (None = unmapped).
2. Walk the SOP process in DFS order and try to match mapped step IDs in sequence.
3. Count sync_moves (matched), model_moves (skipped), log_moves (extra).
4. fitness = sync_moves / (sync_moves + model_moves + log_moves).
5. Optionally check elapsed time against SLA where timestamps exist.

RL findings emitted:
  RL001 — step routinely skipped  (skip_rate > SKIP_THRESHOLD)
  RL002 — activity routinely performed but not in model (extra_rate > EXTRA_THRESHOLD)
  RL003 — SLA routinely breached  (sla_breach_rate > SLA_THRESHOLD)
  RL004 — case fits no documented path  (fitness < NO_PATH_THRESHOLD)
"""

from __future__ import annotations

import logging

from app.schemas.case_history import CaseEvent, EventLog
from app.schemas.ir_sop import SLA, Process, SopIR, TimeUnit
from app.schemas.reality import CaseResult, RealityReport, RlFinding, StepStats

log = logging.getLogger(__name__)

SKIP_THRESHOLD = 0.10      # RL001: flagged when > 10 % of cases skip a step
EXTRA_THRESHOLD = 0.10     # RL002: flagged when > 10 % of cases perform an extra activity
SLA_THRESHOLD = 0.10       # RL003: flagged when > 10 % of cases breach a step SLA
NO_PATH_THRESHOLD = 0.20   # RL004: case has no documented path if fitness < 20 %
CONFORMANT_THRESHOLD = 0.80


def _sla_to_seconds(sla: SLA) -> float | None:
    if sla.vague or sla.max_duration is None:
        return None
    multipliers = {
        TimeUnit.SECONDS: 1,
        TimeUnit.MINUTES: 60,
        TimeUnit.HOURS: 3600,
        TimeUnit.DAYS: 86400,
        TimeUnit.WEEKS: 604800,
    }
    return sla.max_duration * multipliers.get(sla.unit, 1)


def _ordered_step_ids(proc: Process) -> list[str]:
    """Return a BFS-ordered list of step IDs for the process.

    At decisions, all branches are included in the order they appear (depth-first).
    This gives an ordered 'expected' sequence for greedy matching.
    """
    # Build adjacency: step_id → next step_ids (from transitions + decision branches)
    adj: dict[str, list[str]] = {s.id: [] for s in proc.steps}
    for t in proc.transitions:
        adj.setdefault(t.from_id, []).append(t.to_id)
    for dec in proc.decisions:
        for branch in dec.branches:
            if branch.next_step_id:
                adj.setdefault(dec.preceding_step_id, []).append(branch.next_step_id)

    # Find start step (no incoming edges)
    all_ids = {s.id for s in proc.steps}
    targets = {nid for nexts in adj.values() for nid in nexts}
    starts = all_ids - targets
    if not starts:
        return [s.id for s in proc.steps]  # cycle: fall back to declaration order

    start = next(iter(starts))
    visited: list[str] = []
    seen: set[str] = set()

    def dfs(node_id: str) -> None:
        if node_id in seen:
            return
        seen.add(node_id)
        visited.append(node_id)
        for nxt in adj.get(node_id, []):
            dfs(nxt)

    dfs(start)
    # Add any steps not reachable from start (disconnected sub-processes)
    for s in proc.steps:
        if s.id not in seen:
            visited.append(s.id)
    return visited


def _replay_case(
    case_id: str,
    events: list[CaseEvent],
    proc: Process,
    activity_map: dict[str, str | None],
    sla_map: dict[str, float | None],   # step_id → SLA seconds
) -> CaseResult:
    ordered_steps = _ordered_step_ids(proc)
    # Map case activities to step_ids (preserve order, keep None)
    event_step_ids = [activity_map.get(e.activity) for e in events]

    synced: list[str] = []
    skipped: list[str] = []
    sla_breaches: list[str] = []

    case_ptr = 0
    for step_id in ordered_steps:
        found = False
        while case_ptr < len(event_step_ids):
            if event_step_ids[case_ptr] == step_id:
                synced.append(step_id)
                # SLA check: time from previous matched event to this one
                if sla_map.get(step_id) is not None:
                    sla_s = sla_map[step_id]
                    cur_event = events[case_ptr]
                    # Find previous event with a timestamp
                    prev_ts = None
                    for j in range(case_ptr - 1, -1, -1):
                        if events[j].timestamp is not None:
                            prev_ts = events[j].timestamp
                            break
                    if (
                        prev_ts is not None
                        and cur_event.timestamp is not None
                        and sla_s is not None
                    ):
                        elapsed = (cur_event.timestamp - prev_ts).total_seconds()
                        if elapsed > sla_s:
                            sla_breaches.append(step_id)
                case_ptr += 1
                found = True
                break
            else:
                case_ptr += 1

        if not found:
            skipped.append(step_id)

    # Extra: activities that mapped to a step but that step wasn't synced
    synced_set = set(synced)
    extra_steps = [
        sid
        for sid in event_step_ids
        if sid is not None and sid not in synced_set
    ]
    extra_unmapped = [
        events[i].activity
        for i, sid in enumerate(event_step_ids)
        if sid is None
    ]

    sync_n = len(synced)
    model_n = len(skipped)
    log_n = len(extra_steps)
    total = sync_n + model_n + log_n
    fitness = sync_n / total if total > 0 else 1.0

    return CaseResult(
        case_id=case_id,
        fitness=round(fitness, 4),
        synced=synced,
        skipped=skipped,
        extra=list(dict.fromkeys(extra_steps + extra_unmapped)),
        sla_breaches=sla_breaches,
        has_no_path=fitness < NO_PATH_THRESHOLD,
    )


def check_conformance(
    event_log: EventLog,
    ir: SopIR,
    activity_map: dict[str, str | None],
) -> RealityReport:
    """Run token-replay conformance for all cases and produce RL findings."""
    if not ir.processes:
        return RealityReport(
            run_id=event_log.run_id,
            source_filename=event_log.source_filename,
        ).with_stats()

    proc = ir.processes[0]   # use first process (most SOPs have one)

    # Build SLA map: step_id → seconds (None if no SLA or vague)
    sla_map: dict[str, float | None] = {}
    for step in proc.steps:
        sla_map[step.id] = _sla_to_seconds(step.sla) if step.sla else None

    # Replay every case
    case_results: list[CaseResult] = []
    for case_id, events in event_log.cases.items():
        result = _replay_case(case_id, events, proc, activity_map, sla_map)
        case_results.append(result)

    # Aggregate step stats
    all_step_ids = [s.id for s in proc.steps]
    step_stats: dict[str, StepStats] = {sid: StepStats(step_id=sid) for sid in all_step_ids}

    extra_activity_counts: dict[str, int] = {}
    for result in case_results:
        for sid in all_step_ids:
            step_stats[sid].total_cases += 1
        for sid in result.synced:
            if sid in step_stats:
                step_stats[sid].synced_count += 1
        for sid in result.skipped:
            if sid in step_stats:
                step_stats[sid].skipped_count += 1
        for act in result.extra:
            extra_activity_counts[act] = extra_activity_counts.get(act, 0) + 1
        for sid in result.sla_breaches:
            if sid in step_stats:
                step_stats[sid].sla_breach_count += 1

    total = len(case_results)

    # Generate RL findings
    rl_findings: list[RlFinding] = []

    # RL001: step routinely skipped
    for sid, stats in step_stats.items():
        if stats.skip_rate > SKIP_THRESHOLD:
            rl_findings.append(RlFinding(
                code="RL001",
                message=(
                    f"Step '{sid}' is skipped in {stats.skipped_count}/{stats.total_cases} "
                    f"real cases ({stats.skip_rate * 100:.0f}%)"
                ),
                step_id=sid,
                case_count=stats.skipped_count,
                rate=round(stats.skip_rate, 3),
            ))

    # RL002: undocumented activity routinely performed
    for activity, count in extra_activity_counts.items():
        rate = count / total if total else 0.0
        if rate > EXTRA_THRESHOLD:
            rl_findings.append(RlFinding(
                code="RL002",
                message=(
                    f"Activity '{activity}' is performed in {count}/{total} "
                    f"real cases ({rate * 100:.0f}%) but has no matching SOP step"
                ),
                activity=activity,
                case_count=count,
                rate=round(rate, 3),
            ))

    # RL003: SLA routinely breached
    for sid, stats in step_stats.items():
        if sla_map.get(sid) and stats.sla_breach_rate > SLA_THRESHOLD:
            rl_findings.append(RlFinding(
                code="RL003",
                message=(
                    f"SLA breached for step '{sid}' in {stats.sla_breach_count}/"
                    f"{stats.total_cases} real cases ({stats.sla_breach_rate * 100:.0f}%)"
                ),
                step_id=sid,
                case_count=stats.sla_breach_count,
                rate=round(stats.sla_breach_rate, 3),
            ))

    # RL004: cases with no documented path
    no_path_cases = [r for r in case_results if r.has_no_path]
    if no_path_cases:
        no_path_rate = len(no_path_cases) / total if total else 0.0
        rl_findings.append(RlFinding(
            code="RL004",
            message=(
                f"{len(no_path_cases)}/{total} real cases follow no documented SOP path "
                f"(fitness < {NO_PATH_THRESHOLD:.0%})"
            ),
            case_count=len(no_path_cases),
            rate=round(no_path_rate, 3),
        ))

    log.info(
        "conformance: %d cases  avg_fitness=%.3f  rl_findings=%d",
        total,
        sum(r.fitness for r in case_results) / total if total else 0.0,
        len(rl_findings),
    )

    return RealityReport(
        run_id=event_log.run_id,
        source_filename=event_log.source_filename,
        case_results=case_results,
        step_stats=step_stats,
        extra_activity_counts=extra_activity_counts,
        rl_findings=rl_findings,
    ).with_stats()
