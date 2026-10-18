"""Export finished sample runs from the developer database into backend/seed/seed.json.

    python scripts/export_seed.py planted_report.json

The report is the output of ``python -m app.eval.planted --out ...``: for each sample it names the
project and run that were compiled.  Only succeeded runs are exported.  Projects are renamed to the
sample title, set public (owner_uid NULL), and recorded in seed/manifest.json so the API can hand
out a precomputed run instantly.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: E402,F401
from app.core.config import Settings  # noqa: E402
from app.core.db import Base, make_engine  # noqa: E402

SEED_DIR = Path(__file__).resolve().parents[1] / "seed"
SKIP = {"llm_calls"}


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        raise TypeError("binary column in seed export")
    return value


def main(report_path: str) -> None:
    report = [r for r in json.loads(Path(report_path).read_text(encoding="utf-8")) if r["status"] == "succeeded"]
    settings = Settings()
    engine = make_engine(settings.resolved_database_url)
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    meta = {
        p.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in (SEED_DIR / "samples").glob("*/meta.json")
    }

    project_ids = [r["project_id"] for r in report]
    manifest = {r["sample"]: {"project_id": r["project_id"], "run_id": r["run_id"]} for r in report}
    out: dict[str, list[dict]] = {}
    with engine.connect() as conn:
        # Keep only the verified run per sample plus its newest *successful* fix revision. Test
        # compiles, failed runs and superseded revisions stay out of the demo.
        runs_t = tables["compile_runs"]
        selected: list[str] = []
        for r in report:
            selected.append(r["run_id"])
            rev = conn.execute(
                sa.select(runs_t.c.id)
                .where(runs_t.c.base_run_id == r["run_id"], runs_t.c.status == "succeeded")
                .order_by(runs_t.c.created_at.desc())
                .limit(1)
            ).scalar()
            if rev:
                selected.append(rev)
        kept_docs: set[str] = set()
        for row in conn.execute(sa.select(runs_t.c.document_ids).where(runs_t.c.id.in_(selected))).scalars():
            kept_docs.update(row)

        for t in Base.metadata.sorted_tables:
            if t.name in SKIP:
                continue
            cols = t.c.keys()
            if t.name == "projects":
                rows = conn.execute(sa.select(t).where(t.c.id.in_(project_ids))).mappings().all()
            elif t.name == "compile_runs":
                rows = conn.execute(sa.select(t).where(t.c.id.in_(selected))).mappings().all()
            elif t.name == "documents":
                rows = conn.execute(
                    sa.select(t).where(t.c.project_id.in_(project_ids), t.c.id.in_(kept_docs))
                ).mappings().all()
            elif "project_id" in cols:
                rows = conn.execute(sa.select(t).where(t.c.project_id.in_(project_ids))).mappings().all()
            elif t.name in ("llm_cache", "parse_cache"):
                rows = conn.execute(sa.select(t)).mappings().all()
            elif "run_id" in cols:
                rows = conn.execute(sa.select(t).where(t.c.run_id.in_(selected))).mappings().all()
            elif "document_id" in cols:
                rows = conn.execute(sa.select(t).where(t.c.document_id.in_(kept_docs))).mappings().all()
            else:
                continue
            out[t.name] = [{k: _jsonable(v) for k, v in dict(r).items()} for r in rows]

    by_project = {r["project_id"]: r["sample"] for r in report}
    for row in out["projects"]:
        sample = meta[by_project[row["id"]]]
        row["name"] = sample["title"]
        row["description"] = sample.get("description", "")
        row["owner_uid"] = None
    # compile_runs: public demo runs are already approved; keep their notes tidy
    chosen = {r["id"] for r in out.get("compile_runs", [])}
    for row in out.get("compile_runs", []):
        if row.get("base_run_id") not in chosen:  # its base (an internal test compile) is not shipped
            row["base_run_id"] = None
            row["note"] = "Precomputed demo run"

    files_root = settings.storage_dir
    files_out = SEED_DIR / "files"
    if files_out.exists():
        shutil.rmtree(files_out)
    keys: set[str] = {d["storage_key"] for d in out.get("documents", [])}
    blob = json.dumps(out.get("doc_asts", []))
    keys |= set(re.findall(r"figures/[A-Za-z0-9_.-]+\.png", blob))
    for key in keys:
        src = files_root / key
        if src.is_file():
            dst = files_out / key
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    (SEED_DIR / "seed.json").write_text(
        json.dumps({"project_ids": project_ids, "tables": out}, ensure_ascii=False), encoding="utf-8"
    )
    (SEED_DIR / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    size = (SEED_DIR / "seed.json").stat().st_size / 1024
    print(f"exported {len(project_ids)} projects, {sum(len(v) for v in out.values())} rows, seed.json {size:.0f} KB")


if __name__ == "__main__":
    main(sys.argv[1])
