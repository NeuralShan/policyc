"""Layer 5 trace schema: Scenario inputs and ExecutionTrace outputs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.provenance import SourceSpan

TRACE_VERSION = 1


# ---------------------------------------------------------------------------
# Scenario (what the simulator is given)
# ---------------------------------------------------------------------------


class Scenario(BaseModel):
    """Input to the process simulator."""

    id: str                                       # stable slug, e.g. "sc_refund_over_5k"
    description: str
    process_id: str | None = None                 # None → first process in the IR
    facts: dict[str, Any] = Field(default_factory=dict)
    # role_id → actor name (or None = actor unavailable / absent)
    actor_overrides: dict[str, str | None] = Field(default_factory=dict)
    # system_id → is system up (False = down)
    system_overrides: dict[str, bool] = Field(default_factory=dict)
    max_steps: int = 100                          # safety limit


# ---------------------------------------------------------------------------
# Per-step trace events
# ---------------------------------------------------------------------------


class DecisionOutcome(StrEnum):
    DETERMINED = "determined"      # exactly one branch condition is satisfied
    UNDETERMINED = "undetermined"  # no branch condition is satisfied
    CONFLICT = "conflict"          # multiple branch conditions are satisfied
    AMBIGUOUS = "ambiguous"        # at least one branch is vague or unknown


class StepStatus(StrEnum):
    OK = "ok"
    SLA_BREACHED = "sla_breached"
    ACTOR_UNAVAILABLE = "actor_unavailable"
    SYSTEM_DOWN = "system_down"
    INPUT_MISSING = "input_missing"


class TraceStep(BaseModel):
    """One event in the execution trace."""

    seq: int                            # 0-based position in the trace
    node_id: str                        # step_id or decision_id
    node_kind: Literal["step", "decision", "terminal"]
    process_id: str
    action: str | None = None           # step.action (None for decisions)
    actor: str | None = None            # resolved actor name
    step_status: StepStatus | None = None
    decision_outcome: DecisionOutcome | None = None
    branch_taken: str | None = None     # label of branch taken (decisions only)
    sla_max_s: float | None = None      # step.sla converted to seconds
    elapsed_s: float = 0.0              # simulated elapsed time at this point
    sla_ok: bool | None = None          # None when no SLA defined
    source_spans: list[SourceSpan] = Field(default_factory=list)
    note: str | None = None             # e.g. "actor 'approver' unavailable"


# ---------------------------------------------------------------------------
# Overall trace
# ---------------------------------------------------------------------------


class TraceOutcome(StrEnum):
    COMPLETED = "completed"         # reached a TERMINAL step
    DEAD_END = "dead_end"           # step with no outgoing edge and not terminal
    UNDETERMINED = "undetermined"   # decision had no matching branch
    CONFLICT = "conflict"           # decision had multiple matching branches
    AMBIGUOUS = "ambiguous"         # decision had vague/unknown condition
    LOOP_DETECTED = "loop_detected" # same step encountered twice
    MAX_STEPS = "max_steps"         # safety limit reached


class ExecutionTrace(BaseModel):
    """The full trace produced by one simulation run."""

    version: int = TRACE_VERSION
    run_id: str
    process_id: str
    scenario_id: str
    scenario: Scenario
    steps: list[TraceStep] = Field(default_factory=list)
    outcome: TraceOutcome
    elapsed_s: float = 0.0
    sla_breaches: int = 0
    actor_unavailable_count: int = 0
    system_down_count: int = 0
    created_at: datetime | None = None
