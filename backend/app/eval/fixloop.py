"""Run the whole fix loop on the bundled samples: explain → accept patch → recompile → regression.

Why: (1) it proves the loop end to end against a running backend; (2) every Gemini answer it needs
(explanation, re-extraction of the edited section) lands in the LLM response cache, and
``scripts/export_seed.py`` bundles that cache, so on demo day "Explain & fix → Accept" answers
instantly and works even when the free-tier quota is gone.

    python -m app.eval.fixloop --base http://127.0.0.1:8000 --ids expense,loto,account
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

SEED = Path(__file__).resolve().parents[2] / "seed"
PREFER = ("ST004", "ST005", "ST008", "RS004", "TM002", "ST002", "ST001")


def _call(base: str, method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        base + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310 - local dev URL
        return json.loads(resp.read() or b"null")


def fix_one(base: str, run_id: str, max_findings: int = 3) -> dict:
    findings = _call(base, "GET", f"/api/runs/{run_id}/findings")["findings"]
    ranked = sorted(
        (f for f in findings if f["severity"] == "error" and f["code"] in PREFER),
        key=lambda f: PREFER.index(f["code"]),
    )
    out: dict = {"base_run": run_id, "tried": []}
    for finding in ranked[:max_findings]:
        explain = _call(base, "POST", f"/api/runs/{run_id}/findings/{finding['id']}/explain")
        entry = {"code": finding["code"], "clause": finding.get("clause_ref"), "patches": len(explain["patches"]),
                 "source": explain["source"]}
        out["tried"].append(entry)
        if not explain["patches"]:
            continue
        applied = _call(
            base,
            "POST",
            f"/api/runs/{run_id}/apply-patches",
            {"patches": [{"original_text": p["original_text"], "new_text": p["new_text"]} for p in explain["patches"]]},
        )
        new_run = applied["run_id"]
        deadline = time.time() + 900
        status = "running"
        while time.time() < deadline:
            status = _call(base, "GET", f"/api/runs/{new_run}")["status"]
            if status in ("succeeded", "failed", "paused"):
                break
            time.sleep(6)
        out.update(new_run=new_run, status=status)
        if status == "succeeded":
            out["regression"] = _call(base, "GET", f"/api/runs/{new_run}/regression?base={run_id}")
        return out
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--ids", default="expense,loto,account")
    args = ap.parse_args()
    manifest = json.loads((SEED / "manifest.json").read_text(encoding="utf-8"))
    for sid in [i for i in args.ids.split(",") if i]:
        res = fix_one(args.base, manifest[sid]["run_id"])
        reg = res.get("regression")
        print(f"== {sid}: {res.get('status', 'no patch')}", flush=True)
        for t in res["tried"]:
            print(f"   tried {t['code']} {t['clause']}: {t['patches']} patch(es) via {t['source']}", flush=True)
        if reg:
            print(f"   {reg['counts']['fixed']} fixed · {reg['counts']['new']} new · {reg['counts']['remaining']} remaining "
                  f"(health {reg['health']['before']} → {reg['health']['after']})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
