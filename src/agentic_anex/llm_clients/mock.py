"""Deterministic offline mock for orchestration tests."""

from __future__ import annotations

from collections import deque
from typing import Any, Iterable, Mapping

from .base import LLMResponse


class MockLLMClient:
    is_local = True

    def __init__(self, responses: Iterable[Mapping[str, Any] | LLMResponse]):
        self._responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_structured(self, *, prompt: str, response_schema: Mapping[str, Any]) -> LLMResponse:
        self.calls.append({"prompt": prompt, "response_schema": response_schema})
        if not self._responses:
            raise RuntimeError("MockLLMClient has no response remaining")
        response = self._responses.popleft()
        if isinstance(response, LLMResponse):
            return response
        return LLMResponse(response, {"provider": "mock", "model": "deterministic-mock"})


__all__ = ["MockLLMClient"]
