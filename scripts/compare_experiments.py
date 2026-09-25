#!/usr/bin/env python3
"""Paired system comparison with reproducible bootstrap confidence intervals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentic_anex.experiments import load_experiment_records, paired_comparison


def _arm(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise argparse.ArgumentTypeError("arm must have SYSTEM:MODEL form")
    system, model = value.split(":", 1)
    if not system or not model:
        raise argparse.ArgumentTypeError("arm must have SYSTEM:MODEL form")
    return system, model


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare paired experiment records")
    parser.add_argument("--raw", required=True)
    parser.add_argument("--baseline", required=True, type=_arm)
    parser.add_argument("--candidate", required=True, type=_arm)
    parser.add_argument("--metric", required=True,
                        choices=("success", "action_accuracy", "latency_slots",
                                 "wall_time_seconds", "total_tokens", "retries"))
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = paired_comparison(
        load_experiment_records(args.raw), baseline=args.baseline,
        candidate=args.candidate, metric=args.metric,
        bootstrap_samples=args.bootstrap_samples, seed=args.seed,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        path = Path(args.output)
        if path.exists():
            raise FileExistsError(f"refusing to overwrite comparison output: {path}")
        path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
