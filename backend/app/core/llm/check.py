"""Verify Gemini credentials and model names.

uv run python -m app.core.llm.check                # one structured call on the flash tier
uv run python -m app.core.llm.check --tier pro
uv run python -m app.core.llm.check --list-models  # what this project/key can actually use
"""

import argparse
import sys

from pydantic import BaseModel, Field

from app.core.config import GeminiBackend, LLMCacheMode, Settings
from app.core.db import make_engine, make_session_factory, run_migrations
from app.core.llm.gateway import LLMGateway
from app.core.llm.prompts import ModelTier, PromptRegistry


class SmokeReply(BaseModel):
    is_procedural: bool
    actor: str | None = Field(description="Who performs the action, as written; null if none")


def list_models(settings: Settings) -> None:
    from google import genai

    client = genai.Client(
        vertexai=settings.gemini_backend == GeminiBackend.VERTEX,
        project=settings.gcp_project,
        location=settings.gcp_location,
        api_key=settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None,
    )
    for model in client.models.list():
        print(model.name)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--tier", choices=[t.value for t in ModelTier], default=ModelTier.FLASH)
    parser.add_argument("--list-models", action="store_true")
    args = parser.parse_args()

    settings = Settings(llm_cache_mode=LLMCacheMode.OFF)
    print(f"backend   : {settings.gemini_backend}")
    print(f"project   : {settings.gcp_project or '(from env / ADC)'}")
    print(f"location  : {settings.gcp_location or '(SDK default)'}")
    print(f"pro model : {settings.model_pro}")
    print(f"flash     : {settings.model_flash}")
    print(f"api key   : {'set' if settings.gemini_api_key else 'not set (env vars / ADC)'}")

    if args.list_models:
        list_models(settings)
        return 0

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(settings.resolved_database_url)
    sessions = make_session_factory(make_engine(settings.resolved_database_url))
    gateway = LLMGateway(settings, sessions, PromptRegistry())
    reply = gateway.structured(
        "smoke_test",
        SmokeReply,
        {"sentence": "The Customer Service Agent shall log the complaint within 1 business day."},
        tier=ModelTier(args.tier),
    )
    print(f"OK ({gateway.model_name(ModelTier(args.tier))}): {reply.model_dump()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
