"""Ollama structured-output client with no cloud fallback."""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

from .base import LLMClientError, LLMResponse
from .http_transport import JSONTransport, json_http_post


class OllamaClient:
    is_local = True

    def __init__(self, *, model: str, base_url: str = "http://localhost:11434",
                 temperature: float = 0, timeout_seconds: float = 60,
                 seed: int | None = None, transport: JSONTransport | None = None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.seed = seed
        self._transport = transport or json_http_post

    def generate_structured(self, *, prompt: str,
                            response_schema: Mapping[str, Any]) -> LLMResponse:
        options: dict[str, Any] = {"temperature": self.temperature}
        if self.seed is not None:
            options["seed"] = self.seed
        payload = {
            "model": self.model, "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "format": dict(response_schema), "options": options,
        }
        started = time.monotonic()
        response = self._transport(
            url=f"{self.base_url}/api/chat", payload=payload, headers={},
            timeout_seconds=self.timeout_seconds,
        )
        try:
            content = response["message"]["content"]
            structured = content if isinstance(content, Mapping) else json.loads(content)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LLMClientError("Ollama returned malformed structured output.",
                                 code="MALFORMED_STRUCTURED_OUTPUT") from exc
        if not isinstance(structured, Mapping):
            raise LLMClientError("Ollama structured output must be an object.",
                                 code="MALFORMED_STRUCTURED_OUTPUT")
        metadata = {
            "provider": "ollama", "model": response.get("model", self.model),
            "temperature": self.temperature, "local": True,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
        }
        for source, target in (("prompt_eval_count", "prompt_tokens"),
                               ("eval_count", "completion_tokens"),
                               ("total_duration", "provider_duration_ns")):
            if source in response:
                metadata[target] = response[source]
        return LLMResponse(dict(structured), metadata)


__all__ = ["OllamaClient"]
