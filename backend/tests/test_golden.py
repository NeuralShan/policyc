import json

import pytest
from pydantic import ValidationError

from app.eval.golden import GOLDEN_DIR, load_cases, validate_case


def test_repository_golden_set_is_valid():
    cases = load_cases(GOLDEN_DIR)
    assert cases, "expected at least the synthetic sample case"
    for case in cases:
        errors = [p for p in validate_case(case) if p.level == "error"]
        assert errors == [], errors


def write_case(tmp_path, findings, sop="The agent logs the complaint promptly.\n"):
    (tmp_path / "sop.md").write_text(sop, encoding="utf-8")
    (tmp_path / "cases.csv").write_text("case_id,activity\nC-1,Log\n", encoding="utf-8")
    manifest = {
        "id": "t",
        "title": "t",
        "documents": ["sop.md"],
        "case_history": ["cases.csv"],
        "expected_findings": findings,
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return load_cases(tmp_path)[0]


def test_validator_flags_unverifiable_anchors(tmp_path):
    case = write_case(
        tmp_path,
        [
            {"code": "TM003", "document": "sop.md", "quote": "logs  the\ncomplaint promptly"},
            {"code": "TM003", "document": "sop.md", "quote": "within 2 days"},
            {"code": "RL001", "cases": ["C-404"]},
            {"code": "XD001", "document": "other.md", "quote": "x"},
        ],
    )
    messages = [p.message for p in validate_case(case)]
    assert messages == [
        "finding #2 (TM003): quote not found verbatim in sop.md",
        "finding #3 (RL001): case C-404 not found in case history",
        "finding #4 (XD001): document 'other.md' not in manifest",
    ]


@pytest.mark.parametrize(
    "finding",
    [
        {"code": "ZZ999", "document": "sop.md", "quote": "x"},
        {"code": "ST004", "document": "sop.md", "quote": "x", "accept_codes": ["NOPE1"]},
        {"code": "ST004", "quote": "x"},  # quote without document
        {"code": "ST004"},  # no anchor at all
    ],
)
def test_malformed_annotations_are_rejected(tmp_path, finding):
    with pytest.raises(ValidationError):
        write_case(tmp_path, [finding])
