"""OpenAI cloud client; credentials are retained only in private memory."""

from __future__ import annotations

import os

from .base import LLMClientError
from .http_transport import JSONTransport
from .openai_compatible_client import OpenAICompatibleClient


class OpenAIClient(OpenAICompatibleClient):
    provider_name = "openai"
    is_local = False

    def __init__(self, *, model: str, base_url: str = "https://api.openai.com/v1",
                 api_key_env: str = "OPENAI_API_KEY", temperature: float = 0,
                 timeout_seconds: float = 60, transport: JSONTransport | None = None):
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise LLMClientError(
                f"Required API key environment variable {api_key_env!r} is not set.",
                code="MISSING_API_KEY",
            )
        super().__init__(base_url=base_url, model=model, api_key=api_key,
                         temperature=temperature, timeout_seconds=timeout_seconds,
                         transport=transport)
        self.api_key_env = api_key_env


__all__ = ["OpenAIClient"]
