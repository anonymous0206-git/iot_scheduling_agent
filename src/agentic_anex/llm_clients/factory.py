"""Validated provider configuration and explicit client construction."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, Mapping
from urllib.parse import urlparse

from ..schemas import JsonSchema, SchemaError
from .base import LLMClient
from .mock import MockLLMClient
from .ollama_client import OllamaClient
from .openai_client import OpenAIClient
from .openai_compatible_client import OpenAICompatibleClient

ProviderName = Literal["mock", "ollama", "openai_compatible", "openai"]
_PROVIDERS = frozenset(("mock", "ollama", "openai_compatible", "openai"))


@dataclass(frozen=True)
class ProviderConfig(JsonSchema):
    provider: ProviderName
    model: str
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0
    timeout_seconds: float = 60
    max_retries: int = 2
    seed: int | None = None

    def __post_init__(self) -> None:
        if self.provider not in _PROVIDERS:
            raise SchemaError(f"unknown provider {self.provider!r}", path="provider",
                              code="UNKNOWN_PROVIDER")
        if not isinstance(self.model, str) or not self.model.strip():
            raise SchemaError("must be a nonempty model name", path="model",
                              code="INVALID_MODEL")
        if self.base_url is not None:
            if not isinstance(self.base_url, str):
                raise SchemaError("must be an HTTP(S) URL", path="base_url", code="INVALID_URL")
            parsed = urlparse(self.base_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc \
                    or parsed.username is not None or parsed.password is not None:
                raise SchemaError("must be an HTTP(S) URL without embedded credentials",
                                  path="base_url", code="INVALID_URL")
        if not isinstance(self.api_key_env, str) or not self.api_key_env.strip():
            raise SchemaError("must be a nonempty environment-variable name",
                              path="api_key_env", code="INVALID_API_KEY_ENV")
        if isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float)) \
                or self.temperature < 0:
            raise SchemaError("must be a non-negative number", path="temperature",
                              code="INVALID_TEMPERATURE")
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ) or self.timeout_seconds <= 0:
            raise SchemaError("must be positive", path="timeout_seconds", code="INVALID_TIMEOUT")
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int) \
                or not 0 <= self.max_retries <= 2:
            raise SchemaError("must be in [0, 2]", path="max_retries", code="INVALID_MAX_RETRIES")
        if self.seed is not None and (isinstance(self.seed, bool) or not isinstance(self.seed, int)):
            raise SchemaError("must be an integer or null", path="seed", code="INVALID_SEED")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProviderConfig":
        if not isinstance(data, Mapping):
            raise SchemaError("provider config must be an object", code="INVALID_PROVIDER_CONFIG")
        allowed = {"provider", "model", "base_url", "api_key_env", "temperature",
                   "timeout_seconds", "max_retries", "seed"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise SchemaError(f"unknown provider config fields: {unknown}",
                              code="UNKNOWN_PROVIDER_CONFIG_FIELD")
        try:
            return cls(**dict(data))
        except TypeError as exc:
            raise SchemaError("provider and model are required", code="MISSING_PROVIDER_CONFIG_FIELD") from exc


def create_llm_client(config: ProviderConfig) -> LLMClient:
    """Create exactly the requested provider; never fall back."""
    if not isinstance(config, ProviderConfig):
        raise SchemaError("must be a ProviderConfig", code="INVALID_PROVIDER_CONFIG")
    if config.provider == "mock":
        return MockLLMClient([])
    if config.provider == "ollama":
        return OllamaClient(
            model=config.model, base_url=config.base_url or "http://localhost:11434",
            temperature=config.temperature, timeout_seconds=config.timeout_seconds,
            seed=config.seed,
        )
    if config.provider == "openai_compatible":
        if config.base_url is None:
            raise SchemaError("is required for openai_compatible", path="base_url",
                              code="MISSING_BASE_URL")
        api_key = os.environ.get(config.api_key_env)
        return OpenAICompatibleClient(
            base_url=config.base_url, model=config.model, api_key=api_key,
            temperature=config.temperature, timeout_seconds=config.timeout_seconds,
        )
    if config.provider == "openai":
        return OpenAIClient(
            model=config.model, base_url=config.base_url or "https://api.openai.com/v1",
            api_key_env=config.api_key_env, temperature=config.temperature,
            timeout_seconds=config.timeout_seconds,
        )
    raise SchemaError("unknown provider", code="UNKNOWN_PROVIDER")


__all__ = ["ProviderName", "ProviderConfig", "create_llm_client"]
