"""Optional local-model adapter boundary using an injected transport."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .base import LLMResponse


class LocalModelAdapter:
    is_local = True

    def __init__(self, transport: Callable[[str, Mapping[str, Any]], LLMResponse]):
        self._transport = transport

    def generate_structured(self, *, prompt: str, response_schema: Mapping[str, Any]) -> LLMResponse:
        return self._transport(prompt, response_schema)


__all__ = ["LocalModelAdapter"]
