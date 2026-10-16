"""Gap taxonomy v1 for SOPs: the compiler's error codes.

Codes are stable identifiers: findings, suppressions, golden-set annotations and eval metrics all
refer to them. Add new codes; never renumber or reuse old ones.
"""

from enum import StrEnum

from pydantic import BaseModel


class GapCategory(StrEnum):
    ST = "Structure"
    RS = "Responsibility"
    DF = "Data flow"
    TM = "Time"
    LG = "Language"
    XD = "Cross-document"
    EX = "Execution"
    RL = "Reality"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DetectionTier(StrEnum):
    """How a code is detected; drives the confidence a finding can claim."""

    DETERMINISTIC = "deterministic"  # graph algorithms, solver, simulator: no LLM involved
    HISTORICAL = "historical"  # evidence from real case history
    JUDGMENT = "judgment"  # needs an LLM's reading of language


class GapCode(BaseModel):
    code: str
    category: GapCategory
    title: str
    default_severity: Severity
    layer: int  # plan layer that first detects it
    tier: DetectionTier


_E, _W, _I = Severity.ERROR, Severity.WARNING, Severity.INFO
_D, _H, _J = DetectionTier.DETERMINISTIC, DetectionTier.HISTORICAL, DetectionTier.JUDGMENT

_CODES: list[tuple[str, str, Severity, int, DetectionTier]] = [
    ("ST001", "Unreachable step", _E, 4, _D),
    ("ST002", "Dead end: step has no next step and is not a terminal outcome", _E, 4, _D),
    ("ST003", "Loop without exit condition or retry limit", _E, 4, _D),
    ("ST004", "Decision does not cover all cases (missing branch)", _E, 4, _D),
    ("ST005", "Decision branches overlap", _E, 4, _D),
    ("ST006", "Process has no trigger or entry criteria", _W, 4, _D),
    ("ST007", "Process has no defined terminal outcome", _E, 4, _D),
    ("RS001", "Step has no owner", _E, 4, _D),
    ("RS002", "Vague owner (e.g. 'the team', 'relevant authority')", _W, 4, _D),
    ("RS003", "Role not found in the organisation's role directory", _W, 4, _D),
    ("RS004", "Segregation-of-duties violation", _E, 4, _D),
    ("RS005", "Escalation chain has no terminal authority, or cycles", _E, 4, _D),
    ("RS006", "No backup when an actor is unavailable", _W, 4, _D),
    ("DF001", "Artifact used before it is produced", _E, 4, _D),
    ("DF002", "Undefined artifact, system or term", _W, 4, _D),
    ("DF003", "Output is produced but never used", _I, 4, _D),
    ("TM001", "Step has no time limit (SLA)", _W, 4, _D),
    ("TM002", "Step time limits exceed the overall SLA", _E, 4, _D),
    ("TM003", "Vague time expression (e.g. 'promptly')", _W, 4, _D),
    ("TM004", "Business-day vs calendar-day or timezone ambiguity", _W, 4, _D),
    ("LG001", "Vague quantifier (e.g. 'reasonable', 'significant')", _W, 4, _J),
    ("LG002", "Modal ambiguity (should / must / may)", _W, 4, _J),
    ("LG003", "Independent extractions disagree: source text is ambiguous", _W, 2, _J),
    ("XD001", "Dangling cross-reference", _W, 3, _D),
    ("XD002", "Conflicting statements across documents", _E, 4, _D),
    ("XD003", "Hand-off mismatch between processes", _E, 4, _D),
    ("XD004", "Text and diagram describe different flows", _E, 2, _D),
    ("EX001", "Scenario outcome undetermined: the document is silent", _E, 7, _D),
    ("EX002", "Scenario reaches conflicting outcomes", _E, 7, _D),
    ("EX003", "SLA breached under a realistic perturbation", _W, 7, _D),
    ("EX004", "Loophole: compliant path with a harmful outcome", _E, 7, _D),
    ("RL001", "Documented step routinely skipped in practice", _W, 8, _H),
    ("RL002", "Undocumented step routinely performed in practice", _W, 8, _H),
    ("RL003", "Documented SLA routinely breached in practice", _W, 8, _H),
    ("RL004", "Real cases follow no documented path", _E, 8, _H),
    ("RL005", "Complaint or audit finding traced to a clause", _E, 8, _H),
]

TAXONOMY: dict[str, GapCode] = {
    code: GapCode(
        code=code,
        category=GapCategory[code[:2]],
        title=title,
        default_severity=severity,
        layer=layer,
        tier=tier,
    )
    for code, title, severity, layer, tier in _CODES
}
