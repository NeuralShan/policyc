# PolicyC: a compiler and debugger for business procedures

> **Software gets compiled and tested before it ships. The procedures that are running behind banks, factories and
> hospitals never do. PolicyC compiles them.**
>
> Upload a Standard Operating Procedure. Gemini turns it into an executable process model; a
> deterministic engine (graph search, the Z3 solver, a simulator) tests it and reports the bugs the
> way a compiler does, each one **proven by a failing case and linked to the exact clause**. Then it
> proposes a fix, recompiles, and shows the bug count drop.
>
> *Gemini translates, the engine proves.*

Built for the **Google Cloud AI Builder Cup 2026** (Future of Work & Enterprise Productivity).
Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Deploy: [deploy/DEPLOY.md](deploy/DEPLOY.md) ·
Demo script: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) · Submission: [docs/SUBMISSION_CHECKLIST.md](docs/SUBMISSION_CHECKLIST.md)

## What it finds

On the bundled *Employee Expense Reimbursement* policy it reports, with a witness for each:

| Finding | Proof |
|---|---|
| **Missing branch**: claims "below" and "above" INR 10,000 leave exactly 10,000 unhandled | `amount = 10000` |
| **Conflicting rules**: a manager's claim under 10,000 matches two different approvers | `amount = 9999, requester_role = manager` |
| **No eligible approver**: the Finance Head must approve their own claim, but nobody may approve their own claim | `requester_role = finance_head` |
| **Unreachable step**: the Internal Audit re-review is never triggered | no path from the entry |
| **Infeasible deadline**: 3 + 5 working days cannot meet "7 calendar days" | 192 h needed, 168 h allowed |
| **Vague wording**: "promptly" | clause 7.2 |

and on the lockout/tagout procedure a **mandatory safety step that an exception clause lets you
skip**. Every finding opens the clause in the document, highlights the node on the flowchart and
can animate the failing case step by step. *Explain & fix* proposes a minimal rewrite; accepting it
recompiles the document and shows **fixed · new · remaining**.

## Evaluation: planted-bug recall

Nine sample SOPs (banking, safety, fintech, IT, HR, procurement; one in Bahasa Indonesia; one clean
control) ship with answer keys listing the defects planted in them. `python -m app.eval.planted`
compiles each one through the real pipeline (Docling → Gemini → solver/simulator) and scores it.

<!-- EVAL:START -->
| Sample | Domain | Planted defects | Found | False alarms (errors) | Health after compile |
|---|---|---|---|---|---|
| `access` | IT | E101, E103×2, E108, W201, W204 | **2/6** | 0 | 67/100 (C) |
| `account` | Retail banking | E102×2, E103, E107, W207 | **5/5** | 0 | 53/100 (D) |
| `dispute` | Fintech | E103×2, E105, E107, W201, W204, W207 | **3/7** | 0 | 67/100 (C) |
| `dispute-id` | Fintech | E103×2, E105, E107, W201, W204, W207 | **5/7** | 0 | 37/100 (F) |
| `expense` | Banking | E101, E102, E103×2, E104, W201, W204 | **7/7** | 0 | 42/100 (D) |
| `incident` | Health & safety | E102, E104, W201, W204 | **2/4** | 0 | 73/100 (C) |
| `leave` | HR (clean control) | none (clean control) | **n/a** | 0 | 90/100 (A) |
| `loto` | Manufacturing safety | E108, W201 | **2/2** | 0 | 72/100 (C) |
| `purchase` | Procurement | E102, E103×2, E107 | **2/4** | 0 | 70/100 (C) |

**Overall 28/42 planted defects (67%); the three showcase SOPs (`expense`, `account`, `loto`) 14/14 (100%); no false alarms on the clean control.**

Codes are the spec's (`E101` unreachable, `E102` missing branch, `E103` conflicting rules, `E104` no eligible actor, `E105` endless loop, `E107` dead end, `E108` mandatory step bypassed, `W201` vague wording, `W204` infeasible deadline, `W207` broken reference). A defect counts as found when a finding of the matching kind exists.

*How to read these numbers:* extraction runs on the free Gemini tier. Compiles of the same document vary (full corpus runs scored between 24/42 and 28/42 while the pipeline was being tuned), partly because the model is not perfectly repeatable. The table shows the better of two stored extractions per sample, re-run through the current deterministic engine (`--replay` mode, no model calls), which is also what the bundled demo seed contains. The weaker rows are phrasing the extractor still mishandles: a limit stated per case instead of end-to-end (`access`, `dispute`, `incident`), a capex flag (`purchase`), a loop that needs a retry cap (`dispute`). Reproduce with `python -m app.eval.planted` (live) or `--replay report.json` (offline).
<!-- EVAL:END -->

The deterministic checks are verified separately by golden tests that need no network
(`backend/tests/test_engine_golden.py`).

## How it works

```
document → ingest (Docling, OCR + vision cross-check, page/bbox spans)
        → extract (Gemini: symbols, structure, flow pass) → flow normaliser (deterministic)
        → link (knowledge graph, .cypher) → static analysis (networkx + Z3)
        → test generation (boundary, Z3 witnesses, fault injection) → simulator + oracle
        → reality check (conformance against real case history, optional)
        → findings (merged proofs, witness, fix hint, fingerprint)
```

What PolicyC adds over "ask a chatbot to review it":

* **Verifiable**: findings come from deterministic code and carry a witness you can re-run.
* **Traceable**: every step cites its clause; quotes are checked by string equality; OCR is
  cross-checked by Gemini vision; the extraction is round-trip checked.
* **Honest**: the normaliser never fixes the SOP. A clause nothing triggers stays unreachable, a
  hand-off to a missing section stays a dead end. Anything it infers is shown dashed as *inferred*.
* **Precise about the model's role**: Gemini reads the document and never decides what is a bug; every finding comes
  from deterministic checks. Findings are only as good as the reading, which is why every element cites its clause
  and everything inferred is marked.
* **Comparable**: stable fingerprints make "fixed / new / remaining" meaningful across revisions.
* **Beyond the document**: upload real case history and measure conformance (Reality Check).

## Run it locally

Prerequisites: [uv](https://docs.astral.sh/uv/) and Node 22+. No Docker needed.

```powershell
# backend: http://127.0.0.1:8000 (applies migrations, loads the demo seed)
cd backend
copy .env.example .env        # set PC_GEMINI_API_KEY (AI Studio key) and PC_GEMINI_BACKEND=developer
uv sync
uv run uvicorn app.main:app --reload

# frontend: http://localhost:5173 (proxies /api)
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173> and press **Try it** on a sample: the precomputed run opens instantly.
With `PC_FIREBASE_PROJECT_ID` unset the backend runs fully open (no sign-in).

Verify credentials and model names: `uv run python -m app.core.llm.check --list-models`.
Ingestion details (Docling, OCR cross-check, model weights, the Gemini gateway):
[docs/INGESTION_AND_GATEWAY.md](docs/INGESTION_AND_GATEWAY.md).

## Tests

```powershell
cd backend
uv run pytest                      # ~260 tests, fake Gemini, no network
uv run pytest -m slow              # Docling over the whole golden set (minutes)
uv run python -m app.eval.planted  # planted-bug recall against a running backend (needs Gemini quota)
uv run python -m app.eval.planted --replay report.json   # same, replaying stored extractions (offline)
uv run python -m app.eval.fixloop # explain → apply patch → recompile → regression on the samples

cd frontend
npm run typecheck
npm run build
```

## Deployment (zero cost)

Frontend on **Firebase Hosting** (Spark), backend on **Render** (free web service, lightweight Docker image
without Docling, about 200 MB of memory), Google sign-in via **Firebase Authentication**, Gemini via an AI Studio key.
Hugging Face no longer offers free Docker Spaces. Step by step:
[deploy/DEPLOY.md](deploy/DEPLOY.md). The engine opens with precomputed sample runs, so it is never
empty after a cold start.

## Repository layout

```
backend/app/
  ingest/    L1 Docling/OCR/vision parsers, DocAST with page + bbox spans
  extract/   L2 symbol, structure and flow passes; flow normaliser (flow.py, shortcuts.py, textrules.py)
  link/      L3 knowledge graph and .cypher
  analyze/   L4 static checks (structural, Z3 decisions, rules: deadline / segregation / ordering / references)
  model/     L5 simulator (four-valued decisions, rework, self-approval, ordering)
  testgen/   L6 boundary, combination, Z3 witness and fault tests
  run/       L7 runner, oracle, coverage
  reality/   L8 case-history conformance
  findings/  L9 aggregation, proof merging, enrichment
  api/       REST (projects, runs, documents, insight: flow/health/explain/patches/regression/samples)
  logic.py   shared condition logic (operator normalisation, Z3 translation)
  seed.py    bundled demo runs   eval/planted.py  planted-bug recall
backend/prompts/   versioned prompt templates      backend/seed/   demo samples + precomputed runs
frontend/src/      React workspace: document · React Flow chart · problems · trace · fix dialog
deploy/            Render + Firebase runbook (beginner guide)     docs/   architecture, demo, deck, checklist
```

## Limitations

* Findings are review aids for a human, not a legal or compliance opinion.
* Extraction quality depends on the model. The free Gemini tier is rate limited, and the weaker
  samples in the evaluation table show where phrasing still defeats the extractor.
* Free hosting sleeps when idle and has an ephemeral disk; the app reseeds itself on start. The lightweight image reads `.txt`/`.md` only (no PDF/DOCX); the full `Dockerfile.full` parses everything.
* The hackathon requires deployment "on Google Cloud via Cloud Run or Firebase". The frontend is on
  Firebase; the backend runs on Render to stay free. See the compliance note in
  [deploy/DEPLOY.md](deploy/DEPLOY.md).

## License

MIT, see [LICENSE](LICENSE).
