from __future__ import annotations

import argparse
import json

from .models import AnexConfig
from .runner import run_anex
from .topology import generate_connected_topology


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a reproducible ANEX baseline")
    parser.add_argument("--nodes", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--working-period", type=int, default=10)
    parser.add_argument("--active-slots", type=int, default=2)
    parser.add_argument("--channels", type=int, default=2)
    parser.add_argument("--communication-range", type=float, default=18.0)
    parser.add_argument("--interference-ratio", type=float, default=1.5)
    parser.add_argument("--area", type=int, default=40)
    args = parser.parse_args()

    nodes, attempt = generate_connected_topology(
        node_count=args.nodes,
        x_range=args.area,
        y_range=args.area,
        communication_range=args.communication_range,
        working_period=args.working_period,
        active_slots_per_node=args.active_slots,
        seed=args.seed,
    )
    config = AnexConfig(
        working_period=args.working_period,
        channels=args.channels,
        communication_range=args.communication_range,
        interference_ratio=args.interference_ratio,
        seed=args.seed,
    )
    result = run_anex(nodes, config)
    payload = result.to_dict()
    payload["metadata"]["topology_generation_attempt"] = attempt
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

