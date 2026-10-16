"""The compile pipeline's stages, in execution order.

Each stage maps to one layer of the build plan. A stage is ``implemented`` once its layer replaces
the stub handler; the UI shows stubs explicitly so it's always clear what a run actually did.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StageSpec:
    key: str
    label: str
    layer: int
    compiler_analogy: str
    description: str


STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        "ingest",
        "Ingestion",
        1,
        "Lexer",
        "Parse documents into a DocAST with page and bounding-box source spans",
    ),
    StageSpec(
        "extract",
        "Semantic extraction",
        2,
        "Parser",
        "Extract the SOP IR (steps, roles, decisions, SLAs) with provenance",
    ),
    StageSpec(
        "link",
        "Linking & graph",
        3,
        "Linker",
        "Resolve entities across documents and emit the knowledge graph (.cypher)",
    ),
    StageSpec(
        "analyze",
        "Static analysis",
        4,
        "Type checker",
        "Deterministic structure, responsibility, data-flow and timing checks",
    ),
    StageSpec(
        "codegen",
        "Executable model",
        5,
        "Code generation",
        "Compile the IR into a four-valued process simulator",
    ),
    StageSpec(
        "testgen",
        "Test generation",
        6,
        "Test suite",
        "Deterministic, solver, fault-injection, realistic and adversarial tests",
    ),
    StageSpec(
        "execute",
        "Execution & oracle",
        7,
        "Runtime",
        "Run tests on the model, apply the oracle, measure coverage",
    ),
    StageSpec(
        "reality",
        "Reality check",
        8,
        "Profiler",
        "Replay real case history against the SOP (conformance checking)",
    ),
    StageSpec(
        "findings",
        "Findings",
        9,
        "Diagnostics",
        "Cluster, score and report gaps with suggested fixes",
    ),
)

STAGE_KEYS = tuple(s.key for s in STAGES)
