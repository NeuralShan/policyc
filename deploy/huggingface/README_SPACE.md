---
title: PolicyC API
emoji: 📜
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: PolicyC backend - compiles SOPs into testable policy IR
---

# PolicyC backend (Hugging Face Space)

> **Obsolete for free accounts:** Hugging Face now charges for Docker Spaces (PRO). The free route is Render, see `deploy/DEPLOY.md`. This file is kept for anyone with a paid Space.

FastAPI backend for PolicyC. The UI is hosted separately on Firebase Hosting.
Health check: `/api/health`. API docs: `/docs`.

Everything above the first heading is the Space front-matter; the push script copies this file
to the Space repo as `README.md`.

## One-time setup (Hugging Face website)

1. Sign in at https://huggingface.co (free account, no card).
2. New > Space. Owner = you, name e.g. `policyc`, SDK = **Docker** (blank template), hardware =
   **CPU basic - free**, visibility = **Public** (the Firebase UI calls it from the browser, so it
   must be reachable; secrets stay private regardless).
3. Space > Settings > **Variables and secrets** > add:

   | Type | Name | Value |
   |---|---|---|
   | Secret | `PC_GEMINI_API_KEY` | AI Studio key from https://aistudio.google.com/apikey |
   | Variable | `PC_GEMINI_BACKEND` | `developer` |
   | Variable | `PC_MODEL_PRO`, `PC_MODEL_FLASH`, `PC_MODEL_LITE`, `PC_MODEL_EMBEDDING` | model ids you have free-tier access to (defaults are in backend/app/core/config.py) |
   | Variable | `PC_FIREBASE_PROJECT_ID` | your Firebase project id (turns on sign-in enforcement; omit to leave the API open) |
   | Variable | `PC_CORS_ORIGINS` | `https://<project>.web.app,https://<project>.firebaseapp.com` |
   | Variable | `PC_LLM_MAX_RPM` | `8` (stay inside the free-tier requests/minute) |

4. (Optional) Settings > Persistent storage is paid on HF. Without it the disk is wiped on every
   restart/sleep; the bundled demo projects in `backend/seed/` are reloaded at startup.

## Push the code

From the repo root (`policyc/`), PowerShell:

```powershell
.\deploy\huggingface\push_space.ps1 -Space <hf-user>/<space-name>
```

Git Bash / Linux / macOS:

```bash
./deploy/huggingface/push_space.sh <hf-user>/<space-name>
```

When git asks for credentials: username = your HF username, password = an **access token with
Write role** (https://huggingface.co/settings/tokens). The token is never written to a file or
embedded in the remote URL. The script stages a clean copy (Dockerfile, README.md, backend/ without
.venv/.env/data/models/tests, optional frontend/dist) in a temp folder and force-pushes it as `main`
to `https://huggingface.co/spaces/<hf-user>/<space-name>`. Do not `git push` your working tree to the
Space: it would upload your history and any local `.env`.

## After pushing

The Space builds the image (first build 10-20 min: CPU torch + Docling model download), then
starts. Watch the "Logs" tab. The API base URL is `https://<hf-user>-<space-name>.hf.space`
(lower-case; use it as `VITE_API_BASE`). See `deploy/DEPLOY.md` for the full runbook.
