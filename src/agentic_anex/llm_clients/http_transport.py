"""Small injectable JSON HTTP transport shared by provider clients."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Mapping, Protocol

from .base import LLMClientError


class JSONTransport(Protocol):
    def __call__(self, *, url: str, payload: Mapping[str, Any],
                 headers: Mapping[str, str], timeout_seconds: float) -> Mapping[str, Any]: ...


class HTTPStatusError(LLMClientError):
    def __init__(self, status: int):
        code = "MODEL_UNAVAILABLE" if status == 404 else "HTTP_PROVIDER_ERROR"
        super().__init__(f"Provider returned HTTP status {status}.", code=code)
        self.status = status


def json_http_post(*, url: str, payload: Mapping[str, Any], headers: Mapping[str, str],
                   timeout_seconds: float) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url, data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", **dict(headers)}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise HTTPStatusError(exc.code) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise LLMClientError("Provider request timed out.", code="PROVIDER_TIMEOUT") from exc
    except (urllib.error.URLError, ConnectionError, OSError) as exc:
        raise LLMClientError("Provider is unavailable.", code="PROVIDER_UNAVAILABLE") from exc
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise LLMClientError("Provider returned malformed JSON.", code="MALFORMED_PROVIDER_RESPONSE") from exc
    if not isinstance(decoded, Mapping):
        raise LLMClientError("Provider response must be a JSON object.",
                             code="MALFORMED_PROVIDER_RESPONSE")
    return decoded


__all__ = ["JSONTransport", "HTTPStatusError", "json_http_post"]
