#!/usr/bin/env python3
"""Check an OpenAI-style endpoint before spending a full benchmark run on it.

A frontier arm costs real money and 144 requests. Three things can make the
whole run useless, and all three are cheap to test first:

  * the API key environment variable is not set in the shell that runs the
    experiment (a login shell does not always read ``~/.bashrc``);
  * the model rejects ``temperature`` values other than 1, which the client
    always sends, and whose 400 the client's ``response_format`` fallback
    cannot repair;
  * the model does not support strict ``json_schema`` structured output, so
    every item silently falls back to ``json_object`` and the run is not
    comparable to the local arms.

This script exercises the real client, so whatever it reports is what the
experiment will do.

The API key is never printed, logged, or written to a file. The script reports
only whether the variable is set and how long the value is.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from typing import Any

from agentic_anex.llm_clients import ProviderConfig, create_llm_client
from agentic_anex.llm_clients.base import LLMClientError
from agentic_anex.orchestration import AGENT_DECISION_JSON_SCHEMA

# Probe with the schema the experiment actually sends. Probing with a simpler
# schema of the script's own invention is worse than not probing at all: a
# provider can accept a toy schema under strict mode and reject the real one,
# and the client's fallback then degrades every request of the real run to
# free-form JSON without failing.
PROBE_SCHEMA: dict[str, Any] = AGENT_DECISION_JSON_SCHEMA
PROBE_PROMPT = (
    "The approved channel count for this network is either 3 or 7 and the notes do "
    "not mark which one was approved. Plan one ANEX collection. Decide the status "
    "and, if you need something from the user, fill clarification_questions."
)


def list_models(base_url: str, api_key: str, contains: str | None,
                timeout: float) -> list[str] | str:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code} listing models"
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        return f"could not list models: {exc}"
    names = sorted(str(entry.get("id")) for entry in payload.get("data", [])
                   if isinstance(entry, dict) and entry.get("id"))
    if contains:
        names = [name for name in names if contains in name]
    return names


def probe(config: ProviderConfig) -> dict[str, Any]:
    try:
        client = create_llm_client(config)
    except LLMClientError as exc:
        return {"ok": False, "stage": "client_construction", "error": str(exc),
                "code": getattr(exc, "code", None)}
    try:
        response = client.generate_structured(prompt=PROBE_PROMPT,
                                              response_schema=PROBE_SCHEMA)
    except LLMClientError as exc:
        return {"ok": False, "stage": "generate_structured", "error": str(exc),
                "code": getattr(exc, "code", None)}
    except Exception as exc:  # transport errors surface as their own types
        return {"ok": False, "stage": "transport", "error": f"{type(exc).__name__}: {exc}"}
    metadata = dict(response.model_metadata)
    return {
        "ok": True,
        "structured_output_mode": metadata.get("structured_output_mode"),
        "strict_json_schema_supported": metadata.get("structured_output_mode") == "json_schema",
        "model_reported": metadata.get("model"),
        "temperature_accepted": config.temperature,
        "prompt_tokens": metadata.get("prompt_tokens"),
        "completion_tokens": metadata.get("completion_tokens"),
        "duration_ms": metadata.get("duration_ms"),
        "payload": dict(response.structured_output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", default="openai",
                        choices=("openai", "openai_compatible"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--list-models", action="store_true",
                        help="also list model ids the key can see")
    parser.add_argument("--filter", default=None,
                        help="only list model ids containing this substring")
    args = parser.parse_args()

    key = os.environ.get(args.api_key_env)
    report: dict[str, Any] = {
        "api_key_env": args.api_key_env,
        "api_key_set": bool(key),
        "api_key_length": len(key) if key else 0,
        "provider": args.provider,
        "model_requested": args.model,
        "temperature_requested": args.temperature,
    }
    if not key:
        report["problems"] = [
            f"{args.api_key_env} is not set in this shell. Export it in ~/.profile, "
            "then start a new shell; a login shell does not always read ~/.bashrc."]
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    base_url = args.base_url or ("https://api.openai.com/v1" if args.provider == "openai"
                                 else None)
    if base_url is None:
        parser.error("--base-url is required for openai_compatible")
    if args.list_models:
        report["models_visible"] = list_models(base_url, key, args.filter,
                                               args.timeout_seconds)

    report["probe"] = probe(ProviderConfig(
        provider=args.provider, model=args.model, base_url=args.base_url,
        api_key_env=args.api_key_env, temperature=args.temperature,
        timeout_seconds=args.timeout_seconds, max_retries=0))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["probe"].get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
