# Submission checklist: Google Cloud AI Builder Cup 2026 (JAPAC)

Deadline: **18 Oct 2026** (the spec's own plan says submit one day early). Rows marked **YOU** need
a person: an account, a credential, a recording or a decision. Nothing below was done on your behalf
outside this repository.

## Judging criteria → where PolicyC answers each

| Criterion (weight) | Our answer | Evidence to show |
|---|---|---|
| Technical merit & Gen AI (40%) | Gemini is essential *and* paired with a verifier: language → model (symbols, structure, flow pass), vision cross-check of scans, explain-and-patch. Findings come only from deterministic code (graph search, Z3, simulator) with a witness. Self-healing: model output is validated and repaired (normaliser + guards). | `docs/ARCHITECTURE.md`, planted-bug recall table (README), golden tests |
| Problem alignment & impact (25%) | Every bank, factory and hospital runs on SOPs that are never tested. Nine sample SOPs across banking, manufacturing, fintech, HR, IT, safety, incl. one in Bahasa Indonesia. | Sample gallery on the home page |
| Innovation (25%) | Compiler + CI ideas applied to human procedures: lexer/parser/type-checker/test-suite analogy, regression diff, reality check against real case history. | Demo: fix → recompile → "3 fixed · 0 new" |
| UX & solution design (10%) + **Best UI/UX prize** | IDE for policies: document ↔ flowchart ↔ problems, animated failing trace, one-click fix, health score, dark mode, keyboard-first. | Screenshots in the deck; live demo |

## Requirements

| Requirement | Status |
|---|---|
| Uses Gemini / Google AI | ✔ Gemini API (symbols, structure, flow pass, vision, explain & fix) |
| **Deployed on Google Cloud via Cloud Run or Firebase** | ◐ Frontend on **Firebase Hosting**; backend on **Render's free tier** (needed to stay at ₹0: Cloud Run requires a billing account, and Hugging Face now charges for Docker Spaces). **YOU: ask the organisers in writing whether this split qualifies**, and keep the Firebase link as the submitted URL. Draft message in `deploy/DEPLOY.md` |
| Public GitHub repo, README, MIT licence, no secrets | ✔ `LICENSE`, README. **YOU:** make the repo public; confirm no `.env` is committed |
| Demo video ≤ 3 min (public) | **YOU:** record using `docs/DEMO_SCRIPT.md` (use the precomputed sample so it is instant) |
| Deck as PDF | **YOU:** build from `docs/DECK_OUTLINE.md` |
| Team registered, 2-4 working professionals, 21+, JAPAC | **YOU** (registration closed 11 Oct; confirm your team is in) |
| Commit history inside the hackathon window | **YOU:** check `git log` dates; the repo's first commit is 16 Oct 2026 |
| All materials in English | ✔ |

## Go-live steps (one sitting, ~40 minutes)

1. Create a Firebase project (Spark plan), enable **Authentication → Google**, register a web app.
2. Push the code to your GitHub, create a Render free web service from it (Docker), add the settings
   (`PC_GEMINI_API_KEY`, `PC_FIREBASE_PROJECT_ID`, `PC_CORS_ORIGINS`).
3. Put the Render URL and Firebase config in `frontend/.env.production`, `npm run build`, `firebase deploy --only hosting`.
4. Smoke test from an incognito window: sign in as guest → open *Expense* sample → click a finding →
   *Explain & fix* → accept → regression toast.
5. Full runbook: [deploy/DEPLOY.md](../deploy/DEPLOY.md).

## Before you record

The fix loop has been run and the LLM cache is already bundled in `backend/seed/`. Verified on a cold
server with an **invalid** API key: Explain & fix → Apply & recompile works from the bundle alone.

| Sample | Fix applied | Result |
|---|---|---|
| `expense` | clause 4.1 made inclusive ("up to and including INR 10,000") | 1 fixed · 0 new · 10 remaining, health 26 → 50 |
| `loto` | exception must verify zero energy first | 2 fixed · 0 new, safety bypass closed, health 70 → 78 |
| `account` | eligibility gap closed | 4 fixed · 0 new, health 42 → 77 |

Only if you change the extraction or analysis code again: re-run `python -m app.eval.planted --replay`
(offline), `python -m app.eval.fixloop` (needs quota), then `python scripts/export_seed.py`. The free tier's
**daily quota ran out during development** (a full corpus run uses about 100 calls); use a fresh key for
the deployed engine and avoid re-running the whole corpus on it.

## Demo-day safety net

* Samples open **instantly** from bundled precomputed runs: no Gemini call, no waiting.
* "Explain & fix" and "Apply & recompile" on the three showcase samples work without quota (cache bundled).
  Other samples and your own documents need a working Gemini key.
* If the engine is asleep (Render free tier), the first request takes about a minute: open `/api/health` once before recording, or add the free UptimeRobot monitor from `deploy/DEPLOY.md` Part 8.
