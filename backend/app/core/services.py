"""Long-lived services shared by the API and the compile pipeline, built once at startup."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.gateway import LLMGateway, ModelFactory
from app.core.llm.prompts import PromptRegistry
from app.core.storage import LocalStorage


@dataclass
class Services:
    settings: Settings
    engine: Engine
    sessions: sessionmaker
    storage: LocalStorage
    prompts: PromptRegistry
    llm: LLMGateway
    _singletons: dict[str, Any] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def singleton[T](self, name: str, make: Callable[[], T]) -> T:
        """Per-services instance of an expensive helper (e.g. the Docling-backed ingestor)."""
        with self._lock:
            if name not in self._singletons:
                self._singletons[name] = make()
            return self._singletons[name]

    @classmethod
    def build(cls, settings: Settings, model_factory: ModelFactory | None = None) -> "Services":
        engine = make_engine(settings.resolved_database_url)
        sessions = make_session_factory(engine)
        prompts = PromptRegistry()
        return cls(
            settings=settings,
            engine=engine,
            sessions=sessions,
            storage=LocalStorage(settings.storage_dir),
            prompts=prompts,
            llm=LLMGateway(settings, sessions, prompts, model_factory),
        )
