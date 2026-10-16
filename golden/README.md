# Golden set

SME-annotated documents with the gaps the compiler **should** find. Every layer measures itself
against these annotations (extraction recall, diagnostic recall per gap code, findings precision).

Validate with:

```
cd backend
uv run python -m app.eval.golden
```

## Layout

```
golden/
  *.pdf, *.txt                  evaluation documents (Layer 1 parses every supported file here)
  sample-complaint-refund/      SYNTHETIC: Markdown SOP, case history, roles; 25 annotated gaps
    manifest.json
    SOP-CS-014.md
    case_history.csv
    context/roles.csv
  sample-access-request/        SYNTHETIC: DOCX SOP with a swimlane flowchart; 4 annotated gaps
    manifest.json               (regenerate: uv run python -m app.eval.samples)
    SOP-IT-021.docx
  private/                      real, confidential cases: git-ignored
    <case-id>/manifest.json ...
```

Put real SOPs and real case history under `golden/private/`. It is git-ignored.

Loose documents in `golden/` without a `manifest.json` are still used for Layer 1 (parse quality,
span accuracy). Add a manifest to annotate their gaps for Layers 2 onwards.

## manifest.json

| Field | Meaning |
|---|---|
| `id`, `title` | Identifiers for the case |
| `synthetic` | `true` for invented material |
| `documents` | Source documents, relative to the case folder (PDF, DOCX, HTML, MD, TXT) |
| `context_packs` | Organisation facts outside the documents, e.g. `{"roles": "context/roles.csv"}` |
| `case_history` | CSV event logs: one row per event, must include a `case_id` column |
| `expected_findings` | The annotated gaps (below) |

Each expected finding:

| Field | Meaning |
|---|---|
| `code` | A gap code from the taxonomy (see the **Gap codes** page in the UI, or `backend/app/schemas/taxonomy.py`) |
| `document` + `quote` | Where the gap is: a **verbatim** quote from that document. `app.eval.golden` checks MD/TXT/HTML quotes; `app.eval.ingest_report` checks every format against the parsed text |
| `cases` | Case-history `case_id`s that show the gap happening in practice (required for reality codes `RL*` that have no quote) |
| `accept_codes` | Other codes that also count as catching this gap. Example: a missing branch (`ST004`) found dynamically as an undetermined outcome (`EX001`) |
| `note` | What the gap is, in plain words |

Annotate one gap per entry. If one sentence has two problems (say, no owner *and* a dead end), make
two entries with the same quote.
