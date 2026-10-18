"""SOP Intermediate Representation (Layer 2 output / the "parser" artefact).

A procedural document becomes one or more ``Process`` objects in this IR.  Every element carries
``source_spans`` pointing back into the DocAST so any claim can be verified against the original
text.

Schema is versioned: bump ``SOP_IR_VERSION`` whenever the shape changes in a breaking way so the
DB can detect stale records.
"""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.schemas.provenance import SourceSpan

SOP_IR_VERSION = 1

# ---------------------------------------------------------------------------
# Condition DSL (simple structured representation; full grammar in dsl.py)
# ---------------------------------------------------------------------------


class ConditionKind(StrEnum):
    COMPARE = "compare"  # left op right
    LOGICAL = "logical"  # and / or / not over sub-conditions
    VAGUE = "vague"  # "promptly", "soon", "as needed" – cannot be evaluated
    ALWAYS = "always"  # unconditional / default branch
    UNKNOWN = "unknown"  # extractor could not parse the condition


class ValueType(StrEnum):
    NUMBER = "number"
    MONEY = "money"
    DURATION = "duration"
    DATE = "date"
    ENUM = "enum"
    BOOL = "bool"


class TypedValue(BaseModel):
    """A literal value in a condition expression."""

    value_type: ValueType
    number: float | None = None
    text: str | None = None  # for enum / date strings
    bool_value: bool | None = None
    currency: str | None = None  # for money (e.g. "INR", "USD")
    duration_unit: str | None = None  # "hours", "days", "business_days", "calendar_days"


class CompareCondition(BaseModel):
    kind: Literal[ConditionKind.COMPARE] = ConditionKind.COMPARE
    left: str  # variable / attribute name (e.g. "refund_amount")
    op: str  # "gt", "gte", "lt", "lte", "eq", "ne", "in", "not_in"
    right: TypedValue


class LogicalCondition(BaseModel):
    kind: Literal[ConditionKind.LOGICAL] = ConditionKind.LOGICAL
    logical_op: Literal["and", "or", "not"]
    operands: list["ConditionExpr"]


class VagueCondition(BaseModel):
    kind: Literal[ConditionKind.VAGUE] = ConditionKind.VAGUE
    text: str  # verbatim vague phrase


class AlwaysCondition(BaseModel):
    kind: Literal[ConditionKind.ALWAYS] = ConditionKind.ALWAYS


class UnknownCondition(BaseModel):
    kind: Literal[ConditionKind.UNKNOWN] = ConditionKind.UNKNOWN
    raw_text: str  # the original text the extractor could not parse


ConditionExpr = Annotated[
    CompareCondition | LogicalCondition | VagueCondition | AlwaysCondition | UnknownCondition,
    Field(discriminator="kind"),
]

# ---------------------------------------------------------------------------
# Symbol table (glossary extracted from the SOP)
# ---------------------------------------------------------------------------


class RoleRef(BaseModel):
    """An actor / organisational role."""

    id: str  # slugified, e.g. "finance_manager"
    name: str  # as written, e.g. "Finance Manager"
    description: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class ArtifactRef(BaseModel):
    """A document or data artefact produced or consumed by steps."""

    id: str
    name: str  # e.g. "Refund Approval Form (RAF)"
    abbreviation: str | None = None  # e.g. "RAF"
    source_spans: list[SourceSpan] = Field(default_factory=list)


class SystemRef(BaseModel):
    """An IT system or tool referenced by the process."""

    id: str
    name: str  # e.g. "CRM", "Active Directory"
    source_spans: list[SourceSpan] = Field(default_factory=list)


class TermDef(BaseModel):
    """A domain term that appears in conditions or steps."""

    id: str
    name: str
    definition: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class SymbolTable(BaseModel):
    roles: list[RoleRef] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    systems: list[SystemRef] = Field(default_factory=list)
    terms: list[TermDef] = Field(default_factory=list)

    def role(self, role_id: str) -> RoleRef | None:
        return next((r for r in self.roles if r.id == role_id), None)

    def artifact(self, artifact_id: str) -> ArtifactRef | None:
        return next((a for a in self.artifacts if a.id == artifact_id), None)

    def system(self, system_id: str) -> SystemRef | None:
        return next((s for s in self.systems if s.id == system_id), None)

    def all_ids(self) -> set[str]:
        return (
            {r.id for r in self.roles}
            | {a.id for a in self.artifacts}
            | {s.id for s in self.systems}
            | {t.id for t in self.terms}
        )


# ---------------------------------------------------------------------------
# SLA / time constraints
# ---------------------------------------------------------------------------


class TimeUnit(StrEnum):
    HOURS = "hours"
    DAYS = "days"
    BUSINESS_DAYS = "business_days"
    CALENDAR_DAYS = "calendar_days"
    WEEKS = "weeks"


class SLA(BaseModel):
    """A time constraint on a step or the overall process."""

    max_duration: float
    unit: TimeUnit
    from_event: str = "step_start"  # e.g. "step_start", "trigger", "logging"
    vague: bool = False  # True when the original used "promptly" etc.
    vague_text: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Flow elements
# ---------------------------------------------------------------------------


class ModalVerb(StrEnum):
    SHALL = "shall"  # mandatory
    SHOULD = "should"  # recommended (may be optional, signals LG002)
    MAY = "may"  # permitted
    MUST = "must"  # mandatory (synonymous with SHALL)
    WILL = "will"  # often declarative / mandatory
    UNKNOWN = "unknown"


class StepKind(StrEnum):
    ACTION = "action"  # regular task step
    VERIFICATION = "verification"  # check / verify / confirm
    NOTIFICATION = "notification"  # inform / notify
    APPROVAL = "approval"  # explicit approval step
    ESCALATION = "escalation"  # escalate to a higher authority
    TERMINAL = "terminal"  # process end (approved, rejected, closed, etc.)


class TerminalOutcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    CLOSED = "closed"
    COMPLETED = "completed"
    OTHER = "other"


class Step(BaseModel):
    """One action / task in the process flow."""

    id: str  # "s01", stable within one process
    kind: StepKind = StepKind.ACTION
    number: str | None = None  # clause number as printed, e.g. "4.1"
    actor_role_id: str | None = None  # references SymbolTable.roles[*].id
    actor_raw: str | None = None  # original text when role not in symbol table
    modal: ModalVerb = ModalVerb.UNKNOWN
    action: str  # short verb phrase, e.g. "log complaint in CRM"
    inputs: list[str] = Field(default_factory=list)  # artifact ids
    outputs: list[str] = Field(default_factory=list)  # artifact ids
    systems: list[str] = Field(default_factory=list)  # system ids
    preconditions: list[ConditionExpr] = Field(default_factory=list)
    sla: SLA | None = None
    terminal_outcome: TerminalOutcome | None = None  # set only when kind=TERMINAL
    source_spans: list[SourceSpan] = Field(default_factory=list)
    extraction_confidence: float = 1.0  # 0–1; below 0.7 the step is flagged for review
    note: str | None = None  # extractor's explanatory note for low-confidence items
    inferred: bool = False  # True when the flow normaliser added this step (not stated in text)
    off_flow: bool = False  # standing rule / principle (e.g. "no one may approve their own claim")


class DecisionBranch(BaseModel):
    """One labelled branch of a decision (e.g. "Yes", "amount < 5000")."""

    label: str  # human-readable label, e.g. "Upheld"
    condition: ConditionExpr
    next_step_id: str  # id of the Step (or "END") this branch leads to
    source_spans: list[SourceSpan] = Field(default_factory=list)


class Decision(BaseModel):
    """A branching point."""

    id: str  # "d01"
    question: str  # e.g. "Is the complaint upheld?"
    preceding_step_id: str | None = None  # which step leads here (None: entered from a decision)
    branches: list[DecisionBranch]
    source_spans: list[SourceSpan] = Field(default_factory=list)
    extraction_confidence: float = 1.0
    inferred: bool = False  # True when the flow normaliser derived this decision from sibling clauses


class Transition(BaseModel):
    """Direct edge from one step to another (no decision needed)."""

    from_id: str  # step id or decision id
    to_id: str  # step id or "END"
    condition: ConditionExpr = Field(default_factory=AlwaysCondition)
    label: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)
    inferred: bool = False  # True when added by the flow normaliser (document order assumption)


class Deadline(BaseModel):
    """An end-to-end time limit, e.g. "reimbursed within 7 calendar days of submission"."""

    id: str
    description: str
    max_duration: float
    unit: TimeUnit
    from_step_id: str | None = None  # None = process start
    to_step_id: str | None = None  # None = process end
    source_spans: list[SourceSpan] = Field(default_factory=list)


class ConstraintKind(StrEnum):
    MUST_PRECEDE = "must_precede"  # `before_step_id` must always happen before `target_step_id`
    NO_SELF_ACTION = "no_self_action"  # the requester may not perform steps of `role_id` on itself


class Constraint(BaseModel):
    """A rule that must hold on every path (safety invariant, segregation of duties)."""

    id: str
    kind: ConstraintKind
    description: str
    before_step_id: str | None = None
    target_step_id: str | None = None
    role_id: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class ExternalReference(BaseModel):
    """A reference to another document (XD001 candidate if unresolved)."""

    ref_text: str  # as written, e.g. "Refund Policy RP-02 §3.2"
    doc_code: str | None = None
    section: str | None = None
    resolved: bool = False
    source_spans: list[SourceSpan] = Field(default_factory=list)


class Trigger(BaseModel):
    """What initiates the process."""

    description: str
    inputs: list[str] = Field(default_factory=list)  # artifact ids
    condition: ConditionExpr | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Process and top-level IR
# ---------------------------------------------------------------------------


class Process(BaseModel):
    """A single end-to-end process extracted from (part of) a document."""

    id: str  # "proc_01"
    name: str
    document_id: str
    trigger: Trigger | None = None
    overall_sla: SLA | None = None
    entry_step_id: str | None = None  # explicit start node; falls back to the first step
    steps: list[Step] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    references: list[ExternalReference] = Field(default_factory=list)
    deadlines: list[Deadline] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    non_operational_numbers: list[str] = Field(default_factory=list)  # purpose/scope clauses
    section_numbers: list[str] = Field(default_factory=list)  # top-level section numbers present

    def entry(self) -> str | None:
        if self.entry_step_id and (self.step(self.entry_step_id) or self.decision(self.entry_step_id)):
            return self.entry_step_id
        return self.steps[0].id if self.steps else None

    def step(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def decision(self, decision_id: str) -> Decision | None:
        return next((d for d in self.decisions if d.id == decision_id), None)


class ExtractionWarning(BaseModel):
    code: str  # e.g. "low_confidence", "ungrounded", "roundtrip_mismatch", "xd004_candidate"
    message: str
    step_id: str | None = None
    decision_id: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)


class ReviewStatus(StrEnum):
    PENDING = "pending"  # awaiting human review
    APPROVED = "approved"  # human approved (possibly with edits)
    REJECTED = "rejected"  # human rejected; re-extraction needed


class SopIR(BaseModel):
    """The complete Layer 2 output for one or more documents in a run."""

    schema_version: int = SOP_IR_VERSION
    run_id: str
    document_ids: list[str]
    symbols: SymbolTable = Field(default_factory=SymbolTable)
    processes: list[Process] = Field(default_factory=list)
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.PENDING
    review_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Keyed by step/decision id; human edits applied before link stage",
    )
    extraction_stats: dict[str, int] = Field(default_factory=dict)
    # Raw model replies kept so a revision can recompile incrementally: only sections whose text
    # changed go back to the model; the rest (and the flow pass) are replayed.
    raw_sections: dict[str, dict[str, Any]] = Field(default_factory=dict)  # doc key -> section -> reply
    flow_replies: dict[str, Any] = Field(default_factory=dict)  # doc key -> flow-pass reply
