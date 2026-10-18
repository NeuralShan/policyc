"""Application settings, loaded from environment variables (prefix ``PC_``) or ``backend/.env``."""

import json
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator, SecretStr
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class GeminiBackend(StrEnum):
    VERTEX = "vertex"  # Vertex AI: enterprise data terms, region pinning (recommended)
    DEVELOPER = "developer"  # Gemini Developer API (AI Studio key), for local experiments


class LLMCacheMode(StrEnum):
    OFF = "off"  # always call the model, never store
    READ_WRITE = "read_write"  # serve from cache when possible, store new responses
    REPLAY = "replay"  # cache only; a miss is an error (deterministic CI)


def _parse_origins(value: object) -> object:
    """Accepts a JSON list or a comma-separated string (env var friendly)."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [part.strip().rstrip("/") for part in text.split(",") if part.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PC_", env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    data_dir: Path = BACKEND_DIR / "data"
    models_dir: Path = BACKEND_DIR / "models"  # local model weights (Docling layout/table/OCR)
    database_url: str | None = None  # defaults to SQLite inside data_dir
    checkpoint_path: Path | None = None  # LangGraph checkpoints; defaults to data_dir
    auto_migrate: bool = True
    seed_demo: bool = True  # load the bundled precomputed sample projects on startup
    max_upload_mb: int = 50
    # PC_CORS_ORIGINS: JSON list or comma-separated; PC_CORS_ORIGIN_REGEX: optional extra pattern
    cors_origins: Annotated[list[str], NoDecode, BeforeValidator(_parse_origins)] = [
        "http://localhost:5173"
    ]
    cors_origin_regex: str | None = None
    serve_ui: bool | None = None  # PC_SERVE_UI; None = serve frontend/dist when it exists

    # Optional Firebase Auth. Unset = auth disabled (everything is open, as in local dev).
    firebase_project_id: str | None = None  # PC_FIREBASE_PROJECT_ID
    executor_workers: int = 2

    gemini_backend: GeminiBackend = GeminiBackend.VERTEX
    gemini_api_key: SecretStr | None = None  # optional; otherwise SDK env vars / ADC are used
    gcp_project: str | None = None
    gcp_location: str | None = None  # e.g. "europe-west4"; None lets the SDK default ("global")
    model_pro: str = "gemini-3.1-pro-preview"
    model_flash: str = "gemini-3.8-flash"
    model_lite: str = "gemini-3.5-flash-lite"  # light tasks; separate free-tier quota from flash
    model_embedding: str = "gemini-embedding-2"
    llm_seed: int = 7
    llm_timeout_s: float = 120.0
    llm_max_retries: int = 2  # SDK retries on transient errors; quota errors fail fast
    llm_max_rpm: int = 0  # client-side throttle, requests per minute per model; 0 = off
    llm_cache_mode: LLMCacheMode = LLMCacheMode.READ_WRITE

    ocr_lang: str = "en"  # RapidOCR recognition language for scanned pages
    ocr_vision_check: bool = True  # second reading of OCR pages with Gemini vision

    @cached_property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"

    @cached_property
    def resolved_checkpoint_path(self) -> Path:
        return self.checkpoint_path or self.data_dir / "checkpoints.sqlite"

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024
