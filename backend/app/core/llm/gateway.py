"""Single entry point for every Gemini call.

All stages call ``LLMGateway.structured()``, never a chat model directly. That gives one place for:
- model-tier routing (pro / flash / lite, names from config),
- deterministic settings (temperature 0, fixed seed),
- schema-constrained output (Pydantic in, validated Pydantic out), optionally with images,
- the response cache (``off`` / ``read_write`` / ``replay``),
- client-side throttling and fail-fast on exhausted quotas (free tier),
- per-call token/latency accounting tied to a compile run and stage.
"""

import base64
import hashlib
import json
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.exceptions import ModelRateLimitError
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from app.core.config import GeminiBackend, LLMCacheMode, Settings
from app.core.llm.prompts import ModelTier, Prompt, PromptRegistry
from app.models import LLMCacheEntry, LLMCall

ModelFactory = Callable[[str], BaseChatModel]


class LLMCacheMiss(RuntimeError):
    """Raised in ``replay`` mode when a response is not in the cache."""


class LLMOutputError(RuntimeError):
    """The model answered, but the answer did not validate against the requested schema."""


class LLMUnavailable(RuntimeError):
    """Quota or rate limit hit. Callers should degrade gracefully and retry in a later run."""


@dataclass(frozen=True)
class CallContext:
    run_id: str | None = None
    stage: str | None = None


def gemini_model_factory(settings: Settings) -> ModelFactory:
    def make(model_name: str) -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs: dict[str, Any] = {
            "model": model_name,
            "temperature": 0,
            "seed": settings.llm_seed,
            "timeout": settings.llm_timeout_s,
            "max_retries": settings.llm_max_retries,
            "vertexai": settings.gemini_backend == GeminiBackend.VERTEX,
        }
        if settings.gcp_project:
            kwargs["project"] = settings.gcp_project
        if settings.gcp_location:
            kwargs["location"] = settings.gcp_location
        if settings.gemini_api_key:
            kwargs["api_key"] = settings.gemini_api_key.get_secret_value()
        return ChatGoogleGenerativeAI(**kwargs)

    return make


def cache_key(
    model: str,
    prompt: Prompt,
    messages: list[tuple[str, str]],
    schema: type[BaseModel],
    seed: int,
    image_hashes: Sequence[str] = (),
) -> str:
    material = {
        "model": model,
        "prompt": [prompt.id, prompt.version, prompt.content_hash],
        "messages": messages,
        "images": list(image_hashes),
        "schema": schema.model_json_schema(),
        "temperature": 0,
        "seed": seed,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


class RateLimiter:
    """At most ``max_per_minute`` acquisitions in any rolling 60 s window (thread-safe)."""

    def __init__(self, max_per_minute: int, clock=time.monotonic, sleep=time.sleep):
        self.max_per_minute = max_per_minute
        self._clock, self._sleep = clock, sleep
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        if self.max_per_minute <= 0:
            return
        while True:
            with self._lock:
                now = self._clock()
                while self._stamps and now - self._stamps[0] >= 60:
                    self._stamps.popleft()
                if len(self._stamps) < self.max_per_minute:
                    self._stamps.append(now)
                    return
                wait = 60 - (now - self._stamps[0])
            self._sleep(wait)


_RETRY_DELAY = re.compile(r"retryDelay'?\"?:\s*'?\"?(\d+)s")


def _quota_block_seconds(error: Exception) -> float | None:
    """For daily-quota errors, how long to stop calling the model; None for per-minute limits."""
    text = str(error)
    if "PerDay" not in text:
        return None
    match = _RETRY_DELAY.search(text)
    return float(match.group(1)) if match else 3600.0


class LLMGateway:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker,
        prompts: PromptRegistry,
        model_factory: ModelFactory | None = None,
        clock=time.monotonic,
    ):
        self.settings = settings
        self.prompts = prompts
        self._sessions = session_factory
        self._factory = model_factory or gemini_model_factory(settings)
        self._models: dict[str, BaseChatModel] = {}
        self._limiters: dict[str, RateLimiter] = {}
        self._blocked_until: dict[str, float] = {}
        self._clock = clock
        self._lock = threading.Lock()

    def model_name(self, tier: ModelTier) -> str:
        return {
            ModelTier.PRO: self.settings.model_pro,
            ModelTier.FLASH: self.settings.model_flash,
            ModelTier.LITE: self.settings.model_lite,
        }[tier]

    def structured[T: BaseModel](
        self,
        prompt_id: str,
        schema: type[T],
        variables: Mapping[str, Any] | None = None,
        *,
        images: Sequence[bytes] = (),
        version: int | None = None,
        tier: ModelTier | None = None,
        context: CallContext | None = None,
    ) -> T:
        """Render a prompt, call Gemini (or the cache) and return a validated ``schema`` instance.

        ``images`` are PNG bytes appended to the user message.
        """
        prompt = self.prompts.get(prompt_id, version)
        tier = tier or prompt.tier
        model = self.model_name(tier)
        messages = prompt.render(variables)
        image_hashes = [hashlib.sha256(img).hexdigest() for img in images]
        key = cache_key(model, prompt, messages, schema, self.settings.llm_seed, image_hashes)
        mode = self.settings.llm_cache_mode
        call = LLMCall(
            run_id=context.run_id if context else None,
            stage=context.stage if context else None,
            tier=tier,
            model=model,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            cache_key=key,
            cache_hit=False,
        )

        if mode != LLMCacheMode.OFF:
            with self._sessions() as session:
                entry = session.get(LLMCacheEntry, key)
                if entry is not None:
                    call.cache_hit = True
                    session.add(call)
                    session.commit()
                    return schema.model_validate(entry.response)
            if mode == LLMCacheMode.REPLAY:
                self._log(call, error="cache miss in replay mode")
                raise LLMCacheMiss(
                    f"{prompt.id} v{prompt.version}: no cached response ({key[:12]})"
                )

        blocked = self._blocked_until.get(model, 0) - self._clock()
        if blocked > 0:
            self._log(call, error="skipped: daily quota exhausted")
            raise LLMUnavailable(
                f"{model}: daily quota exhausted (retry in {blocked / 3600:.1f} h)"
            )

        self._limiter(model).acquire()
        started = time.perf_counter()
        try:
            result = (
                self._model(model)
                .with_structured_output(schema, include_raw=True)
                .invoke(_with_images(messages, images))
            )
        except ModelRateLimitError as exc:
            call.latency_ms = int((time.perf_counter() - started) * 1000)
            self._log(call, error=f"{type(exc).__name__}: {exc}"[:2000])
            block = _quota_block_seconds(exc)
            if block is not None:
                self._blocked_until[model] = self._clock() + block
                raise LLMUnavailable(f"{model}: daily quota exhausted") from exc
            raise LLMUnavailable(f"{model}: rate limited") from exc
        except Exception as exc:
            call.latency_ms = int((time.perf_counter() - started) * 1000)
            self._log(call, error=f"{type(exc).__name__}: {exc}"[:2000])
            raise
        call.latency_ms = int((time.perf_counter() - started) * 1000)

        usage = getattr(result.get("raw"), "usage_metadata", None) or {}
        call.input_tokens = usage.get("input_tokens")
        call.output_tokens = usage.get("output_tokens")

        parsed = result.get("parsed")
        if parsed is None:
            error = result.get("parsing_error") or "model returned no structured output"
            self._log(call, error=str(error))
            raise LLMOutputError(f"{prompt.id} v{prompt.version}: {error}")
        if not isinstance(parsed, schema):
            parsed = schema.model_validate(parsed)

        with self._sessions() as session:
            if mode == LLMCacheMode.READ_WRITE:
                session.merge(
                    LLMCacheEntry(
                        key=key,
                        model=model,
                        prompt_id=prompt.id,
                        prompt_version=prompt.version,
                        response=parsed.model_dump(mode="json"),
                    )
                )
            session.add(call)
            session.commit()
        return parsed

    def _model(self, name: str) -> BaseChatModel:
        with self._lock:
            if name not in self._models:
                self._models[name] = self._factory(name)
            return self._models[name]

    def _limiter(self, name: str) -> RateLimiter:
        with self._lock:
            if name not in self._limiters:
                self._limiters[name] = RateLimiter(self.settings.llm_max_rpm)
            return self._limiters[name]

    def _log(self, call: LLMCall, error: str) -> None:
        call.error = error
        with self._sessions() as session:
            session.add(call)
            session.commit()


def _with_images(messages: list[tuple[str, str]], images: Sequence[bytes]) -> list:
    if not images:
        return messages
    *head, (role, text) = messages
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text}]
    blocks += [
        {"type": "image", "base64": base64.b64encode(img).decode(), "mime_type": "image/png"}
        for img in images
    ]
    return [*head, (role, blocks)]
