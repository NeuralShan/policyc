"""Lightweight token-replay conformance checker (no pm4py dependency).

Algorithm
---------
For each case:
1. Map case activities → step IDs via the activity_map (None = unmapped).
2. Replay the events over the process graph: each event advances along the cheapest documented
   path to its step (steps passed on the way were skipped); unreachable or unmapped events are
   extra.
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
        TimeUnit.HOURS: 3600,
        TimeUnit.DAYS: 86400,
        TimeUnit.CALENDAR_DAYS: 86400,
        # Elapsed wall-clock time: five business days span about a calendar week.
        TimeUnit.BUSINESS_DAYS: 86400 * 7 / 5,
        TimeUnit.WEEKS: 604800,
    }
    return sla.max_duration * multipliers.get(sla.unit, 1)


def _flow_graph(proc: Process) -> tuple[dict[str, list[str]], set[str], str | None]:
    """Adjacency over on-flow steps and decisions, the set of step ids, and the entry node."""
    steps = {s.id for s in proc.steps if not s.off_flow}
    adj: dict[str, list[str]] = {sid: [] for sid in steps}
    for t in proc.transitions:
        adj.setdefault(t.from_id, []).append(t.to_id)
    for dec in proc.decisions:
        if dec.preceding_step_id:
            adj.setdefault(dec.preceding_step_id, []).append(dec.id)
        for branch in dec.branches:
            if branch.next_step_id:
                adj.setdefault(dec.id, []).append(branch.next_step_id)
    return adj, steps, proc.entry()


def _cheapest_path(
    adj: dict[str, list[str]], steps: set[str], sources: list[str], goal
) -> list[str] | None:
    """Path from any source to the first node satisfying ``goal`` that passes the fewest steps.

    0-1 BFS: entering a step costs 1, entering a decision costs 0. Sources themselves are free.
    Returns the nodes after the source, up to and including the goal node.
    """
    from collections import deque

    best: dict[str, int] = {n: 0 for n in sources}
    prev: dict[str, str | None] = {n: None for n in sources}
    queue = deque(sources)
    while queue:
        node = queue.popleft()
        if goal(node) and prev[node] is not None:
            path = [node]
            while prev[path[-1]] is not None and prev[path[-1]] not in sources:
                path.append(prev[path[-1]])  # type: ignore[arg-type]
            return path[::-1]
        for nxt in adj.get(node, []):
            cost = best[node] + (1 if nxt in steps else 0)
            if cost < best.get(nxt, 1 << 30):
                best[nxt] = cost
                prev[nxt] = node
                (queue.append if nxt in steps else queue.appendleft)(nxt)
    return None


def _replay_case(
    case_id: str,
    events: list[CaseEvent],
    proc: Process,
    activity_map: dict[str, str | None],
    sla_map: dict[str, float | None],   # step_id → SLA seconds
) -> CaseResult:
    """Replay one case over the process graph.

    Each mapped event moves the token forward along the cheapest documented path to its step; the
    steps passed on the way were skipped. An event whose step cannot be reached from the current
    position (or that maps to no step) is an extra move. At the end, the steps still needed to reach
    an end of the process count as skipped.
    """
    adj, steps, entry = _flow_graph(proc)
    synced: list[str] = []
    skipped: list[str] = []
    extra: list[str] = []
    sla_breaches: list[str] = []
    cur: str | None = None
    prev_ts = None

    for event in events:
        sid = activity_map.get(event.activity)
        if sid is None or sid not in steps:
            extra.append(event.activity)
            continue
        if cur is None:
            if entry is None:
                path = [sid]
            elif sid == entry:
                path = [entry]
            else:
                tail = _cheapest_path(adj, steps, [entry], lambda n, t=sid: n == t)
                path = [entry, *tail] if tail is not None else None
        else:
            path = _cheapest_path(adj, steps, [cur], lambda n, t=sid: n == t)
        if path is None:
            extra.append(event.activity)
            continue
        skipped.extend(n for n in path[:-1] if n in steps)
        synced.append(sid)
        sla_s = sla_map.get(sid)
        if (
            sla_s is not None
            and prev_ts is not None
            and event.timestamp is not None
            and (event.timestamp - prev_ts).total_seconds() > sla_s
        ):
            sla_breaches.append(sid)
        cur = sid
        if event.timestamp is not None:
            prev_ts = event.timestamp

    # Finish the case: steps still required to reach an end of the process.
    start = cur if cur is not None else entry
    if start is not None:
        if not adj.get(start):
            if cur is None and start in steps:
                skipped.append(start)
        else:
            tail = _cheapest_path(adj, steps, [start], lambda n: not adj.get(n))
            if tail is not None:
                if cur is None and start in steps:
                    skipped.append(start)
                skipped.extend(n for n in tail if n in steps)

    sync_n = len(synced)
    total = sync_n + len(skipped) + len(extra)
    fitness = sync_n / total if total > 0 else 1.0

    return CaseResult(
        case_id=case_id,
        fitness=round(fitness, 4),
        synced=synced,
        skipped=list(dict.fromkeys(skipped)),
        extra=list(dict.fromkeys(extra)),
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
                    f"real cases ({rate * 100:.0f}%) but does not fit the documented flow"
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
