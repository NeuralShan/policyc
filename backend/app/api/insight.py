"""Insight API: the pieces the workspace UI is built from.

flow         – the process as nodes/edges, annotated with the findings that touch each node
health       – one 0-100 score + grade for a run
explain      – plain-language explanation and minimal clause patches for one finding (Gemini)
apply-patches – write the accepted patches into a new document revision and compile it
regression   – fixed / new / remaining findings between two runs
report       – printable audit report (Markdown / HTML)
samples      – one-click demo documents (precomputed when bundled, live on request)
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import logging
import re
from pathlib import PurePath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import (
    CurrentUser,
    ExecutorDep,
    ServicesDep,
    SessionDep,
    assert_can_write,
    check_project_access,
    get_or_404,
)
from app.api.documents import SOURCE_MEDIA_TYPES, _latest_ast
from app.auth import User, get_current_user
from app.core.config import BACKEND_DIR
from app.core.llm.gateway import CallContext, LLMOutputError, LLMUnavailable
from app.extract.service import get_extractor
from app.findings.service import get_findings_service
from app.logic import describe_condition, display_value
from app.ingest.assemble import ParsedDocument, RawItem
from app.ingest.capabilities import full_parsing
from app.ingest.service import TEXT_PARSER
from app.models import CompileRun, Document, ParseCache, Project, RunStatus
from app.run.service import get_runner_service
from app.schemas.docast import DocAST
from app.schemas.findings import AggregatedFinding, FindingsReport, FindingTriage
from app.schemas.ir_sop import AlwaysCondition, SopIR, UnknownCondition

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["insight"])

SEED_DIR = BACKEND_DIR / "seed"
SAMPLES_DIR = SEED_DIR / "samples"
_DISMISSED = {FindingTriage.FALSE_POSITIVE, FindingTriage.WONT_FIX, FindingTriage.FIXED}


# ---------------------------------------------------------------------------
# access helpers: these POSTs only *read* a run, so demo runs stay usable for explain
# ---------------------------------------------------------------------------


def _read_run(
    run_id: str,
    session: SessionDep,
    user: Annotated[User, Depends(get_current_user)],
) -> CompileRun:
    run = get_or_404(session, CompileRun, run_id)
    check_project_access(user, get_or_404(session, Project, run.project_id), "GET")
    return run


ReadRun = Annotated[CompileRun, Depends(_read_run)]


def _load(services, run_id: str) -> tuple[SopIR | None, FindingsReport | None]:
    return get_extractor(services).load(run_id), get_findings_service(services).load(run_id)


def _active(report: FindingsReport | None) -> list[AggregatedFinding]:
    if report is None:
        return []
    return [f for f in report.findings if f.triage not in _DISMISSED]


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def compute_health(services, run_id: str, report: FindingsReport | None) -> dict[str, Any]:
    active = _active(report)
    errors = sum(1 for f in active if f.severity == "error")
    warnings = sum(1 for f in active if f.severity == "warning")
    infos = sum(1 for f in active if f.severity == "info")
    score = max(0, round(100 - 8 * errors - 3 * warnings - 0.5 * infos))
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"
    tests = {"total": 0, "passed": 0, "failed": 0}
    coverage = {"steps": 0.0, "decisions": 0.0, "branches": 0.0}
    run_report = get_runner_service(services).load(run_id)
    if run_report is not None:
        tests = {"total": run_report.total, "passed": run_report.passed, "failed": run_report.failed}
        cov = run_report.coverage
        coverage = {
            "steps": cov.step_coverage_pct,
            "decisions": cov.decision_coverage_pct,
            "branches": cov.branch_coverage_pct,
        }
    return {
        "score": score,
        "grade": grade,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "tests": tests,
        "coverage": coverage,
    }


@router.get("/runs/{run_id}/health")
def get_health(run: ReadRun, services: ServicesDep) -> dict[str, Any]:
    _, report = _load(services, run.id)
    return compute_health(services, run.id, report)


# ---------------------------------------------------------------------------
# flow
# ---------------------------------------------------------------------------

_SEV_RANK = {"error": 3, "warning": 2, "info": 1}


@router.get("/runs/{run_id}/flow")
def get_flow(run: ReadRun, services: ServicesDep) -> dict[str, Any]:
    ir, report = _load(services, run.id)
    if ir is None or not ir.processes:
        raise HTTPException(404, "No process model for this run yet")
    proc = ir.processes[0]
    role_names = {r.id: r.name for r in ir.symbols.roles}

    touched: dict[str, list[AggregatedFinding]] = {}
    for f in _active(report):
        for node_id in f.involved_node_ids or [x for x in (f.step_id, f.decision_id) if x]:
            touched.setdefault(node_id, []).append(f)

    def annotate(node: dict[str, Any]) -> dict[str, Any]:
        fs = touched.get(node["id"], [])
        sev = max((f.severity for f in fs), key=lambda s: _SEV_RANK.get(s, 0), default=None)
        node.update(
            severity=sev,
            finding_ids=[f.id for f in fs],
            codes=sorted({f.code for f in fs}),
        )
        return node

    nodes: list[dict[str, Any]] = []
    for s in proc.steps:
        span = s.source_spans[0] if s.source_spans else None
        nodes.append(
            annotate(
                {
                    "id": s.id,
                    "kind": "rule" if s.off_flow else ("terminal" if s.kind.value == "terminal" else "step"),
                    "label": s.action,
                    "number": s.number,
                    "actor": role_names.get(s.actor_role_id or "", None) or s.actor_raw,
                    "modal": s.modal.value if s.modal.value != "unknown" else None,
                    "quote": span.quote if span else None,
                    "char_start": span.char_start if span else None,
                    "char_end": span.char_end if span else None,
                    "document_id": span.document_id if span else None,
                    "inferred": s.inferred,
                }
            )
        )
    for d in proc.decisions:
        span = d.source_spans[0] if d.source_spans else None
        nodes.append(
            annotate(
                {
                    "id": d.id,
                    "kind": "decision",
                    "label": d.question,
                    "number": None,
                    "actor": None,
                    "modal": None,
                    "quote": span.quote if span else None,
                    "char_start": span.char_start if span else None,
                    "char_end": span.char_end if span else None,
                    "document_id": span.document_id if span else None,
                    "inferred": d.inferred,
                }
            )
        )

    edges: list[dict[str, Any]] = []
    ids = {n["id"] for n in nodes}
    uses_end = False

    def add_edge(src: str, dst: str, label: str | None, kind: str, inferred: bool) -> None:
        nonlocal uses_end
        if dst == "END":
            uses_end = True
        if src in ids and (dst in ids or dst == "END"):
            edges.append(
                {"id": f"e{len(edges)}", "source": src, "target": dst, "label": label, "kind": kind,
                 "inferred": inferred}
            )

    off = {s.id for s in proc.steps if s.off_flow}
    for t in proc.transitions:
        if t.from_id in off or t.to_id in off:
            continue
        add_edge(t.from_id, t.to_id, t.label if t.label and "inferred" not in t.label else None, "flow", t.inferred)
    for d in proc.decisions:
        if d.preceding_step_id and d.preceding_step_id not in off:
            add_edge(d.preceding_step_id, d.id, None, "flow", False)
        for b in d.branches:
            cond = b.condition
            label = (
                b.label
                if isinstance(cond, (AlwaysCondition, UnknownCondition))
                else describe_condition(cond)
            )
            add_edge(d.id, b.next_step_id, label, "branch", d.inferred)
    if uses_end:
        nodes.append(
            {"id": "END", "kind": "terminal", "label": "End of process", "number": None, "actor": None,
             "modal": None, "quote": None, "char_start": None, "char_end": None, "document_id": None,
             "severity": None, "finding_ids": [], "codes": [], "inferred": False}
        )
    return {
        "run_id": run.id,
        "process_id": proc.id,
        "entry": proc.entry(),
        "nodes": nodes,
        "edges": edges,
        "deadlines": [
            {"id": d.id, "description": d.description, "max_duration": d.max_duration, "unit": d.unit.value}
            for d in proc.deadlines
        ],
        "constraints": [
            {"id": c.id, "kind": c.kind.value, "description": c.description} for c in proc.constraints
        ],
    }


# ---------------------------------------------------------------------------
# explain & fix
# ---------------------------------------------------------------------------


class PatchOut(BaseModel):
    id: str
    clause_ref: str | None = None
    original_text: str
    new_text: str
    rationale: str = ""


class ExplainOut(BaseModel):
    finding_id: str
    plain_explanation: str
    impact: str
    patches: list[PatchOut]
    source: str = "gemini"  # "gemini" | "engine" (deterministic fallback)


class _PatchReply(BaseModel, extra="allow"):
    clause_ref: str | None = None
    original_text: str = ""
    new_text: str = ""
    rationale: str = ""


class _ExplainReply(BaseModel, extra="allow"):
    plain_explanation: str = ""
    impact: str = ""
    patches: list[_PatchReply] = Field(default_factory=list)


def _document_text(session, run: CompileRun) -> tuple[str, list[tuple[Document, DocAST]]]:
    docs: list[tuple[Document, DocAST]] = []
    for doc_id in run.document_ids:
        doc = session.get(Document, doc_id)
        rec = _latest_ast(session, doc_id) if doc else None
        if doc and rec:
            docs.append((doc, DocAST.model_validate(rec.ast)))
    return "\n\n".join(ast.text for _, ast in docs), docs


def _locate(text: str, original: str) -> str | None:
    """The exact substring of ``text`` that ``original`` refers to (tolerating whitespace)."""
    original = original.strip()
    if not original:
        return None
    if original in text:
        return original
    pattern = r"\s+".join(re.escape(part) for part in original.split())
    m = re.search(pattern, text)
    return m.group(0) if m else None


def _line_containing(text: str, needle: str) -> str | None:
    idx = text.find(needle)
    if idx < 0:
        return None
    start = text.rfind("\n", 0, idx) + 1
    end = text.find("\n", idx)
    return text[start : end if end >= 0 else len(text)].strip()


_STRICT_LOW = re.compile(r"\b(below|under|less\s+than)\s+((?:INR|Rs\.?|USD|\$|€|£|₹)?\s*)(\d[\d,]*)", re.I)


def _threshold_patch(finding: AggregatedFinding, text: str) -> PatchOut | None:
    """Deterministic fix for 'below X' + 'above X' gaps: make the lower band inclusive of X."""
    facts = finding.witness.get("facts") if finding.witness else None
    if finding.code not in ("ST004", "EX001") or not facts:
        return None
    for value in facts.values():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        digits = f"{int(value):,}"
        for m in _STRICT_LOW.finditer(text):
            if m.group(3).replace(",", "") != str(int(value)):
                continue
            line = _line_containing(text, m.group(0))
            if not line:
                continue
            cur = m.group(2).strip()
            inclusive = f"{(cur + ' ') if cur else ''}{digits} or below"
            new_line = line.replace(m.group(0), inclusive, 1)
            number = re.match(r"\s*(\d+(?:\.\d+)*)", line)
            return PatchOut(
                id="p1",
                clause_ref=number.group(1) if number else None,
                original_text=line,
                new_text=new_line,
                rationale=f"Makes the lower band include exactly {digits}, so no amount falls between the bands.",
            )
    return None


def _clause_context(ir: SopIR | None, finding: AggregatedFinding) -> str:
    quotes: list[str] = []
    if ir and ir.processes:
        proc = ir.processes[0]
        for node_id in finding.involved_node_ids or [x for x in (finding.step_id, finding.decision_id) if x]:
            st = proc.step(node_id)
            dec = proc.decision(node_id)
            spans = st.source_spans if st else (dec.source_spans if dec else [])
            quotes.extend(sp.quote for sp in spans[:1])
        for c in proc.constraints:
            if finding.code in ("RS004", "ST008", "RS006"):
                quotes.extend(sp.quote for sp in c.source_spans[:1])
    if finding.clause_quote:
        quotes.append(finding.clause_quote)
    uniq = list(dict.fromkeys(q for q in quotes if q))
    return "\n".join(f"- {q}" for q in uniq[:8]) or "(see document)"


def _witness_text(finding: AggregatedFinding) -> str:
    w = finding.witness or {}
    if w.get("facts"):
        return ", ".join(f"{k} = {display_value(v)}" for k, v in sorted(w["facts"].items()))
    if w.get("path"):
        return " → ".join(map(str, w["path"]))
    if w.get("breakdown"):
        return f"{w.get('path_hours')}h needed vs {w.get('allowed_hours')}h allowed: " + " + ".join(w["breakdown"])
    return finding.message


@router.post("/runs/{run_id}/findings/{finding_id}/explain")
def explain_finding(run: ReadRun, finding_id: str, services: ServicesDep, session: SessionDep) -> ExplainOut:
    ir, report = _load(services, run.id)
    finding = next((f for f in (report.findings if report else []) if f.id == finding_id), None)
    if finding is None:
        raise HTTPException(404, f"finding {finding_id} not found")
    text, docs = _document_text(session, run)
    filename = docs[0][0].filename if docs else "document"

    patches: list[PatchOut] = []
    explanation, impact, source = finding.message, "", "engine"
    try:
        reply = services.llm.structured(
            "explain_fix",
            _ExplainReply,
            {
                "filename": filename,
                "code": finding.code,
                "title": finding.title,
                "message": finding.message,
                "witness": _witness_text(finding),
                "suggested_fix": finding.suggested_fix or "(none)",
                "clauses": _clause_context(ir, finding),
                "document_text": text[:9000],
            },
            context=CallContext(run_id=run.id, stage="explain"),
        )
        explanation = reply.plain_explanation or explanation
        impact = reply.impact
        source = "gemini"
        for i, p in enumerate(reply.patches[:2], start=1):
            original = _locate(text, p.original_text)
            if original and p.new_text.strip() and p.new_text.strip() != original:
                patches.append(
                    PatchOut(
                        id=f"p{i}",
                        clause_ref=p.clause_ref,
                        original_text=original,
                        new_text=p.new_text.strip(),
                        rationale=p.rationale,
                    )
                )
    except (LLMUnavailable, LLMOutputError) as exc:
        log.warning("explain_fix unavailable: %s", exc)
    except Exception:
        log.exception("explain_fix failed")

    if not patches:
        fallback = _threshold_patch(finding, text)
        if fallback:
            patches.append(fallback)
            source = "engine" if source != "gemini" else source
    if not impact:
        impact = "People following this procedure may reach different or no outcomes in this situation."
    return ExplainOut(
        finding_id=finding.id,
        plain_explanation=explanation,
        impact=impact,
        patches=patches,
        source=source,
    )


# ---------------------------------------------------------------------------
# apply patches -> new revision
# ---------------------------------------------------------------------------


class PatchIn(BaseModel):
    original_text: str
    new_text: str


class ApplyPatches(BaseModel):
    patches: list[PatchIn] = Field(min_length=1)
    note: str | None = None


def _store_text_document(services, session, project: Project, filename: str, data: bytes) -> Document:
    suffix = PurePath(filename).suffix.lower()
    stored = services.storage.put(project.id, io.BytesIO(data), suffix, services.settings.max_upload_bytes)
    existing = session.scalar(
        select(Document).where(Document.project_id == project.id, Document.sha256 == stored.sha256)
    )
    if existing is not None:
        return existing
    doc = Document(
        project_id=project.id,
        filename=filename,
        media_type=SOURCE_MEDIA_TYPES[suffix],
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        storage_key=stored.key,
    )
    session.add(doc)
    session.flush()
    return doc


def _prime_parse_cache(session, document: Document, ast: DocAST, patches: list[PatchIn]) -> None:
    """Parse the revision as the *original* document, with only the patched clause text changed.

    Re-reading the patched text as plain text would lose the headings and clause structure (the
    text parser guesses headings from capitalisation), and a recompile would then compare a
    mangled model against the original. The revision keeps the original items, levels and numbers.
    """
    remaining = [(_locate(ast.text, p.original_text), p.new_text.strip()) for p in patches]
    items: list[RawItem] = []
    for node in ast.nodes:
        text = node.text
        for original, new in remaining:
            if original and original in text:
                text = text.replace(original, new, 1)
        items.append(
            RawItem(
                kind=node.kind,
                text=text,
                number=node.number,
                level=node.level,
                table=node.table,
                figure=node.figure,
            )
        )
    parsed = ParsedDocument(parser=TEXT_PARSER, items=items)
    key = hashlib.sha256(f"{document.sha256}|{TEXT_PARSER}".encode()).hexdigest()
    session.merge(
        ParseCache(key=key, sha256=document.sha256, parser=TEXT_PARSER, payload=parsed.model_dump(mode="json"))
    )


def _revision_name(filename: str) -> str:
    """``X.pdf`` -> ``X_rev1.txt``; ``X_rev1.txt`` -> ``X_rev2.txt``."""
    stem = PurePath(filename).stem
    m = re.search(r"_rev(\d+)$", stem)
    if m:
        return f"{stem[: m.start()]}_rev{int(m.group(1)) + 1}.txt"
    return f"{stem}_rev1.txt"


@router.post("/runs/{run_id}/apply-patches", status_code=202)
def apply_patches(
    run: ReadRun,
    body: ApplyPatches,
    request: Request,
    services: ServicesDep,
    session: SessionDep,
    executor: ExecutorDep,
    user: CurrentUser,
) -> dict[str, Any]:
    assert_can_write(user)
    project = get_or_404(session, Project, run.project_id)
    _, docs = _document_text(session, run)
    if not docs:
        raise HTTPException(409, "this run has no parsed document to patch")

    texts = {doc.id: ast.text for doc, ast in docs}
    applied = 0
    for p in body.patches:
        for doc_id, text in texts.items():
            original = _locate(text, p.original_text)
            if original:
                texts[doc_id] = text.replace(original, p.new_text.strip(), 1)
                applied += 1
                break
    if applied == 0:
        raise HTTPException(422, "none of the patches match the document text")

    # a demo (public) project is never modified: the revision goes into the user's own copy
    target = project
    if project.owner_uid is None and not user.open_access:
        target = Project(name=f"{project.name} (fixed)", description="", owner_uid=user.uid)
        session.add(target)
        session.flush()

    new_doc_ids: list[str] = []
    first_new: Document | None = None
    for doc, ast in docs:
        if texts[doc.id] != ast.text:
            new_doc = _store_text_document(
                services, session, target, _revision_name(doc.filename), texts[doc.id].encode("utf-8")
            )
            _prime_parse_cache(session, new_doc, ast, body.patches)
            new_doc_ids.append(new_doc.id)
            first_new = first_new or new_doc
        elif target.id == project.id:
            new_doc_ids.append(doc.id)
        else:
            clone = _store_text_document(services, session, target, f"{PurePath(doc.filename).stem}.txt",
                                         ast.text.encode("utf-8"))
            _prime_parse_cache(session, clone, ast, [])
            new_doc_ids.append(clone.id)

    new_run = CompileRun(
        project_id=target.id,
        document_ids=list(dict.fromkeys(new_doc_ids)),
        auto_approve=True,
        base_run_id=run.id,
        note=body.note or f"Applied {applied} fix{'es' if applied != 1 else ''}",
    )
    session.add(new_run)
    session.commit()
    executor.submit(new_run.id)
    return {
        "run_id": new_run.id,
        "base_run_id": run.id,
        "project_id": target.id,
        "document_id": first_new.id if first_new else None,
        "applied": applied,
    }


# ---------------------------------------------------------------------------
# regression
# ---------------------------------------------------------------------------


def _summary(f: AggregatedFinding) -> dict[str, Any]:
    return {
        "id": f.id,
        "code": f.code,
        "title": f.title,
        "severity": f.severity,
        "step_id": f.step_id,
        "decision_id": f.decision_id,
        "message": f.message,
        "clause_ref": f.clause_ref,
    }


@router.get("/runs/{run_id}/regression")
def get_regression(
    run: ReadRun, services: ServicesDep, session: SessionDep, base: str = Query(...)
) -> dict[str, Any]:
    base_run = get_or_404(session, CompileRun, base)
    if base_run.project_id != run.project_id and base_run.id != run.base_run_id:
        project = get_or_404(session, Project, base_run.project_id)
        # allow comparing a user's copy against the public run it came from
        if project.owner_uid is not None:
            raise HTTPException(404, "base run not found")
    new_report = get_findings_service(services).load(run.id)
    old_report = get_findings_service(services).load(base)
    if new_report is None or old_report is None:
        raise HTTPException(404, "findings are not ready for one of the runs")
    new_f, old_f = _active(new_report), _active(old_report)

    def key(f: AggregatedFinding) -> tuple[str, str]:
        return (f.code, f.clause_ref or f.step_id or f.decision_id or "")

    new_by_fp = {f.fingerprint: f for f in new_f}
    old_by_fp = {f.fingerprint: f for f in old_f}
    new_keys = {key(f) for f in new_f}
    old_keys = {key(f) for f in old_f}
    fixed = [f for f in old_f if f.fingerprint not in new_by_fp and key(f) not in new_keys]
    added = [f for f in new_f if f.fingerprint not in old_by_fp and key(f) not in old_keys]
    remaining = [f for f in new_f if f.fingerprint in old_by_fp or key(f) in old_keys]
    return {
        "base_run_id": base,
        "run_id": run.id,
        "counts": {"fixed": len(fixed), "new": len(added), "remaining": len(remaining)},
        "fixed": [_summary(f) for f in fixed],
        "new": [_summary(f) for f in added],
        "remaining": [_summary(f) for f in remaining],
        "health": {
            "before": compute_health(services, base, old_report)["score"],
            "after": compute_health(services, run.id, new_report)["score"],
        },
    }


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def _report_markdown(run: CompileRun, project: Project, health: dict, findings: list[AggregatedFinding]) -> str:
    lines = [
        f"# PolicyC verification report — {project.name}",
        "",
        f"Run `{run.id}` · health **{health['score']}/100 (grade {health['grade']})** · "
        f"{health['errors']} errors · {health['warnings']} warnings · "
        f"{health['tests']['passed']}/{health['tests']['total']} test scenarios passed",
        "",
        "_Gemini translated the document into a process model; a deterministic engine (graph search, "
        "Z3 solver, simulator) produced every finding below. Each carries a witness you can re-run._",
        "",
    ]
    for f in findings:
        lines += [f"## {f.code} · {f.title} ({f.severity})", ""]
        lines.append(f.message)
        if f.clause_ref:
            lines.append(f"\n**Clause {f.clause_ref}**" + (f": “{f.clause_quote}”" if f.clause_quote else ""))
        if f.witness:
            lines.append(f"\n**Witness:** {_witness_text(f)}")
        if f.reproduced_by_tests:
            lines.append(f"\n**Reproduced by {f.reproduced_by_tests} test scenario(s).**")
        if f.suggested_fix:
            lines.append(f"\n**Suggested fix:** {f.suggested_fix}")
        lines.append("")
    if not findings:
        lines.append("No open findings. ✔")
    return "\n".join(lines)


@router.get("/runs/{run_id}/report")
def get_report(run: ReadRun, services: ServicesDep, session: SessionDep, format: str = "md") -> Response:
    _, report = _load(services, run.id)
    if report is None:
        raise HTTPException(404, "No findings report for this run")
    project = get_or_404(session, Project, run.project_id)
    health = compute_health(services, run.id, report)
    md = _report_markdown(run, project, health, _active(report))
    if format == "html":
        body = html.escape(md)
        body = re.sub(r"^## (.+)$", r"<h2>\1</h2>", body, flags=re.M)
        body = re.sub(r"^# (.+)$", r"<h1>\1</h1>", body, flags=re.M)
        body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
        body = body.replace("\n\n", "<br><br>")
        page = (
            "<!doctype html><meta charset='utf-8'><title>PolicyC report</title>"
            "<style>body{font:15px/1.5 system-ui;max-width:780px;margin:2rem auto;padding:0 1rem}"
            "h2{margin-top:1.6rem;border-bottom:1px solid #ddd}@media print{body{margin:0}}</style>"
            f"<body>{body}</body>"
        )
        return Response(page, media_type="text/html")
    return PlainTextResponse(md, media_type="text/markdown")


# ---------------------------------------------------------------------------
# samples
# ---------------------------------------------------------------------------


def _sample_meta() -> list[dict[str, Any]]:
    metas = []
    if SAMPLES_DIR.is_dir():
        for path in sorted(SAMPLES_DIR.glob("*/meta.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            data["dir"] = path.parent.name
            metas.append(data)
    return metas


def _manifest() -> dict[str, Any]:
    path = SEED_DIR / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


@router.get("/samples")
def list_samples(session: SessionDep) -> list[dict[str, Any]]:
    manifest = _manifest()
    out = []
    for meta in _sample_meta():
        entry = manifest.get(meta["id"])
        cached = bool(entry and session.get(CompileRun, entry["run_id"]))
        out.append(
            {
                "id": meta["id"],
                "title": meta["title"],
                "description": meta.get("description", ""),
                "industry": meta.get("industry", ""),
                "language": meta.get("language", "en"),
                "planted_bugs": meta.get("planted_bugs", 0),
                "doc_code": meta.get("doc_code"),
                "precomputed": cached,
            }
        )
    return out


@router.post("/samples/{sample_id}/run", status_code=202)
def run_sample(
    sample_id: str,
    services: ServicesDep,
    session: SessionDep,
    executor: ExecutorDep,
    user: CurrentUser,
    live: bool = False,
) -> dict[str, Any]:
    meta = next((m for m in _sample_meta() if m["id"] == sample_id), None)
    if meta is None:
        raise HTTPException(404, f"unknown sample {sample_id}")
    entry = _manifest().get(sample_id)
    if not live and entry:
        run = session.get(CompileRun, entry["run_id"])
        if run is not None:
            return {"project_id": run.project_id, "run_id": run.id, "cached": True}

    assert_can_write(user)
    sample_dir = SAMPLES_DIR / meta["dir"]
    # lightweight deployments cannot read the PDF: use the text version of the same sample
    source = sample_dir / (
        meta.get("file", "sop.md") if full_parsing() else meta.get("text_file", "sop.md")
    )
    project = Project(
        name=f"{meta['title']} (live)",
        description=f"Sample: {meta.get('description', '')}",
        owner_uid=user.uid,
    )
    session.add(project)
    session.flush()
    doc = _store_text_document(services, session, project, source.name, source.read_bytes())
    run = CompileRun(project_id=project.id, document_ids=[doc.id], auto_approve=True,
                     note=f"Live compile of sample {sample_id}")
    session.add(run)
    session.commit()
    executor.submit(run.id)
    return {"project_id": project.id, "run_id": run.id, "cached": False}


__all__ = ["router", "compute_health", "RunStatus"]
