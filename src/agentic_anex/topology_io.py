"""Validated topology loading, generation, statistics, and legacy conversion."""

from __future__ import annotations

import json
import math
import random
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .schemas import InfeasibleNetworkError, NetworkInstance, NodeSpec, ScheduleEntry, SchemaError


ActiveSlotMode = Literal["legacy_exclude_final_slot", "full_period"]
LEGACY_ACTIVE_SLOT_MODE: ActiveSlotMode = "legacy_exclude_final_slot"
FULL_PERIOD_ACTIVE_SLOT_MODE: ActiveSlotMode = "full_period"


def topology_statistics(instance: NetworkInstance) -> dict[str, int | float]:
    """Return undirected graph statistics, including sink-rooted BFS depth."""
    by_id = {node.id: node for node in instance.nodes}
    node_count = len(instance.nodes)
    degrees = [len(node.neighbor_ids) for node in instance.nodes]
    edge_count = sum(degrees) // 2
    distances = {instance.sink_id: 0}
    frontier = [instance.sink_id]
    while frontier:
        current = frontier.pop(0)
        for neighbor in by_id[current].neighbor_ids:
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                frontier.append(neighbor)
    max_bfs_layer = max(distances.values(), default=0)
    possible_edges = node_count * (node_count - 1) / 2
    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "average_degree": sum(degrees) / node_count,
        "maximum_degree": max(degrees, default=0),
        "density": edge_count / possible_edges if possible_edges else 0.0,
        # For Paper 1 this is the maximum sink-rooted hop distance, rather than
        # the maximum shortest path over every possible pair of nodes.
        "hop_diameter": max_bfs_layer,
        "max_bfs_layer": max_bfs_layer,
    }


def _with_statistics(instance: NetworkInstance) -> NetworkInstance:
    metadata = dict(instance.metadata)
    metadata["topology_statistics"] = topology_statistics(instance)
    return replace(instance, metadata=metadata)


def _config_value(config: Any, name: str) -> Any:
    if isinstance(config, Mapping):
        if name not in config:
            raise SchemaError("required configuration value is missing", path=name, code="MISSING_CONFIG_FIELD")
        return config[name]
    if not hasattr(config, name):
        raise SchemaError("required configuration value is missing", path=name, code="MISSING_CONFIG_FIELD")
    return getattr(config, name)


def _parse_legacy_lines(path: Path) -> list[tuple[int, float, float, tuple[int, ...]]]:
    records: list[tuple[int, float, float, tuple[int, ...]]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SchemaError(f"cannot read topology file: {exc}", path=str(path), code="TOPOLOGY_READ_ERROR") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        # Published repository files use a textual first line such as
        # ``D 20 L 40``.  Only an explicit nonnumeric header is skipped.
        if not records and fields[0].upper() in {"D", "N", "HEADER"}:
            continue
        if len(fields) < 4:
            raise SchemaError(
                "expected: node_id x y active_slot [active_slot ...]",
                path=f"{path}:{line_number}", code="INVALID_LEGACY_TOPOLOGY_LINE",
            )
        try:
            node_id = int(fields[0])
            x, y = float(fields[1]), float(fields[2])
            active_slots = tuple(int(value) for value in fields[3:])
        except ValueError as exc:
            raise SchemaError(
                "node ID and active slots must be integers; coordinates must be numeric",
                path=f"{path}:{line_number}", code="INVALID_LEGACY_TOPOLOGY_VALUE",
            ) from exc
        records.append((node_id, x, y, active_slots))
    if not records:
        raise SchemaError("topology file contains no nodes", path=str(path), code="EMPTY_TOPOLOGY_FILE")
    return records


def _neighbors_from_coordinates(
    records: Sequence[tuple[int, float, float, tuple[int, ...]]], communication_range: float
) -> dict[int, list[int]]:
    neighbors = {record[0]: [] for record in records}
    for index, (left_id, left_x, left_y, _) in enumerate(records):
        for right_id, right_x, right_y, _ in records[index + 1:]:
            if math.hypot(left_x - right_x, left_y - right_y) <= communication_range:
                neighbors[left_id].append(right_id)
                neighbors[right_id].append(left_id)
    return neighbors


def load_legacy_topology(path: str | Path, config: Any) -> NetworkInstance:
    """Load the published whitespace format without silently renumbering IDs."""
    source_path = Path(path)
    working_period = _config_value(config, "working_period")
    communication_range = _config_value(config, "communication_range")
    sink_id = getattr(config, "sink_id", 0) if not isinstance(config, Mapping) else config.get("sink_id", 0)
    if isinstance(communication_range, bool) or not isinstance(communication_range, (int, float)):
        raise SchemaError("must be numeric", path="communication_range", code="INVALID_COMMUNICATION_RANGE")
    if not math.isfinite(communication_range) or communication_range <= 0:
        raise SchemaError("must be positive and finite", path="communication_range", code="INVALID_COMMUNICATION_RANGE")
    records = _parse_legacy_lines(source_path)
    neighbors = _neighbors_from_coordinates(records, communication_range)
    instance = NetworkInstance(
        nodes=tuple(
            NodeSpec(node_id, x, y, active_slots, tuple(sorted(neighbors[node_id])))
            for node_id, x, y, active_slots in records
        ),
        sink_id=sink_id,
        working_period=working_period,
        communication_range=communication_range,
        name=source_path.stem,
        metadata={"format": "legacy_text", "source_path": str(source_path)},
    )
    return _with_statistics(instance)


def load_json_topology(path: str | Path) -> NetworkInstance:
    source_path = Path(path)
    try:
        payload = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SchemaError(f"cannot read topology file: {exc}", path=str(source_path), code="TOPOLOGY_READ_ERROR") from exc
    instance = NetworkInstance.from_json(payload)
    return _with_statistics(instance)


def save_json_topology(instance: NetworkInstance, path: str | Path) -> None:
    if not isinstance(instance, NetworkInstance):
        raise SchemaError("must be a NetworkInstance", path="instance", code="INVALID_NETWORK")
    destination = Path(path)
    try:
        destination.write_text(instance.to_json(indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, TypeError) as exc:
        raise SchemaError(f"cannot write topology file: {exc}", path=str(destination), code="TOPOLOGY_WRITE_ERROR") from exc


def generate_network_instance(
    *,
    node_count: int,
    x_range: int,
    y_range: int,
    communication_range: float,
    working_period: int,
    active_slots_per_node: int,
    seed: int,
    sink_id: int = 0,
    active_slot_mode: ActiveSlotMode = LEGACY_ACTIVE_SLOT_MODE,
    max_attempts: int = 1_000,
    name: str | None = None,
) -> NetworkInstance:
    """Generate a connected network using isolated, reproducible RNG state."""
    for field_name, value in (("node_count", node_count), ("x_range", x_range),
                              ("y_range", y_range), ("working_period", working_period),
                              ("active_slots_per_node", active_slots_per_node),
                              ("max_attempts", max_attempts)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise SchemaError("must be an integer", path=field_name, code="INVALID_INTEGER")
    if node_count < 2:
        raise SchemaError("must be at least 2", path="node_count", code="INVALID_NODE_COUNT")
    if x_range < 0 or y_range < 0:
        raise SchemaError("coordinate ranges must be non-negative", code="INVALID_COORDINATE_RANGE")
    if node_count > (x_range + 1) * (y_range + 1):
        raise InfeasibleNetworkError(
            "coordinate grid has fewer unique positions than requested nodes",
            path="node_count", code="INSUFFICIENT_UNIQUE_POSITIONS",
        )
    if working_period <= 0:
        raise SchemaError("must be positive", path="working_period", code="INVALID_WORKING_PERIOD")
    if max_attempts < 1:
        raise SchemaError("must be at least 1", path="max_attempts", code="INVALID_MAX_ATTEMPTS")
    if active_slot_mode not in {LEGACY_ACTIVE_SLOT_MODE, FULL_PERIOD_ACTIVE_SLOT_MODE}:
        raise SchemaError(
            "must be legacy_exclude_final_slot or full_period",
            path="active_slot_mode", code="INVALID_ACTIVE_SLOT_MODE",
        )
    slot_population = working_period - 1 if active_slot_mode == LEGACY_ACTIVE_SLOT_MODE else working_period
    if not 1 <= active_slots_per_node <= slot_population:
        raise SchemaError(
            f"must be in [1, {slot_population}] for {active_slot_mode}",
            path="active_slots_per_node", code="INVALID_ACTIVE_SLOT_COUNT",
        )
    if isinstance(communication_range, bool) or not isinstance(communication_range, (int, float)):
        raise SchemaError("must be numeric", path="communication_range", code="INVALID_COMMUNICATION_RANGE")
    if not math.isfinite(communication_range) or communication_range <= 0:
        raise SchemaError("must be positive and finite", path="communication_range", code="INVALID_COMMUNICATION_RANGE")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SchemaError("must be an integer", path="seed", code="INVALID_INTEGER")
    if isinstance(sink_id, bool) or not isinstance(sink_id, int):
        raise SchemaError("must be an integer", path="sink_id", code="INVALID_INTEGER")
    if sink_id != 0:
        # The generator follows the published placement/sequence, whose sink is
        # node zero. Accepting another value would imply a silent relabeling.
        raise SchemaError("generated sink ID must be 0", path="sink_id", code="UNSUPPORTED_GENERATED_SINK_ID")

    rng = random.Random(seed)
    slot_domain = range(slot_population)
    for attempt in range(max_attempts):
        records: list[tuple[int, float, float, tuple[int, ...]]] = [
            (0, x_range / 2, y_range / 2, tuple(rng.sample(slot_domain, active_slots_per_node)))
        ]
        occupied = {(records[0][1], records[0][2])}
        for node_id in range(1, node_count):
            while True:
                position = (rng.randint(0, x_range), rng.randint(0, y_range))
                if position not in occupied:
                    occupied.add(position)
                    break
            records.append((
                node_id, float(position[0]), float(position[1]),
                tuple(rng.sample(slot_domain, active_slots_per_node)),
            ))
        neighbors = _neighbors_from_coordinates(records, communication_range)
        specs = tuple(
            NodeSpec(node_id, x, y, slots, tuple(neighbors[node_id]))
            for node_id, x, y, slots in records
        )
        try:
            instance = NetworkInstance(
                nodes=specs,
                sink_id=sink_id,
                working_period=working_period,
                communication_range=communication_range,
                name=name,
                metadata={
                    "generation_seed": seed,
                    "generation_attempt": attempt,
                    "active_slot_mode": active_slot_mode,
                },
            )
        except InfeasibleNetworkError:
            continue
        return _with_statistics(instance)
    raise InfeasibleNetworkError(
        f"failed to generate a sink-connected topology in {max_attempts} attempts",
        path="generation", code="GENERATION_ATTEMPTS_EXHAUSTED",
    )


def network_instance_to_legacy_nodes(instance: NetworkInstance) -> list[Any]:
    """Create fresh mutable legacy nodes only after schema validation succeeds."""
    if not isinstance(instance, NetworkInstance):
        raise SchemaError("must be a NetworkInstance", path="instance", code="INVALID_NETWORK")
    from libs.node import Node

    by_id = {node.id: node for node in instance.nodes}
    legacy_nodes = []
    for node_id in range(len(instance.nodes)):
        spec = by_id[node_id]
        legacy = Node(spec.id, spec.x, spec.y, list(spec.active_slots))
        legacy.neighborIDs = list(spec.neighbor_ids)
        legacy_nodes.append(legacy)
    return legacy_nodes


def legacy_nodes_to_network_instance(
    nodes: Sequence[Any],
    *,
    working_period: int,
    communication_range: float,
    sink_id: int = 0,
    name: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> NetworkInstance:
    """Snapshot legacy topology fields; scheduling/tree state is not imported."""
    try:
        specs = tuple(
            NodeSpec(
                id=node.ID,
                x=node.x,
                y=node.y,
                active_slots=tuple(node.active_slot),
                neighbor_ids=tuple(node.neighborIDs),
            )
            for node in nodes
        )
    except AttributeError as exc:
        raise SchemaError(
            f"legacy node is missing required topology field: {exc}",
            path="nodes", code="INVALID_LEGACY_NODE",
        ) from exc
    instance = NetworkInstance(
        nodes=specs,
        sink_id=sink_id,
        working_period=working_period,
        communication_range=communication_range,
        name=name,
        metadata=dict(metadata or {}),
    )
    return _with_statistics(instance)


def legacy_nodes_to_schedule_entries(nodes: Sequence[Any], *, working_period: int) -> tuple[ScheduleEntry, ...]:
    """Snapshot completed legacy scheduling fields into public immutable entries."""
    entries = []
    try:
        for node in nodes:
            if node.ID == 0:
                continue
            if node.parentID is None or node.timeslot is None or node.channel is None:
                continue
            entries.append(ScheduleEntry(
                sender=node.ID,
                receiver=node.parentID,
                timeslot=node.timeslot,
                channel=node.channel,
                receiver_active_slot=node.timeslot % working_period,
            ))
    except AttributeError as exc:
        raise SchemaError(f"legacy node is missing schedule field: {exc}", path="nodes",
                          code="INVALID_LEGACY_NODE") from exc
    return tuple(entries)


__all__ = [
    "ActiveSlotMode", "LEGACY_ACTIVE_SLOT_MODE", "FULL_PERIOD_ACTIVE_SLOT_MODE",
    "load_legacy_topology", "load_json_topology", "save_json_topology",
    "generate_network_instance", "network_instance_to_legacy_nodes",
    "legacy_nodes_to_network_instance", "topology_statistics",
    "legacy_nodes_to_schedule_entries",
]
