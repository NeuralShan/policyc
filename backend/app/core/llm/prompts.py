"""Versioned prompt registry.

Prompts live in ``backend/prompts/<id>.v<N>.toml``. Templates use ``$name`` placeholders
(``string.Template``) so JSON examples with braces need no escaping. Changing a prompt means adding
a new version file; the content hash is also part of the LLM cache key, so in-place edits can never
serve stale cached answers.
"""

import hashlib
import re
import string
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.core.config import BACKEND_DIR

PROMPTS_DIR = BACKEND_DIR / "prompts"
_FILENAME = re.compile(r"^(?P<id>[a-z][a-z0-9_]*)\.v(?P<version>\d+)\.toml$")


class ModelTier(StrEnum):
    PRO = "pro"  # extraction, adversarial search, remediation
    FLASH = "flash"  # vision, bulk generation, critics
    LITE = "lite"  # short classification-style calls


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    tier: ModelTier
    description: str
    system: str
    user: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.system}\x00{self.user}".encode()).hexdigest()

    def render(self, variables: Mapping[str, Any] | None = None) -> list[tuple[str, str]]:
        """LangChain-style ``(role, text)`` messages. A missing variable raises ``KeyError``."""
        values = {k: str(v) for k, v in (variables or {}).items()}
        messages = [("human", string.Template(self.user).substitute(values))]
        if self.system:
            messages.insert(0, ("system", string.Template(self.system).substitute(values)))
        return messages


class PromptRegistry:
    def __init__(self, directory: Path = PROMPTS_DIR):
        self._prompts: dict[str, dict[int, Prompt]] = {}
        for path in sorted(directory.glob("*.toml")):
            match = _FILENAME.match(path.name)
            if not match:
                raise ValueError(f"prompt file must be named <id>.v<N>.toml: {path.name}")
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            prompt = Prompt(
                id=data["id"],
                version=int(data["version"]),
                tier=ModelTier(data["tier"]),
                description=data.get("description", ""),
                system=data.get("system", "").strip(),
                user=data["user"].strip(),
            )
            if (prompt.id, prompt.version) != (match["id"], int(match["version"])):
                raise ValueError(f"{path.name}: id/version inside the file do not match its name")
            self._prompts.setdefault(prompt.id, {})[prompt.version] = prompt

    def get(self, prompt_id: str, version: int | None = None) -> Prompt:
        versions = self._prompts.get(prompt_id)
        if not versions:
            raise KeyError(f"unknown prompt: {prompt_id}")
        if version is None:
            return versions[max(versions)]
        if version not in versions:
            raise KeyError(f"unknown prompt version: {prompt_id} v{version}")
        return versions[version]

    def all(self) -> list[Prompt]:
        return [p for versions in self._prompts.values() for p in versions.values()]
