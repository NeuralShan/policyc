"""Planted-bug recall: compile the bundled sample SOPs and score the findings against answer keys.

Each sample in ``backend/seed/samples/<id>/`` ships an ``expected.json`` listing the defects that
were deliberately planted (spec section 16 codes, E1xx/W2xx).  This script runs every sample
through a *running* backend (the real pipeline: Docling → Gemini → solver/simulator) and reports

* recall    – planted defects found / planted defects
* surplus   – findings with no planted counterpart (errors on the clean control are false positives)

Usage (backend must be running):

    python -m app.eval.planted --base http://127.0.0.1:8000 --out planted_report.json
    python -m app.eval.planted --ids expense,loto
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

SAMPLES = Path(__file__).resolve().parents[2] / "seed" / "samples"

# spec code -> finding codes that count as detecting it
CODE_MAP: dict[str, tuple[str, ...]] = {
    "E101": ("ST001",),
    "E102": ("ST004", "EX001"),
    "E103": ("ST005", "EX002"),
    "E104": ("RS004", "RS006"),
    "E105": ("ST003",),
    "E107": ("ST002",),
    "E108": ("ST008",),
    "W201": ("TM003", "LG001"),
    "W204": ("TM002",),
    "W207": ("XD001",),
}


def _call(base: str, method: str, path: str):
    req = urllib.request.Request(base + path, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310 - local dev URL
        return json.loads(resp.read() or b"null")


def score(expected: dict, findings: list[dict]) -> dict:
    planted: dict[str, int] = {}
    for p in expected.get("planted", []):
        planted[p["code"]] = planted.get(p["code"], 0) + 1
    found_by_code: dict[str, int] = {}
    for f in findings:
        found_by_code[f["code"]] = found_by_code.get(f["code"], 0) + 1

    detail, hits, total = [], 0, 0
    used: dict[str, int] = {}
    for code, n in sorted(planted.items()):
        accepted = CODE_MAP.get(code, ())
        available = sum(found_by_code.get(c, 0) for c in accepted)
        got = min(n, available)
        hits += got
        total += n
        for c in accepted:
            used[c] = used.get(c, 0) + found_by_code.get(c, 0)
        detail.append({"planted": code, "count": n, "found": got, "via": list(accepted)})
    explained = {c for codes in CODE_MAP.values() for c in codes}
    # only structural / solver / runtime codes can be false alarms; ownership and wording notes
    # (RS001, TM001, LG*, DF*) are advice rather than proofs and are not scored
    scored = {"ST001", "ST002", "ST003", "ST004", "ST005", "ST008", "RS004", "RS006", "TM002", "EX001",
              "EX002", "XD001"}
    surplus_err = [
        f["code"] for f in findings
        if f["severity"] == "error" and f["code"] in scored and (f["code"] not in explained or not planted)
    ]
    return {"recall": hits / total if total else 1.0, "hits": hits, "planted": total,
            "detail": detail, "surplus_error_codes": surplus_err}


def _post(base: str, path: str, body: dict):
    req = urllib.request.Request(
        base + path, method="POST", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310 - local dev URL
        return json.loads(resp.read() or b"null")


def run_one(base: str, sample_id: str, poll_s: int = 8, timeout_s: int = 900, replay: dict | None = None) -> dict:
    expected = json.loads((SAMPLES / sample_id / "expected.json").read_text(encoding="utf-8"))
    if replay is not None:
        # recompile the same document incrementally from an earlier run: model replies are replayed,
        # so only the deterministic stages (normaliser, checks, tests, findings) run again
        started = _post(
            base,
            f"/api/projects/{replay['project_id']}/runs",
            {"auto_approve": True, "base_run_id": replay["run_id"]},
        )
        started = {"run_id": started["id"], "project_id": started["project_id"]}
    else:
        started = _call(base, "POST", f"/api/samples/{sample_id}/run?live=true")
    run_id = started["run_id"]
    t0 = time.time()
    status = "running"
    while time.time() - t0 < timeout_s:
        run = _call(base, "GET", f"/api/runs/{run_id}")
        status = run["status"]
        if status in ("succeeded", "failed", "cancelled", "paused"):
            break
        time.sleep(poll_s)
    result = {"sample": sample_id, "run_id": run_id, "project_id": started["project_id"], "status": status,
              "seconds": round(time.time() - t0), "error": run.get("error")}
    if status == "succeeded":
        findings = _call(base, "GET", f"/api/runs/{run_id}/findings")["findings"]
        result["findings"] = [
            {"code": f["code"], "severity": f["severity"], "message": f["message"][:160],
             "clause": f.get("clause_ref")} for f in findings
        ]
        result["health"] = _call(base, "GET", f"/api/runs/{run_id}/health")
        result.update(score(expected, findings))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--ids", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--replay", default="", help="report JSON from an earlier pass: replay its runs without the model")
    args = ap.parse_args()
    previous = {}
    if args.replay:
        previous = {r["sample"]: r for r in json.loads(Path(args.replay).read_text(encoding="utf-8"))}
    ids = [i for i in args.ids.split(",") if i] or sorted(p.name for p in SAMPLES.iterdir() if p.is_dir())
    results = []
    for sid in ids:
        print(f"== {sid}", flush=True)
        res = run_one(args.base, sid, replay=previous.get(sid))
        results.append(res)
        print(
            f"   {res['status']} in {res['seconds']}s  recall={res.get('hits')}/{res.get('planted')}  "
            f"surplus errors={res.get('surplus_error_codes')}",
            flush=True,
        )
        if args.out:
            Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    done = [r for r in results if r["status"] == "succeeded"]
    hits = sum(r["hits"] for r in done)
    planted = sum(r["planted"] for r in done)
    print(f"\nOVERALL recall {hits}/{planted} = {hits / planted:.0%}" if planted else "\nno runs finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
