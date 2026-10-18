# PolicyC deployment: technical reference (for experienced readers; beginners start with DEPLOY.md)

> **Note:** the Hugging Face Space route described below needs a paid PRO plan since Docker Spaces left the free tier. The free route is **Render** with the default `Dockerfile` (lightweight image, no Docling); see DEPLOY.md. The full image is `Dockerfile.full`; it remains for self-hosting with enough RAM.

Frontend: Firebase Hosting (Spark plan). Backend: Hugging Face Space (Docker, free CPU basic).
LLM: Gemini via an AI Studio API key (Vertex is not used: it needs billing). Auth: Firebase
Authentication (Google sign-in), verified by the backend.

Placeholders used below: `<fb-project>` Firebase project id, `<hf-user>` HF username, `<space>` Space
name. The Space API origin is `https://<hf-user>-<space>.hf.space` (lower-case).

## Compliance note (open question for the organisers)

The hackathon rule says the project must be "deployed on Google Cloud via Cloud Run or Firebase".
Here the frontend is on Firebase Hosting but the backend runs on Hugging Face Spaces, because Cloud
Run/Functions require a billing account. Whether this split satisfies the rule is NOT confirmed;
ask the organisers before submission (and keep the Cloud Run route as fallback if they say no).

## a) Firebase project (Spark plan)

1. https://console.firebase.google.com > Add project > name it, disable Google Analytics. Stay on the
   Spark (free) plan; never click "Upgrade".
2. Build > Authentication > Get started > Sign-in method > **Google** > Enable > pick a support
   email > Save.
3. Authentication > Settings > **Authorized domains**: confirm `localhost`, `<fb-project>.web.app`
   and `<fb-project>.firebaseapp.com` are listed (add any custom domain). The HF domain is not needed
   (sign-in happens on the Firebase-hosted UI).
4. Project settings (gear) > General > Your apps > **Web** (`</>`) > register app (tick nothing
   about Hosting) > copy the `firebaseConfig` values (apiKey, authDomain, projectId, appId,
   messagingSenderId).
5. Install the CLI and log in: `npm i -g firebase-tools` then `firebase login`.
6. `cp .firebaserc.example .firebaserc` and put `<fb-project>` in it (or `firebase use --add`).
7. In `firebase.json` replace `YOUR-USER-YOUR-SPACE.hf.space` in the CSP `connect-src` with your
   Space host (search for the TODO placeholder).

## b) Hugging Face Space (backend)

Follow `deploy/huggingface/README_SPACE.md`: create a Docker Space, add the secrets/variables, run
the push script.

Variables/secrets summary:

| Name | Where | Example / meaning |
|---|---|---|
| `PC_GEMINI_API_KEY` | secret | AI Studio key |
| `PC_GEMINI_BACKEND` | variable | `developer` (baked into the image as default too) |
| `PC_MODEL_PRO`, `PC_MODEL_FLASH`, `PC_MODEL_LITE`, `PC_MODEL_EMBEDDING` | variable | Gemini model ids |
| `PC_FIREBASE_PROJECT_ID` | variable | `<fb-project>`; unset = auth disabled, API fully open |
| `PC_CORS_ORIGINS` | variable | `https://<fb-project>.web.app,https://<fb-project>.firebaseapp.com` (comma list or JSON list) |
| `PC_CORS_ORIGIN_REGEX` | variable, optional | e.g. `https://<fb-project>--[a-z0-9-]+\.web\.app` for hosting preview channels |
| `PC_LLM_MAX_RPM` | variable | `8` (client-side throttle per model) |
| `PC_SERVE_UI` | variable, optional | `false` to never serve a bundled UI from the Space |
| `PC_DATA_DIR`, `PC_MODELS_DIR` | image defaults | `/data`, `/opt/models` (do not set) |

Wait for the build to finish (10-20 min first time), then check
`https://<hf-user>-<space>.hf.space/api/health` returns `{"status":"ok"}`.

## c) Build and deploy the frontend

```bash
cd frontend
cp .env.example .env.production     # then edit: VITE_API_BASE and the five VITE_FIREBASE_* values
npm ci
npm run build
cd ..
firebase deploy --only hosting
```

Open `https://<fb-project>.web.app`, click Sign in with Google.

## d) Smoke tests

```bash
API=https://<hf-user>-<space>.hf.space
WEB=https://<fb-project>.web.app

# 1. backend alive
curl -s $API/api/health                        # {"status":"ok"}

# 2. auth mode
curl -s $API/api/me                            # {"auth_enabled":true,"uid":null,...}

# 3. CORS preflight from the Firebase origin (expect 200 + access-control-allow-origin: $WEB)
curl -si -X OPTIONS $API/api/projects \
  -H "Origin: $WEB" -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: authorization,content-type" | head -15

# 4. a guest can read public/demo projects
curl -s $API/api/projects

# 5. a guest write is rejected (expect HTTP 401 {"detail":"Sign in required"})
curl -si -X POST $API/api/projects -H "Content-Type: application/json" \
  -d '{"name":"x","description":""}' | head -1; echo

# 6. hosting headers (COOP, CSP, cache)
curl -sI $WEB | grep -i -E "cross-origin-opener|content-security|cache-control"
```

Browser checks: sign in with Google (popup opens and closes, no COOP warning in console); the
project list shows the demo projects when signed out and your own projects when signed in; creating
a project while signed out shows the sign-in prompt; a run streams events (SSE passes the token as
`?access_token=`).

Local dev is unchanged: with `PC_FIREBASE_PROJECT_ID` unset the backend runs fully open and the
Vite proxy forwards `/api` to port 8000.

## e) Free-tier pitfalls

- **The Space sleeps** after ~48 h without traffic and cold-starts in about a minute (the
  Docling weights are baked into the image, so no download). Open the URL a few minutes before a demo.
  The UI should tolerate a slow first request.
- **Ephemeral disk**: without paid persistent storage everything under `/data` (SQLite, uploads,
  checkpoints) is lost on restart. The backend auto-loads the bundled demo projects from
  `backend/seed/seed.json` on startup (see "Demo seed" below) so the app is never empty. User
  projects/runs created on the Space are temporary.
- **Gemini free-tier limits**: low requests/minute and per-day quotas, and free-tier prompts may
  be used by Google to improve products; do not upload confidential documents. Keep
  `PC_LLM_MAX_RPM` low (e.g. 8) and prefer the cache (`PC_LLM_CACHE_MODE=read_write`, default).
- **Free CPU is slow and has 16 GB RAM / 2 vCPU**: keep `PC_EXECUTOR_WORKERS` at 1-2 and avoid
  uploading large scanned PDFs (OCR is heavy).
- **Public Space**: the API is reachable by anyone; with auth enabled only guests can read public
  demo data and every write needs a valid Firebase token. Secrets are never exposed.
- **Hosting preview channels** have different origins; set `PC_CORS_ORIGIN_REGEX` if you use them.
- The Docker image was written but could not be built locally (no Docker); the first HF build is
  the real test. If the CPU torch pin from `uv.lock` is missing on the PyTorch CPU index, the build
  fails at the "uv pip install" step: bump torch in `backend/pyproject.toml`, re-lock and retry.

## f) Demo seed (precomputed sample runs)

`backend/seed/` ships nine finished sample runs (documents, parsed ASTs, IR, diagnostics, tests,
findings) plus the LLM and parse caches. On every start `app/seed.py` inserts them if missing, as
**public, read-only projects** (`owner_uid` NULL), so a cold Space opens with real results and a
guest can explore without signing in. "Explain & fix" works on a demo run: *Apply & recompile*
creates a private copy for the signed-in user. Because the LLM cache ships too, recompiling a sample
is fast and does not spend Gemini quota.

Regenerate it after changing the extraction or analysis code:

```powershell
cd backend
# 1) compile every sample on a running local backend and score it against the answer keys
python -m app.eval.planted --out planted_report.json
# 2) export those runs into backend/seed/ (seed.json, manifest.json, files/)
python scripts/export_seed.py planted_report.json
```

`GET /api/samples` lists them; `POST /api/samples/<id>/run` returns the precomputed run instantly,
or compiles a fresh copy with `?live=true` (signed-in users only when auth is enabled).

### Warm the "Explain & fix" cache (already done for expense, loto, account)

The seed contains the finished sample runs, but a live **Explain & fix → Apply & recompile** asks Gemini
twice (the explanation, and a re-read of the one section you edited). To make that loop instant and
independent of quota on demo day, run it once per sample against a backend that has quota, then
re-export the seed (the LLM response cache is part of it):

```powershell
cd backend
python -m app.eval.fixloop --ids expense,loto,account   # prints "x fixed · y new · z remaining"
python scripts/export_seed.py planted_report.json       # bundles the warmed cache into backend/seed/
```

If the free-tier daily quota is exhausted, the recompile **stops with a clear error** ("Extraction
failed for 1 section(s) ... daily quota exhausted") instead of producing a misleading result; the
explanation and the patch itself still work from the cache. Quota resets daily; use a separate key for
the deployed Space than the one you develop with.
