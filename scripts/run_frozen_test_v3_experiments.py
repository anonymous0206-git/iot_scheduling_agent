#!/usr/bin/env python3
"""Run the experiment matrix over a benchmark whose topologies come from a catalogue.

``scripts/run_experiments.py`` resolves topologies with the built-in resolver,
which knows a single topology. This runner supplies a catalogue-aware resolver
instead: every topology named by the harness file is loaded from the catalogue
entry's JSON file and checked against the SHA-256 recorded there. Nothing in
``agentic_anex`` is modified; the same append-only ledger, systems, and seeds
are used, so a run started here can be resumed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from agentic_anex.experiments import (
    ProviderAgentBenchmarkSystem, RuleBasedBenchmarkSystem,
    load_jsonl, run_experiment_matrix,
)
from agentic_anex.llm_clients import ProviderConfig
from agentic_anex.schemas import NetworkInstance
from agentic_anex.topology_io import load_json_topology


class CatalogueError(ValueError):
    """The catalogue cannot supply the topologies the benchmark refers to."""


def _seeds(value: str) -> tuple[int, ...]:
    try:
        seeds = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("seeds must be comma-separated integers") from exc
    if not seeds or len(seeds) != len(set(seeds)):
        raise argparse.ArgumentTypeError("seeds must be nonempty and unique")
    return seeds


def catalogue_resolver(catalogue: Mapping[str, Mapping[str, Any]], *,
                       catalogue_dir: str | Path | None = None):
    """Build a ``topology_resolver`` that loads catalogue topologies by id."""
    base = Path(catalogue_dir) if catalogue_dir is not None else Path.cwd()
    cache: dict[str, NetworkInstance] = {}

    def resolve(topology_id: str | None) -> NetworkInstance | None:
        if topology_id is None:
            return None
        if topology_id in cache:
            return cache[topology_id]
        entry = catalogue.get(topology_id)
        if entry is None:
            raise CatalogueError(f"topology {topology_id!r} is not in the catalogue")
        declared_path = entry.get("path")
        if not isinstance(declared_path, str) or not declared_path.strip():
            raise CatalogueError(f"catalogue entry {topology_id!r} has no 'path'")
        path = Path(declared_path)
        if not path.is_absolute():
            path = base / path
        if not path.is_file():
            raise CatalogueError(f"topology file for {topology_id!r} not found: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        declared_sha = entry.get("sha256")
        if isinstance(declared_sha, str) and declared_sha != digest:
            raise CatalogueError(
                f"topology {path} sha256 {digest} does not match the catalogue entry "
                f"{declared_sha}")
        instance = load_json_topology(path)
        if instance.name != topology_id:
            raise CatalogueError(f"topology {path} is named {instance.name!r}, not "
                                 f"{topology_id!r}")
        cache[topology_id] = instance
        return instance

    return resolve


def check_coverage(items, catalogue: Mapping[str, Any]) -> list[str]:
    """Topology ids the benchmark refers to that the catalogue does not hold."""
    referenced = {item.get("topology_id") for item in items}
    return sorted(str(name) for name in referenced - {None} if name not in catalogue)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--benchmark", required=True,
                        help="harness JSONL exported from a sealed benchmark")
    parser.add_argument("--topology-catalogue", required=True,
                        help="catalogue JSON mapping topology_id to path and sha256")
    parser.add_argument("--catalogue-dir", default=None,
                        help="directory relative catalogue paths resolve against "
                             "(default: the working directory)")
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
    parser.add_argument("--timeout-seconds", type=float, default=600)
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
            systems.append(ProviderAgentBenchmarkSystem(ProviderConfig(
                provider=args.provider, model=args.model, base_url=args.base_url,
                api_key_env=args.api_key_env, temperature=args.temperature,
                timeout_seconds=args.timeout_seconds, max_retries=args.max_retries)))
        except (TypeError, ValueError) as exc:
            parser.error(str(exc))

    catalogue = json.loads(Path(args.topology_catalogue).read_text(encoding="utf-8"))
    if not isinstance(catalogue, dict) or not catalogue:
        print(json.dumps({"status": "refused",
                          "problems": ["topology catalogue must be a non-empty object"]},
                         indent=2))
        return 1
    items = load_jsonl(args.benchmark)
    missing = check_coverage(items, catalogue)
    if missing:
        print(json.dumps({"status": "refused", "problems": [
            f"benchmark refers to topologies missing from the catalogue: {missing}"]}, indent=2))
        return 1
    resolver = catalogue_resolver(catalogue, catalogue_dir=args.catalogue_dir)
    try:
        summary = run_experiment_matrix(items, systems, args.seeds, args.raw_output,
                                        topology_resolver=resolver)
    except CatalogueError as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1
    print(json.dumps({"status": "completed", "raw_output": args.raw_output,
                      "topologies_available": len(catalogue), **summary},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
