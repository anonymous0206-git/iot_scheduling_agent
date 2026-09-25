#!/usr/bin/env python3
"""Deterministic scheduling scalability experiment over a topology catalogue.

For every topology in a catalogue built by ``scripts/build_topology_catalogue.py``
and every requested channel count, run the legacy ANEX scheduler through the
typed wrapper (alpha = 1, the model the legacy code enforces), validate the
schedule with the independent validator under ``legacy_neighbor``, and measure
its latency. No language model is involved.

Outputs (write-once, in ``--output-dir``):

  runs.csv              one row per topology and channel count
  summary.csv           mean, sd, 95% CI, min, max, validity per (node_count, channels)
  paired_bootstrap.json latency difference of each channel count against the
                        reference count, paired by topology, with a seeded
                        bootstrap confidence interval
  manifest.json         catalogue hash, settings, output hashes, timestamps
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from agentic_anex.models import AnexConfig
from agentic_anex.tools import ValidationMode, measure_schedule, run_anex, validate_schedule
from agentic_anex.topology_io import load_json_topology

EXPERIMENT_FORMAT = "agentic_anex.topology_scaling_experiment.v1"
RUN_COLUMNS = [
    "topology_id", "node_count", "generation_seed", "average_degree", "max_bfs_layer",
    "channels", "latency_slots", "max_timeslot_index", "valid", "violations",
    "used_channels", "scheduled_transmissions", "anex_seconds", "validate_seconds",
]
SUMMARY_COLUMNS = [
    "node_count", "channels", "topologies", "latency_mean", "latency_sd", "latency_ci95",
    "latency_min", "latency_max", "valid_rate", "used_channels_mean", "anex_seconds_mean",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_experiment(*, catalogue_path: str | Path, channels: Sequence[int],
                   reference_channels: int = 2, bootstrap_samples: int = 10_000,
                   bootstrap_seed: int = 0) -> dict[str, Any]:
    catalogue_path = Path(catalogue_path)
    catalogue = json.loads(catalogue_path.read_text(encoding="utf-8"))
    directory = catalogue_path.parent
    channel_list = sorted(set(int(c) for c in channels))
    if not channel_list or any(c < 1 for c in channel_list):
        raise ValueError("channels must be positive integers")
    if reference_channels not in channel_list:
        raise ValueError("reference_channels must be one of the requested channel counts")
    rows: list[dict[str, Any]] = []
    entries = sorted(catalogue["topologies"].values(),
                     key=lambda e: (e["node_count"], e["generation_seed"]))
    for entry in entries:
        path = directory / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"topology file {path} does not match the catalogue hash")
        instance = load_json_topology(path)
        for channel_count in channel_list:
            config = AnexConfig(working_period=entry["working_period"], channels=channel_count,
                                communication_range=float(entry["communication_range"]),
                                interference_ratio=1.0, seed=entry["generation_seed"])
            started = time.perf_counter()
            result = run_anex(instance, config)
            anex_seconds = time.perf_counter() - started
            started = time.perf_counter()
            report = validate_schedule(instance, result.schedule, ValidationMode(
                collision_model="legacy_neighbor", channels=channel_count, interference_ratio=1.0))
            validate_seconds = time.perf_counter() - started
            metrics = measure_schedule(instance, result.schedule).to_dict()
            rows.append({
                "topology_id": entry["topology_id"],
                "node_count": entry["node_count"],
                "generation_seed": entry["generation_seed"],
                "average_degree": entry["average_degree"],
                "max_bfs_layer": entry["max_bfs_layer"],
                "channels": channel_count,
                "latency_slots": metrics["latency_slots"],
                "max_timeslot_index": metrics["max_timeslot_index"],
                "valid": bool(report.valid),
                "violations": len(report.violations),
                "used_channels": len(metrics.get("used_channels", [])),
                "scheduled_transmissions": metrics.get("scheduled_transmissions"),
                "anex_seconds": round(anex_seconds, 6),
                "validate_seconds": round(validate_seconds, 6),
            })
    return {
        "rows": rows,
        "summary": summarize(rows),
        "paired_bootstrap": paired_bootstrap(rows, reference_channels, bootstrap_samples,
                                            bootstrap_seed),
        "settings": {
            "catalogue": str(catalogue_path),
            "catalogue_sha256": sha256_file(catalogue_path),
            "catalogue_format": catalogue.get("catalogue_format"),
            "channels": channel_list,
            "reference_channels": reference_channels,
            "interference_ratio": 1.0,
            "collision_model": "legacy_neighbor",
            "bootstrap_samples": bootstrap_samples,
            "bootstrap_seed": bootstrap_seed,
            "topologies": len(entries),
        },
    }


def summarize(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["node_count"], row["channels"])].append(row)
    summary = []
    for (node_count, channel_count), group in sorted(grouped.items()):
        latencies = [row["latency_slots"] for row in group]
        sd = statistics.stdev(latencies) if len(latencies) > 1 else 0.0
        summary.append({
            "node_count": node_count,
            "channels": channel_count,
            "topologies": len(group),
            "latency_mean": round(statistics.mean(latencies), 3),
            "latency_sd": round(sd, 3),
            "latency_ci95": round(1.96 * sd / math.sqrt(len(latencies)), 3),
            "latency_min": min(latencies),
            "latency_max": max(latencies),
            "valid_rate": round(sum(row["valid"] for row in group) / len(group), 3),
            "used_channels_mean": round(statistics.mean(row["used_channels"] for row in group), 3),
            "anex_seconds_mean": round(statistics.mean(row["anex_seconds"] for row in group), 6),
        })
    return summary


def paired_bootstrap(rows: Sequence[dict[str, Any]], reference_channels: int,
                     samples: int, seed: int) -> list[dict[str, Any]]:
    by_key: dict[tuple[int, int], dict[str, int]] = defaultdict(dict)
    for row in rows:
        by_key[(row["node_count"], row["channels"])][row["topology_id"]] = row["latency_slots"]
    node_counts = sorted({key[0] for key in by_key})
    channel_counts = sorted({key[1] for key in by_key})
    rng = np.random.RandomState(seed)
    comparisons = []
    for node_count in node_counts:
        reference = by_key.get((node_count, reference_channels), {})
        for channel_count in channel_counts:
            if channel_count == reference_channels:
                continue
            candidate = by_key.get((node_count, channel_count), {})
            shared = sorted(set(reference) & set(candidate))
            if len(shared) < 2:
                continue
            diffs = np.array([candidate[t] - reference[t] for t in shared], dtype=float)
            indices = rng.randint(0, len(diffs), size=(samples, len(diffs)))
            means = diffs[indices].mean(axis=1)
            comparisons.append({
                "node_count": node_count,
                "channels": channel_count,
                "reference_channels": reference_channels,
                "pairs": len(shared),
                "mean_latency_difference": round(float(diffs.mean()), 3),
                "ci95": [round(float(np.percentile(means, 2.5)), 3),
                         round(float(np.percentile(means, 97.5)), 3)],
                "topologies_improved": int((diffs < 0).sum()),
                "topologies_unchanged": int((diffs == 0).sum()),
                "topologies_worse": int((diffs > 0).sum()),
            })
    return comparisons


def write_outputs(experiment: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    output_dir = Path(output_dir)
    paths = {name: output_dir / name for name in
             ("runs.csv", "summary.csv", "paired_bootstrap.json", "manifest.json")}
    existing = [str(path) for path in paths.values() if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite existing experiment outputs: {existing}")
    output_dir.mkdir(parents=True, exist_ok=True)
    with paths["runs.csv"].open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_COLUMNS)
        writer.writeheader()
        writer.writerows(experiment["rows"])
    with paths["summary.csv"].open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(experiment["summary"])
    paths["paired_bootstrap.json"].write_text(
        json.dumps(experiment["paired_bootstrap"], indent=2) + "\n", encoding="utf-8")
    manifest = {
        "experiment_format": EXPERIMENT_FORMAT,
        "completed_at_utc": _utc_now(),
        "settings": experiment["settings"],
        "runs": len(experiment["rows"]),
        "all_valid": all(row["valid"] for row in experiment["rows"]),
        "no_language_model_involved": True,
        "outputs": {
            name: {"path": name, "sha256": sha256_file(path)}
            for name, path in paths.items() if name != "manifest.json"
        },
    }
    paths["manifest.json"].write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalogue", required=True, help="catalogue.json of a topology catalogue")
    parser.add_argument("--channels", nargs="+", type=int, default=[1, 2, 3, 4, 5, 6, 7])
    parser.add_argument("--reference-channels", type=int, default=2)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    args = parser.parse_args()
    try:
        experiment = run_experiment(catalogue_path=args.catalogue, channels=args.channels,
                                    reference_channels=args.reference_channels,
                                    bootstrap_samples=args.bootstrap_samples,
                                    bootstrap_seed=args.bootstrap_seed)
        manifest = write_outputs(experiment, args.output_dir)
    except (FileExistsError, ValueError) as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1
    print(json.dumps({"status": "completed", "output_dir": str(args.output_dir),
                      "runs": manifest["runs"], "all_valid": manifest["all_valid"],
                      "summary": experiment["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
