"""Test doubles for Gemini. Tests never call the network."""

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel

Responder = Callable[[type[BaseModel], list], Any]


class FakeChat:
    """Stands in for ``ChatGoogleGenerativeAI``. ``responder(schema, messages)`` returns the parsed
    object (or ``None`` to simulate unparseable output, or raises to simulate API errors)."""

    def __init__(self, name: str, responder: Responder):
        self.name = name
        self.responder = responder
        self.calls: list = []

    def with_structured_output(self, schema, include_raw):
        assert include_raw is True
        fake = self

        class _Runnable:
            def invoke(self, messages):
                fake.calls.append(messages)
                parsed = fake.responder(schema, messages)
                raw = AIMessage(
                    content="{}",
                    usage_metadata={"input_tokens": 11, "output_tokens": 5, "total_tokens": 16},
                )
                if parsed is None:
                    return {"raw": raw, "parsed": None, "parsing_error": ValueError("bad json")}
                return {"raw": raw, "parsed": parsed, "parsing_error": None}

        return _Runnable()


def default_responder(schema: type[BaseModel], messages) -> Any:
    """Plausible minimal answers for the ingest and extract prompts."""
    name = schema.__name__
    if name == "ProfileReply":
        return schema(doc_class="procedural", rationale="Numbered steps with actors.")
    if name == "PageReading":
        return schema(blocks=[])
    if name == "DiagramReply":
        return schema(is_process_diagram=False, description="A logo.")
    if name == "SymbolReply":
        return schema(
            roles=[{"id": "agent", "name": "Agent", "quote": "Agent"}],
            artifacts=[{"id": "form", "name": "Form", "quote": "Form"}],
            systems=[{"id": "crm", "name": "CRM", "quote": "CRM"}],
            terms=[],
        )
    if name == "StructureReply":
        return schema(
            steps=[
                {
                    "id": "s01",
                    "kind": "action",
                    "actor_role_id": "agent",
                    "modal": "shall",
                    "action": "log the complaint",
                    "source_quote": "Agent",
                }
            ],
            decisions=[],
            transitions=[{"from_id": "s01", "to_id": "END"}],
            references=[],
        )
    if name == "_RoundtripReply":
        return schema(agreement=1.0, missing=[], wrong=[], hallucinated=[])
    raise AssertionError(f"no fake answer for {name}")


def fake_factory(responder: Responder = default_responder, models: dict | None = None):
    def factory(name: str) -> FakeChat:
        chat = FakeChat(name, responder)
        if models is not None:
            models[name] = chat
        return chat

    return factory


def image_count(messages) -> int:
    content = messages[-1][1]
    return (
        sum(1 for block in content if block.get("type") == "image")
        if isinstance(content, list)
        else 0
    )
