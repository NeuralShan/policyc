"""Incremental recompile of a revision, and aborting when a section cannot be extracted."""

import pytest

from app.core.llm.gateway import CallContext
from app.extract.service import Extractor
from app.extract.structure import StructureReply
from app.schemas.docast import DocAST, DocNode, NodeKind
from app.schemas.provenance import SourceSpan
from tests.fakes import default_responder, fake_factory

TEXT = """\
1 Purpose
1.1 This procedure sets out how claims are handled.
3 Submission
3.1 The requester submits the claim.
4 Approval
4.1 Claims below INR 10,000 are approved by the line manager.
"""


def _ast(text: str, filename: str = "SOP.pdf") -> DocAST:
    nodes, offset, parent = [], 0, None
    for i, line in enumerate(text.splitlines(), 1):
        number = line.split(" ", 1)[0]
        heading = line.count(".") == 0
        start = text.find(line, offset)
        offset = start + len(line)
        if heading:
            parent = f"n{i:04}"
        nodes.append(
            DocNode(
                id=f"n{i:04}",
                kind=NodeKind.HEADING if heading else NodeKind.PARAGRAPH,
                level=1 if heading else None,
                parent_id=None if heading else parent,
                number=number,
                text=line,
                spans=[SourceSpan(document_id="d", char_start=start, char_end=offset, quote=line)],
            )
        )
    return DocAST(document_id="d", sha256="x", filename=filename, media_type="application/pdf",
                  parser="t", text=text, nodes=nodes)


def _factory(calls: list[str], fail_sections: set[str] | None = None):
    def responder(schema, messages):
        if schema is StructureReply:
            user = str(messages[-1])
            section = "4" if "Claims below" in user or "up to" in user else "3"
            calls.append(section)
            if fail_sections and section in fail_sections:
                raise RuntimeError("quota exhausted")
            return schema(steps=[{"id": f"s{section}.1", "number": f"{section}.1", "action": "Do it",
                                  "actor_role_id": None, "source_quote": None}])
        return default_responder(schema, messages)

    return fake_factory(responder)


@pytest.fixture
def make_services(settings):
    from app.core.db import run_migrations
    from app.core.services import Services

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(settings.resolved_database_url)
    built: list = []

    def factory(calls, fail=None):
        s = Services.build(settings, _factory(calls, fail))
        built.append(s)
        return s

    yield factory
    for s in built:
        s.engine.dispose()


def test_revision_replays_unchanged_sections_and_reasks_only_the_edited_one(make_services):
    calls: list[str] = []
    services = make_services(calls)
    ex = Extractor(services)
    base = ex.extract([_ast(TEXT)], "run_a", CallContext())
    assert sorted(calls) == ["3", "4"] and set(base.raw_sections["SOP"]) == {"Section 3", "Section 4"}

    calls.clear()
    edited = TEXT.replace("below INR 10,000", "up to INR 10,000")
    rev = ex.extract([_ast(edited, "SOP_rev1.txt")], "run_b", CallContext(), base_ir=base)
    assert calls == ["4"], "only the edited section goes back to the model"
    assert {s.number for s in rev.processes[0].steps} == {"3.1", "4.1"}
    assert rev.symbols == base.symbols  # symbols reused, not re-asked


def test_failed_section_is_reported_as_a_structure_pass_failure(make_services):
    calls: list[str] = []
    services = make_services(calls, fail={"4"})
    ir = Extractor(services).extract([_ast(TEXT)], "run_c", CallContext())
    failed = [w for w in ir.warnings if w.code == "structure_pass_failed"]
    assert len(failed) == 1 and "Section 4" in failed[0].message
