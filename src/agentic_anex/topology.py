from __future__ import annotations

import copy
import random

from .legacy import gentopo


def generate_connected_topology(
    *,
    node_count: int,
    x_range: int,
    y_range: int,
    communication_range: float,
    working_period: int,
    active_slots_per_node: int,
    seed: int,
    max_attempts: int = 1_000,
):
    """Generate a connected legacy topology reproducibly.

    This intentionally preserves the legacy active-slot sampling behavior,
    which samples from ``range(0, working_period - 1)`` and therefore excludes
    the final slot. The behavior is recorded for regression compatibility and
    should be revisited before the final experimental freeze.
    """
    if node_count < 2:
        raise ValueError("node_count must be at least 2")
    if not 1 <= active_slots_per_node < working_period:
        raise ValueError("active_slots_per_node must be in [1, working_period-1]")

    random.seed(seed)
    for attempt in range(max_attempts):
        nodes = gentopo.random_rect(
            num_node=node_count,
            x_range=x_range,
            y_range=y_range,
            comm_range=communication_range,
            time_slot=working_period,
            active_slot_no=active_slots_per_node,
        )
        if gentopo.build_bfs(copy.deepcopy(nodes)):
            return nodes, attempt
    raise RuntimeError(f"failed to generate a connected topology in {max_attempts} attempts")

