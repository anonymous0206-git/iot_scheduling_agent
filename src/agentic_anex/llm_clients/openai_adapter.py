"""Optional OpenAI adapter boundary.

No OpenAI SDK is imported by core. Applications may inject a structured-output
transport callable configured with their chosen SDK/version.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .base import LLMResponse


class OpenAIAdapter:
    is_local = False

    def __init__(self, transport: Callable[[str, Mapping[str, Any]], LLMResponse]):
        self._transport = transport

    def generate_structured(self, *, prompt: str, response_schema: Mapping[str, Any]) -> LLMResponse:
        return self._transport(prompt, response_schema)


__all__ = ["OpenAIAdapter"]
