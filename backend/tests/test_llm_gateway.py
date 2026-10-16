from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import LLMCacheMode
from app.core.llm.gateway import CallContext, LLMCacheMiss, LLMGateway, LLMOutputError
from app.core.llm.prompts import ModelTier, PromptRegistry
from app.models import LLMCacheEntry, LLMCall


class Verdict(BaseModel):
    is_procedural: bool
    actor: str | None


class FakeChat:
    """Stands in for a Gemini chat model; records what it was asked."""

    def __init__(self, name: str, replies: list):
        self.name = name
        self.replies = replies
        self.calls: list = []

    def with_structured_output(self, schema, include_raw):
        assert include_raw is True
        fake = self

        class _Runnable:
            def invoke(self, messages):
                fake.calls.append(messages)
                parsed = fake.replies.pop(0)
                raw = AIMessage(
                    content="{}",
                    usage_metadata={"input_tokens": 11, "output_tokens": 5, "total_tokens": 16},
                )
                if parsed is None:
                    return {"raw": raw, "parsed": None, "parsing_error": ValueError("bad json")}
                return {"raw": raw, "parsed": parsed, "parsing_error": None}

        return _Runnable()


@pytest.fixture
def prompts(tmp_path: Path) -> PromptRegistry:
    (tmp_path / "classify.v1.toml").write_text(
        'id = "classify"\nversion = 1\ntier = "flash"\n'
        'system = "You read SOPs."\nuser = "Sentence: $sentence"\n',
        encoding="utf-8",
    )
    return PromptRegistry(tmp_path)


def make_gateway(services, prompts, replies, mode=LLMCacheMode.READ_WRITE):
    models: dict[str, FakeChat] = {}

    def factory(name):
        models[name] = FakeChat(name, replies)
        return models[name]

    settings = services.settings.model_copy(update={"llm_cache_mode": mode})
    return LLMGateway(settings, services.sessions, prompts, factory), models


def calls(services) -> list[LLMCall]:
    with services.sessions() as session:
        return list(session.scalars(select(LLMCall).order_by(LLMCall.id)))


def test_miss_then_hit_serves_from_cache(services, prompts):
    reply = Verdict(is_procedural=True, actor="agent")
    gateway, models = make_gateway(services, prompts, [reply])
    ctx = CallContext(run_id="run_1", stage="extract")

    first = gateway.structured("classify", Verdict, {"sentence": "Agent logs it."}, context=ctx)
    second = gateway.structured("classify", Verdict, {"sentence": "Agent logs it."}, context=ctx)

    assert first == second == reply
    fake = models[services.settings.model_flash]
    assert len(fake.calls) == 1
    assert fake.calls[0] == [("system", "You read SOPs."), ("human", "Sentence: Agent logs it.")]
    logged = calls(services)
    assert [c.cache_hit for c in logged] == [False, True]
    assert (logged[0].input_tokens, logged[0].output_tokens) == (11, 5)
    assert (logged[0].run_id, logged[0].stage, logged[0].tier) == ("run_1", "extract", "flash")


def test_different_input_or_tier_is_a_different_cache_entry(services, prompts):
    replies = [Verdict(is_procedural=True, actor=None) for _ in range(3)]
    gateway, models = make_gateway(services, prompts, replies)
    gateway.structured("classify", Verdict, {"sentence": "A"})
    gateway.structured("classify", Verdict, {"sentence": "B"})
    gateway.structured("classify", Verdict, {"sentence": "A"}, tier=ModelTier.PRO)
    assert len(models[services.settings.model_flash].calls) == 2
    assert len(models[services.settings.model_pro].calls) == 1
    with services.sessions() as session:
        assert len(session.scalars(select(LLMCacheEntry)).all()) == 3


def test_replay_mode_fails_on_miss_without_calling_model(services, prompts):
    gateway, models = make_gateway(services, prompts, [], mode=LLMCacheMode.REPLAY)
    with pytest.raises(LLMCacheMiss):
        gateway.structured("classify", Verdict, {"sentence": "A"})
    assert models == {}
    assert calls(services)[0].error == "cache miss in replay mode"


def test_off_mode_never_reads_or_writes_cache(services, prompts):
    replies = [Verdict(is_procedural=False, actor=None) for _ in range(2)]
    gateway, models = make_gateway(services, prompts, replies, mode=LLMCacheMode.OFF)
    gateway.structured("classify", Verdict, {"sentence": "A"})
    gateway.structured("classify", Verdict, {"sentence": "A"})
    assert len(models[services.settings.model_flash].calls) == 2
    with services.sessions() as session:
        assert session.scalars(select(LLMCacheEntry)).all() == []


def test_unparseable_output_raises_and_is_logged_not_cached(services, prompts):
    gateway, _ = make_gateway(services, prompts, [None])
    with pytest.raises(LLMOutputError, match="bad json"):
        gateway.structured("classify", Verdict, {"sentence": "A"})
    assert calls(services)[0].error == "bad json"
    with services.sessions() as session:
        assert session.scalars(select(LLMCacheEntry)).all() == []


def test_missing_template_variable_raises(services, prompts):
    gateway, _ = make_gateway(services, prompts, [])
    with pytest.raises(KeyError):
        gateway.structured("classify", Verdict, {})
