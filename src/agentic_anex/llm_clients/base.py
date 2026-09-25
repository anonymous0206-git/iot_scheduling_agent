"""Provider-neutral structured-output client contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


class LLMClientError(RuntimeError):
    """Bounded provider failure safe to expose in orchestration logs."""

    def __init__(self, message: str, *, code: str = "LLM_CLIENT_ERROR"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LLMResponse:
    structured_output: Mapping[str, Any]
    model_metadata: Mapping[str, Any] = field(default_factory=dict)


class LLMClient(Protocol):
    is_local: bool

    def generate_structured(
        self, *, prompt: str, response_schema: Mapping[str, Any]
    ) -> LLMResponse:
        """Return JSON-compatible structured output matching response_schema."""


__all__ = ["LLMClient", "LLMResponse", "LLMClientError"]
