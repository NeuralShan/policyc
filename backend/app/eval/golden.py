"""Golden set: SME-annotated documents with the gaps the compiler is expected to find.

Each case is a directory containing ``manifest.json`` (see ``golden/README.md``). Later layers
score themselves against these annotations; this module loads and validates them.

    uv run python -m app.eval.golden            # validates ../golden
    uv run python -m app.eval.golden PATH
"""

import csv
import re
import sys
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import BACKEND_DIR
from app.schemas.taxonomy import TAXONOMY

GOLDEN_DIR = BACKEND_DIR.parent / "golden"
TEXT_SUFFIXES = {".md", ".txt", ".html", ".htm"}


def _known_code(code: str) -> str:
    if code not in TAXONOMY:
        raise ValueError(f"unknown gap code {code!r}")
    return code


class ExpectedFinding(BaseModel):
    code: str
    document: str | None = None
    quote: str | None = Field(default=None, min_length=1)
    note: str = ""
    accept_codes: list[str] = Field(
        default_factory=list, description="Other codes that also count as catching this gap"
    )
    cases: list[str] = Field(default_factory=list, description="Case-history case ids as evidence")

    _check_code = field_validator("code")(_known_code)

    @field_validator("accept_codes")
    @classmethod
    def _check_accept(cls, codes: list[str]) -> list[str]:
        return [_known_code(c) for c in codes]

    @model_validator(mode="after")
    def _anchored(self) -> "ExpectedFinding":
        if (self.quote is None) != (self.document is None):
            raise ValueError("quote and document must be given together")
        if self.quote is None and not self.cases:
            raise ValueError("needs a document quote, case ids, or both")
        return self


class GoldenManifest(BaseModel):
    id: str
    title: str
    synthetic: bool = False
    documents: list[str] = Field(min_length=1)
    context_packs: dict[str, str] = Field(default_factory=dict)
    case_history: list[str] = Field(default_factory=list)
    expected_findings: list[ExpectedFinding]


class GoldenCase(BaseModel):
    root: Path
    manifest: GoldenManifest


class Problem(BaseModel):
    case_id: str
    level: str  # "error" | "warning"
    message: str


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_cases(root: Path = GOLDEN_DIR) -> list[GoldenCase]:
    return [
        GoldenCase(
            root=path.parent,
            manifest=GoldenManifest.model_validate_json(path.read_text(encoding="utf-8")),
        )
        for path in sorted(root.rglob("manifest.json"))
    ]


def validate_case(case: GoldenCase) -> list[Problem]:
    m = case.manifest
    problems: list[Problem] = []

    def problem(level: str, message: str) -> None:
        problems.append(Problem(case_id=m.id, level=level, message=message))

    texts: dict[str, str] = {}
    for name in m.documents:
        path = case.root / name
        if not path.is_file():
            problem("error", f"document missing: {name}")
        elif path.suffix.lower() in TEXT_SUFFIXES:
            texts[name] = _normalise(path.read_text(encoding="utf-8"))
    for name in [*m.context_packs.values(), *m.case_history]:
        if not (case.root / name).is_file():
            problem("error", f"file missing: {name}")

    case_ids: set[str] = set()
    for name in m.case_history:
        path = case.root / name
        if path.is_file():
            with path.open(encoding="utf-8", newline="") as f:
                case_ids |= {row["case_id"] for row in csv.DictReader(f)}

    for i, finding in enumerate(m.expected_findings, start=1):
        where = f"finding #{i} ({finding.code})"
        if finding.document is not None:
            if finding.document not in m.documents:
                problem("error", f"{where}: document {finding.document!r} not in manifest")
            elif finding.document in texts:
                if _normalise(finding.quote) not in texts[finding.document]:
                    problem("error", f"{where}: quote not found verbatim in {finding.document}")
            else:
                problem("warning", f"{where}: quote checked by app.eval.ingest_report")
        for case_id in finding.cases:
            if case_id not in case_ids:
                problem("error", f"{where}: case {case_id} not found in case history")
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else GOLDEN_DIR
    cases = load_cases(root)
    if not cases:
        print(f"no golden cases (manifest.json) under {root}")
        return 1
    errors = 0
    for case in cases:
        m = case.manifest
        by_category: dict[str, int] = {}
        for f in m.expected_findings:
            by_category[f.code[:2]] = by_category.get(f.code[:2], 0) + 1
        label = " [synthetic]" if m.synthetic else ""
        counts = ", ".join(f"{k}:{v}" for k, v in sorted(by_category.items()))
        print(f"{m.id}{label}: {len(m.expected_findings)} expected findings ({counts})")
        for p in validate_case(case):
            errors += p.level == "error"
            print(f"  {p.level}: {p.message}")
    print("OK" if not errors else f"{errors} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
