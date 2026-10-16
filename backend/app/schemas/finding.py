"""Layer 4 diagnostic schema.

Each ``Diagnostic`` is one gap or issue the static analyzer found in the SOP IR.
It mirrors a compiler diagnostic: code, location, message, evidence.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.provenance import SourceSpan


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class CheckTier(StrEnum):
    DETERMINISTIC = "deterministic"  # networkx / Z3 — zero LLM calls
    LANGUAGE = "language"            # pattern-based language checks


class Diagnostic(BaseModel):
    code: str                        # e.g. "ST001"
    severity: Severity
    message: str
    process_id: str | None = None
    step_id: str | None = None
    decision_id: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    check_tier: CheckTier = CheckTier.DETERMINISTIC


class DiagnosticsReport(BaseModel):
    run_id: str
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)  # counts per code + total_*

    def with_stats(self) -> DiagnosticsReport:
        counts: dict[str, int] = {}
        for d in self.diagnostics:
            counts[d.code] = counts.get(d.code, 0) + 1
        counts["total_errors"] = sum(
            1 for d in self.diagnostics if d.severity == Severity.ERROR
        )
        counts["total_warnings"] = sum(
            1 for d in self.diagnostics if d.severity == Severity.WARNING
        )
        counts["total_infos"] = sum(
            1 for d in self.diagnostics if d.severity == Severity.INFO
        )
        counts["total"] = len(self.diagnostics)
        self.stats = counts
        return self
