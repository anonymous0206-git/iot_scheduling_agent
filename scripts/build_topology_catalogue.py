#!/usr/bin/env python3
"""Generate a deterministic multi-size topology catalogue with the legacy ANEX generator.

Every topology comes from ``generate_network_instance``, the reproducible
wrapper around ``source/libs/gentopo.random_rect`` (isolated RNG, connectivity
enforced). Each one is saved as a JSON ``NetworkInstance`` next to its baseline
ANEX schedule (alpha = 1, the model the legacy code enforces), so network and
schedule can be rendered with ``python -m agentic_anex.visualization``. The
catalogue records public properties and SHA-256 hashes for every topology and
writes a pipeline-compatible subset for the language benchmark.

Outputs are write-once; an existing catalogue directory is never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from agentic_anex.models import AnexConfig
from agentic_anex.schemas import to_json
from agentic_anex.tools import ValidationMode, measure_schedule, run_anex, validate_schedule
from agentic_anex.topology_io import generate_network_instance, save_json_topology, topology_statistics

CATALOGUE_FORMAT = "agentic_anex.topology_catalogue.v1"
CATALOGUE_FILENAME = "catalogue.json"
LLM_CATALOGUE_FILENAME = "llm_catalogue.json"
ACTIVE_SLOT_MODE = "legacy_exclude_final_slot"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_catalogue(*, output_dir: str | Path, sizes: Sequence[int], samples: int, area: int,
                    communication_range: float, working_period: int, active_slots: int,
                    baseline_channels: int, prefix: str,
                    llm_sample_indices: Sequence[int]) -> dict[str, Any]:
    output_dir = Path(output_dir)
    catalogue_path = output_dir / CATALOGUE_FILENAME
    llm_path = output_dir / LLM_CATALOGUE_FILENAME
    for path in (catalogue_path, llm_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing catalogue file {path}")
    if samples < 1 or not sizes:
        raise ValueError("sizes must be non-empty and samples must be at least 1")
    if any(index < 0 or index >= samples for index in llm_sample_indices):
        raise ValueError("llm_sample_indices must lie within range(samples)")
    output_dir.mkdir(parents=True, exist_ok=True)
    topologies: dict[str, dict[str, Any]] = {}
    for node_count in sizes:
        for seed in range(samples):
            topology_id = f"{prefix}{node_count}_seed{seed}"
            path = output_dir / f"{topology_id}.json"
            schedule_path = output_dir / f"{topology_id}.baseline_schedule.json"
            if path.exists() or schedule_path.exists():
                raise FileExistsError(f"refusing to overwrite topology files for {topology_id}")
            instance = generate_network_instance(
                node_count=node_count, x_range=area, y_range=area,
                communication_range=communication_range, working_period=working_period,
                active_slots_per_node=active_slots, seed=seed, active_slot_mode=ACTIVE_SLOT_MODE,
                name=topology_id,
            )
            save_json_topology(instance, path)
            config = AnexConfig(working_period=working_period, channels=baseline_channels,
                                communication_range=float(communication_range),
                                interference_ratio=1.0, seed=seed)
            started = time.perf_counter()
            result = run_anex(instance, config)
            anex_seconds = time.perf_counter() - started
            report = validate_schedule(instance, result.schedule, ValidationMode(
                collision_model="legacy_neighbor", channels=baseline_channels,
                interference_ratio=1.0))
            metrics = measure_schedule(instance, result.schedule).to_dict()
            # The tool trace carries wall-clock timestamps; drop it so the saved
            # baseline schedule is byte-deterministic for a given topology.
            schedule_path.write_text(to_json(replace(result, trace=None), indent=2) + "\n",
                                     encoding="utf-8")
            stats = topology_statistics(instance)
            topologies[topology_id] = {
                "topology_id": topology_id,
                "path": path.name,
                "sha256": sha256_file(path),
                "baseline_schedule_path": schedule_path.name,
                "baseline_schedule_sha256": sha256_file(schedule_path),
                "node_count": node_count,
                "sink_id": instance.sink_id,
                "working_period": working_period,
                "communication_range": float(communication_range),
                "active_slots_per_node": active_slots,
                "active_slot_mode": ACTIVE_SLOT_MODE,
                "generation_seed": seed,
                "coordinate_domain": [0, area],
                "edge_count": stats.get("edge_count"),
                "average_degree": stats.get("average_degree"),
                "maximum_degree": stats.get("maximum_degree"),
                "density": stats.get("density"),
                "max_bfs_layer": stats.get("max_bfs_layer"),
                "baseline": {
                    "channels": baseline_channels,
                    "interference_ratio": 1.0,
                    "collision_model": "legacy_neighbor",
                    "max_timeslot_index": metrics.get("max_timeslot_index"),
                    "elapsed_latency_slots": metrics.get("latency_slots"),
                    "valid": bool(report.valid),
                    "violations": len(report.violations),
                    "anex_seconds": round(anex_seconds, 4),
                },
            }
    llm_subset = {
        topology_id: entry for topology_id, entry in topologies.items()
        if entry["generation_seed"] in set(llm_sample_indices)
    }
    catalogue = {
        "catalogue_format": CATALOGUE_FORMAT,
        "generated_at_utc": _utc_now(),
        "generator": {
            "function": "agentic_anex.topology_io.generate_network_instance",
            "legacy_source": "source/libs/gentopo.random_rect",
            "coordinate_domain": [0, area],
            "communication_range": float(communication_range),
            "working_period": working_period,
            "active_slots_per_node": active_slots,
            "active_slot_mode": ACTIVE_SLOT_MODE,
            "baseline_channels": baseline_channels,
            "interference_ratio": 1.0,
            "id_pattern": f"{prefix}{{node_count}}_seed{{generation_seed}}",
        },
        "sizes": list(sizes),
        "samples_per_size": samples,
        "llm_sample_indices": list(llm_sample_indices),
        "topologies": topologies,
    }
    catalogue_path.write_text(json.dumps(catalogue, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    llm_path.write_text(json.dumps(llm_subset, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return catalogue


def summarize(catalogue: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for node_count in catalogue["sizes"]:
        entries = [e for e in catalogue["topologies"].values() if e["node_count"] == node_count]
        latencies = [e["baseline"]["elapsed_latency_slots"] for e in entries]
        rows.append({
            "node_count": node_count,
            "topologies": len(entries),
            "average_degree_mean": round(statistics.mean(e["average_degree"] for e in entries), 2),
            "max_bfs_layer_range": [min(e["max_bfs_layer"] for e in entries),
                                    max(e["max_bfs_layer"] for e in entries)],
            "baseline_latency_mean": round(statistics.mean(latencies), 2),
            "baseline_latency_range": [min(latencies), max(latencies)],
            "all_baselines_valid": all(e["baseline"]["valid"] for e in entries),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--sizes", nargs="+", type=int, default=[50, 100, 150, 200, 250, 300])
    parser.add_argument("--samples", type=int, default=30, help="topologies per size (seeds 0..samples-1)")
    parser.add_argument("--area", type=int, default=100, help="square coordinate domain 0..area")
    parser.add_argument("--range", dest="communication_range", type=float, default=20.0)
    parser.add_argument("--working-period", type=int, default=10)
    parser.add_argument("--active-slots", type=int, default=2)
    parser.add_argument("--baseline-channels", type=int, default=2)
    parser.add_argument("--prefix", default="topo")
    parser.add_argument("--llm-samples", nargs="+", type=int, default=[0],
                        help="sample indices exported to llm_catalogue.json")
    args = parser.parse_args()
    try:
        catalogue = build_catalogue(
            output_dir=args.output_dir, sizes=args.sizes, samples=args.samples, area=args.area,
            communication_range=args.communication_range, working_period=args.working_period,
            active_slots=args.active_slots, baseline_channels=args.baseline_channels,
            prefix=args.prefix, llm_sample_indices=args.llm_samples,
        )
    except (FileExistsError, ValueError) as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1
    print(json.dumps({
        "status": "generated",
        "output_dir": str(args.output_dir),
        "topologies": len(catalogue["topologies"]),
        "llm_catalogue_entries": len(catalogue["llm_sample_indices"]) * len(catalogue["sizes"]),
        "summary": summarize(catalogue),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
