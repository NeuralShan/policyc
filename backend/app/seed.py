"""Bundled demo data: precomputed runs for the sample SOPs.

Hugging Face Spaces (and any container) start with an empty database and an ephemeral disk, and
the free Gemini tier can run out of quota during a live demo.  ``backend/seed/seed.json`` holds the
finished sample runs (documents, parsed ASTs, IR, diagnostics, tests, findings, plus the LLM and
parse caches), so a fresh deployment opens with real, complete results and a "recompile" of a
sample is instant.  Seeded projects have ``owner_uid = NULL``: public and read-only.

Export from a developer database with ``python -m scripts.export_seed``.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from app.core.config import BACKEND_DIR
from app.core.services import Services
from app.core.db import Base
from app import models  # noqa: F401  (registers the tables on Base.metadata)

log = logging.getLogger(__name__)

SEED_DIR = BACKEND_DIR / "seed"
SEED_FILE = SEED_DIR / "seed.json"
_CHUNK = 200


def _is_datetime(col: sa.Column) -> bool:
    # UTCDateTime is a TypeDecorator whose python_type is `object`; check the implementation type
    impl = getattr(col.type, "impl", col.type)
    return isinstance(col.type, sa.DateTime) or isinstance(impl, sa.DateTime)


def _revive(table: sa.Table, row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        col = table.c.get(key)
        if value is not None and col is not None and isinstance(value, str) and _is_datetime(col):
            value = datetime.fromisoformat(value)
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
        out[key] = value
    return out


def load_seed(services: Services) -> int:
    """Insert the bundled demo projects if they are not present yet. Returns projects added."""
    if not services.settings.seed_demo or not SEED_FILE.is_file():
        return 0
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    project_ids: list[str] = data.get("project_ids", [])
    tables = {t.name: t for t in Base.metadata.sorted_tables}

    with services.engine.begin() as conn:
        present = set(
            conn.execute(sa.select(tables["projects"].c.id).where(tables["projects"].c.id.in_(project_ids))).scalars()
        )
        missing = [p for p in project_ids if p not in present]
        if not missing:
            return 0
        for name in [t.name for t in Base.metadata.sorted_tables]:
            rows = data["tables"].get(name)
            if not rows:
                continue
            table = tables[name]
            keep = [r for r in rows if _belongs(name, r, missing, data)]
            for i in range(0, len(keep), _CHUNK):
                batch = [_revive(table, r) for r in keep[i : i + _CHUNK]]
                if name in ("llm_cache", "parse_cache"):
                    # caches are shared: skip rows that already exist
                    pk = list(table.primary_key.columns)[0]
                    existing = set(conn.execute(sa.select(pk).where(pk.in_([b[pk.name] for b in batch]))).scalars())
                    batch = [b for b in batch if b[pk.name] not in existing]
                if batch:
                    conn.execute(table.insert(), batch)

    root = services.storage.root
    files = SEED_DIR / "files"
    if files.is_dir():
        for src in files.rglob("*"):
            if src.is_file():
                dst = root / src.relative_to(files)
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
    log.info("seed: loaded %d demo project(s)", len(missing))
    return len(missing)


def _belongs(table: str, row: dict[str, Any], projects: list[str], data: dict[str, Any]) -> bool:
    if table in ("llm_cache", "parse_cache"):
        return True
    if table == "projects":
        return row["id"] in projects
    if "project_id" in row:
        return row["project_id"] in projects
    runs = {r["id"] for r in data["tables"].get("compile_runs", []) if r["project_id"] in projects}
    docs = {r["id"] for r in data["tables"].get("documents", []) if r["project_id"] in projects}
    if "run_id" in row and row["run_id"] is not None:
        return row["run_id"] in runs
    if "document_id" in row:
        return row["document_id"] in docs
    return False
