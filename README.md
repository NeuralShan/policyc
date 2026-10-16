# Policy Compiler (`policyc`)

Compiles organisational documents (SOPs first; policies and playbooks later) the way a compiler
compiles code:

1. Parse them into an executable intermediate representation and a knowledge graph.
2. Run them against deterministic, solver-generated, realistic and **real historical** cases.
3. Report the gaps as numbered diagnostics with the source clause, a counterexample and a suggested fix.

It verifies documents; it does not summarise them.

## Status

| Layer | Stage | Compiler analogy | Status |
|---|---|---|---|
| 0 | Foundations: API, storage, Gemini gateway, LangGraph pipeline, web shell, golden set | — | **done** |
| 1 | Ingestion: DocAST with page and bounding-box spans | Lexer | **done** |
| 2 | Semantic extraction: SOP IR | Parser | stub |
| 3 | Linking & knowledge graph (`.cypher`) | Linker | stub |
| 4 | Static analysis | Type checker | stub |
| 5 | Executable model | Code generation | stub |
| 6 | Test generation | Test suite | stub |
| 7 | Execution & oracle | Runtime | stub |
| 8 | Reality check (case-history conformance) | Profiler | stub |
| 9 | Findings, scoring, remediation | Diagnostics | stub |

Stub stages still run, and the UI labels them **stub**, so every run shows what was actually done.

## Run it

Prerequisites: [uv](https://docs.astral.sh/uv/) and Node 22+. No Docker needed. Python
dependencies live in `backend/.venv` and npm packages in `frontend/node_modules`; nothing is installed
globally.

```powershell
# backend: http://127.0.0.1:8000  (applies DB migrations on startup)
cd backend
uv sync
uv run uvicorn app.main:app --reload

# frontend: http://localhost:5173  (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

After `npm run build`, the backend serves the built UI itself at http://127.0.0.1:8000.

### Gemini

Copy `backend/.env.example` to `backend/.env` and set your Vertex AI project, or an API key. Then
verify the credentials and model names:

```powershell
cd backend
uv run python -m app.core.llm.check --list-models
uv run python -m app.core.llm.check
```

Every LLM call goes through `app/core/llm/gateway.py`. It handles:

- tier routing (pro / flash / lite),
- temperature 0 and a fixed seed,
- schema-validated output, optionally with images,
- a response cache keyed by model, prompt content, inputs, images and schema,
- a per-model throttle (`PC_LLM_MAX_RPM`),
- failing fast once a daily quota is exhausted,
- token logging per run and stage.

## Layer 1: ingestion

Each uploaded document becomes a **DocAST** (`app/schemas/docast.py`): a section tree of titles,
headings, paragraphs, list items, tables and figures. Every node carries:

- its clause number as printed (`4.3`, `(2)`, `a)`),
- its source spans. Each span is a character range in the DocAST's canonical text plus a page and
  bounding box. `ast.text[span.char_start:span.char_end] == span.quote` always holds, so later
  layers can verify any quote by plain string comparison.

The parsing pipeline:

| Input | How it's read |
|---|---|
| PDF, DOCX, HTML, Markdown | [Docling](https://github.com/docling-project/docling): layout, reading order, tables with header cells, figures, heading levels |
| Plain text | Own parser (`app/ingest/text_parser.py`) |
| Scanned PDF pages | Local OCR (RapidOCR), **then an independent Gemini vision reading** aligned line by line. Agreement marks a node `ocr_verified`. A disagreement uses the vision text, keeps the OCR reading as `alt_text`, and adds a warning for review. Local OCR silently garbled the energy-isolation step of the scanned lockout SOP, so OCR never goes unchecked. |
| Figures | Logos and icons are skipped. Larger figures go to Gemini vision. Process diagrams become a graph of shapes, arrows and lanes, which Layer 2 compares with the text. |
| Every document | A profile: procedural / normative / descriptive, plus code, version, effective date and owner. Each value needs a verbatim evidence quote, or it is dropped. |

Other behaviour:

- **Parse cache.** The deterministic parse is cached per file content and parser version.
- **Quota exhaustion degrades gracefully.** If Gemini is unavailable (for example, free-tier quota),
  the deterministic parse still completes with warnings, and the missing enrichments are retried on
  the next run.
- **Viewer.** The document page (`/documents/:id`) shows the outline, the PDF with clickable boxes
  for every node, provenance, OCR-versus-vision readings, tables, diagrams and the profile.

**First PDF parse:** Docling's model weights (about 730 MB) download into `backend/models/`, using
the Windows certificate store so the corporate proxy works. To download them ahead of time:

```powershell
cd backend
uv run python -m app.ingest.models
```

## Develop

```powershell
cd backend
uv run pytest                          # fast suite (fake Gemini, no network)
uv run pytest -m slow                  # Docling over the whole golden set (a few minutes)
uv run ruff check .
uv run ruff format .
uv run python -m app.eval.golden       # validate golden-set annotations
uv run python -m app.eval.ingest_report             # Layer 1 eval: parse, span accuracy, quotes
uv run python -m app.eval.ingest_report --outline FILE
uv run python -m app.eval.samples      # regenerate the synthetic DOCX + flowchart sample

cd frontend
npm run typecheck
npm run build
```

## Layout

```
backend/app/
  core/       config, db, storage, services, llm/ (gateway, prompt registry, check CLI)
  schemas/    provenance (SourceSpan), taxonomy (gap codes), docast (Layer 1 output), API models
  pipeline/   stages, LangGraph compile graph, checkpointer, run executor
  ingest/     Layer 1: docling/text parsers, assembly, OCR cross-check, diagrams, profile, stage
  api/        projects, documents (+ DocAST, figures), runs (+ SSE events), meta
  eval/       golden-set validator, ingest report, synthetic sample generator
backend/prompts/   versioned prompt templates (<id>.v<N>.toml)
backend/alembic/   migrations
backend/models/    local model weights (git-ignored)
frontend/src/      React + TanStack Query + Tailwind UI (pdf.js document viewer)
golden/            evaluation documents and annotated cases (see golden/README.md)
```
