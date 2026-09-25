#!/usr/bin/env python3
"""Run or safely resume the built-in Paper 1 experiment matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentic_anex.experiments import (
    ProviderAgentBenchmarkSystem, RuleBasedBenchmarkSystem,
    load_jsonl, run_experiment_matrix,
)
from agentic_anex.llm_clients import ProviderConfig


def _seeds(value: str) -> tuple[int, ...]:
    try:
        seeds = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("seeds must be comma-separated integers") from exc
    if not seeds or len(seeds) != len(set(seeds)):
        raise argparse.ArgumentTypeError("seeds must be nonempty and unique")
    return seeds


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reproducible Paper 1 experiments")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--raw-output", required=True,
                        help="Append-only JSONL ledger; existing records are never overwritten")
    parser.add_argument("--systems", default="rule_based",
                        help="Comma-separated systems: rule_based,llm_agent")
    parser.add_argument("--seeds", type=_seeds, default=(0,))
    parser.add_argument("--provider", choices=("ollama", "openai_compatible", "openai"))
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--max-retries", type=int, default=2)
    args = parser.parse_args()
    names = tuple(name.strip() for name in args.systems.split(",") if name.strip())
    unknown = sorted(set(names) - {"rule_based", "llm_agent"})
    if unknown:
        parser.error(f"unknown built-in systems: {unknown}")
    systems = [RuleBasedBenchmarkSystem() for name in names if name == "rule_based"]
    if "llm_agent" in names:
        if not args.provider or not args.model:
            parser.error("llm_agent requires --provider and --model")
        try:
            config = ProviderConfig(
                provider=args.provider, model=args.model, base_url=args.base_url,
                api_key_env=args.api_key_env, temperature=args.temperature,
                timeout_seconds=args.timeout_seconds, max_retries=args.max_retries,
            )
            systems.append(ProviderAgentBenchmarkSystem(config))
        except (TypeError, ValueError) as exc:
            parser.error(str(exc))
    summary = run_experiment_matrix(
        load_jsonl(args.benchmark), systems, args.seeds, args.raw_output
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
