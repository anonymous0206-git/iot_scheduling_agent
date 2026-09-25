"""Client for local or remote OpenAI-compatible chat-completions servers."""

from __future__ import annotations

import json
import ipaddress
import time
from typing import Any, Mapping
from urllib.parse import urlparse

from .base import LLMClientError, LLMResponse
from .http_transport import HTTPStatusError, JSONTransport, json_http_post
from .strict_schema import to_openai_strict


class OpenAICompatibleClient:
    provider_name = "openai_compatible"
    is_local = True

    def __init__(self, *, base_url: str, model: str, api_key: str | None = None,
                 temperature: float = 0, timeout_seconds: float = 60,
                 transport: JSONTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self._transport = transport or json_http_post
        if self.provider_name == "openai_compatible":
            hostname = urlparse(base_url).hostname or ""
            try:
                self.is_local = ipaddress.ip_address(hostname).is_private
            except ValueError:
                self.is_local = hostname.lower() == "localhost"

    def _request(self, prompt: str, response_format: Mapping[str, Any]) -> Mapping[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        return self._transport(
            url=f"{self.base_url}/chat/completions",
            payload={
                "model": self.model, "temperature": self.temperature,
                "messages": [
                    {"role": "system", "content": "Return only one JSON object."},
                    {"role": "user", "content": prompt},
                ],
                "response_format": dict(response_format),
            },
            headers=headers, timeout_seconds=self.timeout_seconds,
        )

    def generate_structured(self, *, prompt: str,
                            response_schema: Mapping[str, Any]) -> LLMResponse:
        started = time.monotonic()
        mode = "json_schema"
        # The strict subset rejects, rather than ignores, the bounds, defaults and
        # bare ``const`` values a validation schema carries. Sending the schema
        # unrewritten makes every request 400 and silently degrade to free-form
        # JSON, where the model invents field names for a schema it never saw.
        native_format = {
            "type": "json_schema",
            "json_schema": {"name": "agentic_anex_decision", "strict": True,
                            "schema": to_openai_strict(response_schema)},
        }
        try:
            response = self._request(prompt, native_format)
        except HTTPStatusError as exc:
            if exc.status not in (400, 415, 422):
                raise
            mode = "json_object"
            response = self._request(prompt, {"type": "json_object"})
        try:
            content = response["choices"][0]["message"]["content"]
            structured = content if isinstance(content, Mapping) else json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMClientError("Provider returned malformed structured output.",
                                 code="MALFORMED_STRUCTURED_OUTPUT") from exc
        if not isinstance(structured, Mapping):
            raise LLMClientError("Structured output must be a JSON object.",
                                 code="MALFORMED_STRUCTURED_OUTPUT")
        metadata: dict[str, Any] = {
            "provider": self.provider_name, "model": response.get("model", self.model),
            "temperature": self.temperature, "local": self.is_local,
            "structured_output_mode": mode,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
        }
        usage = response.get("usage")
        if isinstance(usage, Mapping):
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                if name in usage:
                    metadata[name] = usage[name]
        return LLMResponse(dict(structured), metadata)


__all__ = ["OpenAICompatibleClient"]
