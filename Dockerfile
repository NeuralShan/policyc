# PolicyC backend, LIGHTWEIGHT image for free 512 MB hosts (Render free web service).
# No Docling / PyTorch: plain-text and Markdown upload, the nine precomputed samples, the whole
# analysis engine, Explain & fix and Google sign-in all work. PDF/DOCX upload is refused politely.
# Build context = repository root (this folder). Regenerate the requirements after changing
# dependencies:  cd backend && uv export --no-dev --no-group full --no-hashes --no-emit-project -o requirements-lite.txt
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

COPY backend/requirements-lite.txt ./requirements-lite.txt
RUN pip install -r requirements-lite.txt

COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY backend/prompts ./prompts
COPY backend/seed ./seed

# Non-root; the disk is ephemeral on the free plan, so the demo seed is reloaded on every start.
RUN useradd -m -u 1000 user && mkdir -p /tmp/policyc && chown -R user:user /app /tmp/policyc
USER user

ENV HOME=/home/user \
    PC_DATA_DIR=/tmp/policyc \
    PC_GEMINI_BACKEND=developer \
    PC_MODEL_PRO=gemini-3.5-flash-lite \
    PC_MODEL_FLASH=gemini-3.5-flash-lite \
    PC_MODEL_LITE=gemini-3.5-flash-lite \
    PC_LLM_MAX_RPM=8 \
    PC_EXECUTOR_WORKERS=1 \
    PC_SERVE_UI=false

EXPOSE 10000
# Render injects $PORT (10000 by default)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
