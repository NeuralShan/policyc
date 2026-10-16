"""DF: Data-flow checks.

DF001  artifact consumed before it is produced (use-before-define in topological order)
DF002  undefined artifact or system (referenced in a step but absent from the SymbolTable)
DF003  artifact produced but never consumed (dead output)
"""

from __future__ import annotations

from app.analyze.registry import register
from app.schemas.finding import CheckTier, Diagnostic, Severity
from app.schemas.graph import LinkedIR
from app.schemas.ir_sop import SopIR


@register("DF", "Data-flow checks")
def dataflow_checks(ir: SopIR, _linked: LinkedIR | None) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    known_artifact_ids = {a.id for a in ir.symbols.artifacts}
    known_system_ids = {s.id for s in ir.symbols.systems}

    for proc in ir.processes:
        produced: set[str] = set()
        consumed: set[str] = set()

        for step in proc.steps:
            # DF002 — undefined artifact
            for art_id in step.inputs + step.outputs:
                if art_id not in known_artifact_ids:
                    diags.append(
                        Diagnostic(
                            code="DF002",
                            severity=Severity.WARNING,
                            message=(
                                f"Step '{step.id}': artifact '{art_id}' is not defined "
                                "in the symbol table"
                            ),
                            process_id=proc.id,
                            step_id=step.id,
                            source_spans=step.source_spans,
                            evidence={"artifact_id": art_id},
                            check_tier=CheckTier.DETERMINISTIC,
                        )
                    )

            # DF002 — undefined system
            for sys_id in step.systems:
                if sys_id not in known_system_ids:
                    diags.append(
                        Diagnostic(
                            code="DF002",
                            severity=Severity.WARNING,
                            message=(
                                f"Step '{step.id}': system '{sys_id}' is not defined "
                                "in the symbol table"
                            ),
                            process_id=proc.id,
                            step_id=step.id,
                            source_spans=step.source_spans,
                            evidence={"system_id": sys_id},
                            check_tier=CheckTier.DETERMINISTIC,
                        )
                    )

            # DF001 — artifact used before produced
            for art_id in step.inputs:
                if art_id in known_artifact_ids and art_id not in produced:
                    diags.append(
                        Diagnostic(
                            code="DF001",
                            severity=Severity.WARNING,
                            message=(
                                f"Step '{step.id}' consumes artifact '{art_id}' "
                                "before any earlier step produces it"
                            ),
                            process_id=proc.id,
                            step_id=step.id,
                            source_spans=step.source_spans,
                            evidence={"artifact_id": art_id},
                            check_tier=CheckTier.DETERMINISTIC,
                        )
                    )
                consumed.add(art_id)

            for art_id in step.outputs:
                produced.add(art_id)

        # DF003 — produced but never consumed in this process
        for art_id in produced - consumed:
            diags.append(
                Diagnostic(
                    code="DF003",
                    severity=Severity.INFO,
                    message=(
                        f"Artifact '{art_id}' is produced in process '{proc.name}' "
                        "but never consumed within the same process"
                    ),
                    process_id=proc.id,
                    evidence={"artifact_id": art_id},
                    check_tier=CheckTier.DETERMINISTIC,
                )
            )

    return diags
