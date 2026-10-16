"""Layer 1 evaluation over the golden set: parse quality, span accuracy, golden quotes.

    uv run python -m app.eval.ingest_report                 # deterministic parse only, no LLM
    uv run python -m app.eval.ingest_report --llm           # full ingest incl. OCR check, profile
    uv run python -m app.eval.ingest_report --outline FILE  # print one document's node tree

Exit criteria checked: every golden document parses; span accuracy on PDF text layers >= 95%;
every golden-manifest quote is found in the parsed text.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

from app.api.documents import SOURCE_MEDIA_TYPES
from app.core.config import Settings
from app.core.db import run_migrations
from app.core.llm.gateway import CallContext
from app.core.services import Services
from app.eval.golden import GOLDEN_DIR, load_cases
from app.ingest.assemble import assemble
from app.ingest.service import ast_stats, get_ingestor
from app.ingest.span_check import check_spans
from app.models import Document
from app.schemas.docast import DocAST

SPAN_TARGET = 0.95


def golden_files(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SOURCE_MEDIA_TYPES and p.name != "README.md"
    )


def transient_document(services: Services, path: Path) -> Document:
    with path.open("rb") as f:
        stored = services.storage.put("golden", f, path.suffix.lower(), max_bytes=200 * 2**20)
    return Document(
        id=f"golden_{stored.sha256[:12]}",
        project_id="golden",
        filename=path.name,
        media_type=SOURCE_MEDIA_TYPES[path.suffix.lower()],
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        storage_key=stored.key,
    )


def ingest(services: Services, path: Path, use_llm: bool) -> DocAST:
    ingestor = get_ingestor(services)
    doc = transient_document(services, path)
    if use_llm:
        context = CallContext(stage="eval")
        return ingestor.ingest(doc, context, lambda msg: print(f"    {path.name}: {msg}"))
    return assemble(
        ingestor.parse(doc),
        document_id=doc.id,
        sha256=doc.sha256,
        filename=doc.filename,
        media_type=doc.media_type,
    )


def print_outline(ast: DocAST) -> None:
    depth: dict[str, int] = {}
    for n in ast.nodes:
        d = depth.get(n.parent_id, -1) + 1 if n.parent_id else 0
        depth[n.id] = d
        span = n.spans[0]
        where = f"p{span.page}" if span.page else ""
        tags = [n.kind.value]
        if n.level is not None:
            tags.append(f"L{n.level}")
        if n.number:
            tags.append(f"#{n.number}")
        if n.text_source != "native":
            tags.append(n.text_source.value)
        body = n.text.replace("\n", " / ")
        print(f"{'  ' * d}{n.id} [{' '.join(tags)}] {body[:100]} {where}")
        if n.alt_text:
            print(f"{'  ' * d}      (OCR read: {n.alt_text[:90]})")
        if n.figure and n.figure.diagram:
            g = n.figure.diagram
            print(
                f"{'  ' * d}      diagram: {len(g.nodes)} shapes, {len(g.edges)} arrows, "
                f"lanes {g.lanes}"
            )
    for w in ast.warnings:
        print(f"  warning {w.code}: {w.message}")
    if ast.profile:
        p = ast.profile
        meta = {
            k: getattr(p, k).value
            for k in ("title", "document_code", "version", "effective_date", "owner")
            if getattr(p, k)
        }
        print(f"  profile: {p.doc_class} ({p.rationale}) {meta}")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("paths", nargs="*", type=Path, help="files (default: the golden set)")
    parser.add_argument("--llm", action="store_true", help="run OCR cross-check, diagrams, profile")
    parser.add_argument("--outline", action="store_true", help="print each document's node tree")
    args = parser.parse_args(argv[1:])

    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(settings.resolved_database_url)
    services = Services.build(settings)
    files = args.paths or golden_files(GOLDEN_DIR)
    asts: dict[str, DocAST] = {}
    failures = 0

    print(
        f"{'document':<62} {'pages':>5} {'nodes':>5} {'tbl':>4} {'fig':>4} {'ocr':>4} "
        f"{'spans':>12}  class"
    )
    for path in files:
        try:
            ast = ingest(services, path, args.llm)
        except Exception as exc:
            failures += 1
            print(f"{path.name:<62} FAILED: {type(exc).__name__}: {exc}")
            continue
        asts[path.name] = ast
        stats = ast_stats(ast)
        span_col = "-"
        if ast.media_type == "application/pdf" and stats["ocr_pages"] < stats["pages"]:
            report = check_spans(
                ast, services.storage.path(transient_document(services, path).storage_key)
            )
            span_col = f"{report.ok}/{report.checked} {report.accuracy:.0%}"
            if report.accuracy < SPAN_TARGET:
                failures += 1
                for f in report.failures[:5]:
                    print(
                        f"    span {f.node_id} p{f.page} score {f.score}: {f.expected[:60]!r}"
                        f" vs {f.found[:60]!r}"
                    )
        print(
            f"{path.name[:62]:<62} {stats['pages']:>5} {stats['nodes']:>5} {stats['tables']:>4}"
            f" {stats['figures']:>4} {stats['ocr_pages']:>4} {span_col:>12}  "
            f"{stats['doc_class'] or '-'}"
        )
        if args.outline:
            print_outline(ast)

    for case in load_cases(GOLDEN_DIR):
        for i, finding in enumerate(case.manifest.expected_findings, start=1):
            ast = asts.get(finding.document or "")
            if finding.quote and ast and _squash(finding.quote) not in _squash(ast.text):
                failures += 1
                print(f"quote missing: {case.manifest.id} #{i} {finding.code} {finding.quote!r}")

    shutil.rmtree(settings.storage_dir / "golden", ignore_errors=True)
    print("OK" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
