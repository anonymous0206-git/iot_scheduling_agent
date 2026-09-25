"""User-facing multi-provider runtime for bounded Agentic ANEX orchestration."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .llm_clients import MockLLMClient, ProviderConfig, create_llm_client
from .orchestration import Orchestrator, RequirementAgent
from .schemas import DomainError, SchemaError
from .topology_io import load_json_topology
from .visualization import render_interactive_schedule, save_visualization
from .workflows.rule_based import RuleBasedRequest, process_request


def _read_config(path: str | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaError("could not read provider config JSON", path="config",
                          code="INVALID_PROVIDER_CONFIG_JSON") from exc
    if not isinstance(data, Mapping):
        raise SchemaError("provider config must be a JSON object", path="config",
                          code="INVALID_PROVIDER_CONFIG_JSON")
    return dict(data)


def _provider_config(args: argparse.Namespace) -> ProviderConfig:
    values = _read_config(args.config)
    cli_values = {
        "provider": args.provider, "model": args.model, "base_url": args.base_url,
        "api_key_env": args.api_key_env, "temperature": args.temperature,
        "timeout_seconds": args.timeout_seconds, "max_retries": args.max_retries,
        "seed": args.seed,
    }
    values.update({key: value for key, value in cli_values.items() if value is not None})
    if "provider" not in values:
        raise SchemaError(
            "select --provider, provide it in --config, or use --rule-based",
            path="provider", code="MISSING_PROVIDER",
        )
    if "model" not in values and values["provider"] == "mock":
        values["model"] = "deterministic-mock"
    return ProviderConfig.from_dict(values)


def _mock_decision(network: Any) -> dict[str, Any]:
    return {
        "status": "EXECUTE",
        "decision_summary": "Deterministic mock accepted the Paper 1 request.",
        "request": {
            "channels": 2, "interference_ratio": 1.0,
            "workload": "one_shot", "objective": "minimize_latency", "seed": 0,
            "collision_model": "legacy_neighbor", "latency_target_slots": None,
        },
        "clarification_questions": [],
        "approved_tool_calls": [
            "inspect_network", "run_anex", "validate_schedule", "measure_schedule",
        ],
    }


def _safe_runtime(config: ProviderConfig, wall_time_ms: float, retry_count: int,
                  error: Mapping[str, Any] | None, model_calls: int = 0,
                  token_totals: Mapping[str, int] | None = None,
                  is_local: bool | None = None) -> dict[str, Any]:
    return {
        "provider": config.provider, "model": config.model,
        "base_url": config.base_url, "api_key_env": config.api_key_env,
        "temperature": config.temperature, "timeout_seconds": config.timeout_seconds,
        "max_retries": config.max_retries, "seed": config.seed,
        "local": is_local,
        "wall_time_ms": round(wall_time_ms, 3), "retry_count": retry_count,
        "model_calls": model_calls, "tokens": dict(token_totals or {}),
        "error_category": error.get("category") if error else None,
        "credentials_persisted": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run bounded multi-provider Agentic ANEX")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--provider", choices=("mock", "ollama", "openai_compatible", "openai"))
    selection.add_argument("--rule-based", action="store_true",
                           help="use the deterministic rule-based requirement processor")
    parser.add_argument("--model"); parser.add_argument("--base-url")
    parser.add_argument("--api-key-env"); parser.add_argument("--temperature", type=float)
    parser.add_argument("--timeout-seconds", type=float); parser.add_argument("--max-retries", type=int)
    parser.add_argument("--seed", type=int); parser.add_argument("--config")
    parser.add_argument("--network", required=True); parser.add_argument("--request", required=True)
    parser.add_argument("--output"); parser.add_argument("--visualization-output")
    return parser


def _rule_based_request(user_text: str, network: Any) -> RuleBasedRequest:
    """Extract only explicitly stated Paper 1 intent for the rule baseline."""
    normalized = user_text.lower().replace("_", " ").replace("-", " ")
    workload = "one_shot" if re.search(r"\bone\s+shot\b", normalized) else None
    objective = None
    if re.search(r"\b(minimi[sz]e|minimum)\s+latency\b", normalized):
        objective = "minimize_latency"
    elif re.search(r"\b(minimi[sz]e|optimi[sz]e|minimum)\s+energy\b", normalized):
        objective = "energy_optimization"
    return RuleBasedRequest(topology=network, workload=workload, objective=objective)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        network = load_json_topology(args.network)
        started = time.monotonic()
        if args.rule_based:
            if args.config:
                raise SchemaError("--config cannot be combined with --rule-based",
                                  code="CONFLICTING_RUNTIME_SELECTION")
            report = process_request(_rule_based_request(args.request, network))
            wall_time_ms = (time.monotonic() - started) * 1000
            runtime = {
                "provider": "rule_based", "model": None, "base_url": None,
                "api_key_env": None, "temperature": None, "timeout_seconds": None,
                "max_retries": 0, "seed": 0, "local": True,
                "wall_time_ms": round(wall_time_ms, 3), "retry_count": 0,
                "model_calls": 0, "tokens": {}, "error_category": (
                    report.error.get("category") if report.error else None
                ), "credentials_persisted": False,
            }
        else:
            config = _provider_config(args)
            client = create_llm_client(config)
            # The offline mock is deliberately deterministic and never represents
            # a production parser or an alternate scheduler.
            if isinstance(client, MockLLMClient):
                client = MockLLMClient([_mock_decision(network)])
            report = Orchestrator(
                RequirementAgent(client, max_retries=config.max_retries)
            ).run(args.request, network)
            wall_time_ms = (time.monotonic() - started) * 1000
            token_totals: dict[str, int] = {}
            for log in report.llm_logs:
                for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = log.model_metadata.get(name)
                    if isinstance(value, int) and not isinstance(value, bool):
                        token_totals[name] = token_totals.get(name, 0) + value
            runtime = _safe_runtime(
                config, wall_time_ms, report.retry_count, report.error,
                len(report.llm_logs), token_totals, is_local=client.is_local,
            )
        document = {
            "report_format": "agentic_anex.multi_provider_orchestration.v1",
            "runtime": runtime,
            "orchestration": report.to_dict(),
        }
        if args.visualization_output:
            if report.status != "EXECUTE" or report.result is None \
                    or report.final_validation is None or not report.final_validation.valid:
                document["visualization"] = {
                    "path": str(args.visualization_output), "status": "not_created",
                    "reason": "VISUALIZATION_REQUIRES_VALID_SCHEDULE",
                }
            else:
                artifact = render_interactive_schedule(
                    network, report.result.schedule, validation=report.final_validation,
                )
                save_visualization(artifact, args.visualization_output)
                document["visualization"] = {
                    "path": str(args.visualization_output), "status": "created",
                    "kind": artifact.kind,
                    "input_hash": artifact.trace["input_hash"] if artifact.trace else None,
                }
        encoded = json.dumps(document, sort_keys=True, indent=2)
        if args.output:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
        else:
            print(encoded)
        return 0 if report.status == "EXECUTE" else 2
    except (DomainError, OSError) as exc:
        error = exc.to_dict() if isinstance(exc, DomainError) else {
            "category": "io_error", "code": type(exc).__name__, "message": str(exc),
        }
        print(json.dumps({"status": "ERROR", "error": error}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
