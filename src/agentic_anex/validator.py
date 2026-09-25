"""Independent, non-repairing validation over immutable public schemas."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Literal, Sequence

from .schemas import NetworkInstance, ScheduleEntry, SchemaError, ValidationReport, Violation

CollisionModel = Literal["legacy_neighbor", "interference_range"]
VALIDATOR_VERSION = "2.0.0"
CHECKED_CONSTRAINTS = (
    "one_transmission_per_non_sink", "known_sender_and_receiver",
    "sink_does_not_transmit", "communication_link", "channel_range",
    "receiver_active_slot", "receiver_active_slot_field",
    "acyclic_sink_rooted_routing", "aggregation_precedence",
    "primary_collision", "secondary_collision", "half_duplex",
)


def _v(code: str, message: str, *, nodes: Iterable[int] = (),
       links: Iterable[tuple[int, int]] = (), timeslots: Iterable[int] = (),
       details: dict | None = None) -> Violation:
    return Violation(code, message, tuple(nodes), dict(details or {}), tuple(links), tuple(timeslots))


def _interferes(network: NetworkInstance, a: ScheduleEntry, b: ScheduleEntry,
                model: CollisionModel, ratio: float) -> bool:
    nodes = {node.id: node for node in network.nodes}
    if model == "legacy_neighbor":
        return a.sender in nodes[b.receiver].neighbor_ids or b.sender in nodes[a.receiver].neighbor_ids
    radius = network.communication_range * ratio
    a_sender, a_receiver = nodes[a.sender], nodes[a.receiver]
    b_sender, b_receiver = nodes[b.sender], nodes[b.receiver]
    return (
        math.hypot(a_sender.x - b_receiver.x, a_sender.y - b_receiver.y) <= radius
        or math.hypot(b_sender.x - a_receiver.x, b_sender.y - a_receiver.y) <= radius
    )


def validate_schedule(
    network: NetworkInstance,
    schedule: Sequence[ScheduleEntry],
    *, channels: int,
    interference_ratio: float = 1.0,
    collision_model: CollisionModel = "legacy_neighbor",
) -> ValidationReport:
    """Validate schema snapshots without modifying or repairing either input."""
    if not isinstance(network, NetworkInstance):
        raise SchemaError("validator requires a public NetworkInstance, not legacy nodes",
                          path="network", code="INVALID_NETWORK")
    if isinstance(channels, bool) or not isinstance(channels, int) or channels < 1:
        raise SchemaError("must be an integer of at least 1", path="channels", code="INVALID_CHANNEL_COUNT")
    if (isinstance(interference_ratio, bool)
            or not isinstance(interference_ratio, (int, float))
            or not math.isfinite(interference_ratio) or interference_ratio < 1):
        raise SchemaError("must be finite and at least 1", path="interference_ratio",
                          code="INVALID_INTERFERENCE_RATIO")
    if collision_model not in {"legacy_neighbor", "interference_range"}:
        raise SchemaError("must be legacy_neighbor or interference_range", path="collision_model",
                          code="INVALID_COLLISION_MODEL")
    if not isinstance(schedule, (list, tuple)) or any(not isinstance(e, ScheduleEntry) for e in schedule):
        raise SchemaError("must contain public ScheduleEntry values", path="schedule", code="INVALID_SCHEDULE")

    entries = tuple(schedule)
    nodes = {node.id: node for node in network.nodes}
    non_sink = set(nodes) - {network.sink_id}
    violations: list[Violation] = []
    by_sender: dict[int, list[ScheduleEntry]] = defaultdict(list)

    for entry in entries:
        by_sender[entry.sender].append(entry)
        witness = dict(nodes=(entry.sender, entry.receiver),
                       links=((entry.sender, entry.receiver),), timeslots=(entry.timeslot,))
        if entry.sender not in nodes:
            violations.append(_v("UNKNOWN_SENDER", f"Sender {entry.sender} is not in the network.", **witness))
            continue
        if entry.sender == network.sink_id:
            violations.append(_v("SINK_TRANSMISSION", f"Sink {network.sink_id} must not transmit.", **witness))
        if entry.receiver not in nodes:
            violations.append(_v("UNKNOWN_RECEIVER", f"Receiver {entry.receiver} is not in the network.", **witness))
            continue
        if entry.receiver not in nodes[entry.sender].neighbor_ids:
            violations.append(_v("NON_NEIGHBOR_LINK",
                                 f"Link {entry.sender}->{entry.receiver} is not a communication edge.", **witness))
        if not 1 <= entry.channel <= channels:
            violations.append(_v("INVALID_CHANNEL", f"Channel {entry.channel} is outside [1, {channels}].",
                                 details={"channel": entry.channel, "channels": channels}, **witness))
        active_slot = entry.timeslot % network.working_period
        if entry.receiver_active_slot != active_slot:
            violations.append(_v("ACTIVE_SLOT_FIELD_MISMATCH",
                                 f"Recorded slot {entry.receiver_active_slot}; timeslot implies {active_slot}.",
                                 details={"expected_active_slot": active_slot}, **witness))
        if active_slot not in nodes[entry.receiver].active_slots:
            violations.append(_v("INACTIVE_RECEIVER",
                                 f"Receiver {entry.receiver} is inactive at slot {active_slot}.",
                                 details={"active_slot": active_slot}, **witness))

    for sender in sorted(non_sink):
        count = len(by_sender.get(sender, ()))
        if count == 0:
            violations.append(_v("MISSING_TRANSMISSION", f"Node {sender} has no transmission.", nodes=(sender,)))
        elif count > 1:
            group = by_sender[sender]
            violations.append(_v("DUPLICATE_TRANSMISSION", f"Node {sender} has {count} transmissions.",
                                 nodes=(sender,), links=((e.sender, e.receiver) for e in group),
                                 timeslots=(e.timeslot for e in group), details={"count": count}))

    unique = {sender: group[0] for sender, group in by_sender.items()
              if sender in non_sink and len(group) == 1 and group[0].receiver in nodes}
    for sender, entry in unique.items():
        path, cursor = [sender], sender
        for _ in range(len(nodes)):
            current = unique.get(cursor)
            if current is None:
                break
            parent = current.receiver
            if parent == network.sink_id:
                break
            if parent in path:
                cycle = tuple(path[path.index(parent):] + [parent])
                violations.append(_v("PARENT_CYCLE", f"Routing path from {sender} contains a cycle.",
                                     nodes=cycle, links=tuple(zip(cycle, cycle[1:]))))
                break
            path.append(parent)
            cursor = parent
        else:
            violations.append(_v("PARENT_CYCLE", f"Routing path from {sender} exceeds the node bound.",
                                 nodes=tuple(path)))
        parent_entry = unique.get(entry.receiver)
        if parent_entry is not None and entry.timeslot >= parent_entry.timeslot:
            violations.append(_v("PRECEDENCE_VIOLATION",
                                 f"Child {sender} at {entry.timeslot} must precede parent "
                                 f"{entry.receiver} at {parent_entry.timeslot}.",
                                 nodes=(sender, entry.receiver), links=((sender, entry.receiver),),
                                 timeslots=(entry.timeslot, parent_entry.timeslot)))

    by_receiver_time: dict[tuple[int, int], list[ScheduleEntry]] = defaultdict(list)
    by_time_channel: dict[tuple[int, int], list[ScheduleEntry]] = defaultdict(list)
    sender_times = {(entry.sender, entry.timeslot) for entry in entries if entry.sender in nodes}
    for entry in entries:
        if entry.sender in nodes and entry.receiver in nodes:
            by_receiver_time[(entry.receiver, entry.timeslot)].append(entry)
            by_time_channel[(entry.timeslot, entry.channel)].append(entry)
            if (entry.receiver, entry.timeslot) in sender_times:
                violations.append(_v("HALF_DUPLEX_VIOLATION",
                                     f"Receiver {entry.receiver} also transmits at timeslot {entry.timeslot}.",
                                     nodes=(entry.sender, entry.receiver), links=((entry.sender, entry.receiver),),
                                     timeslots=(entry.timeslot,)))
    for (receiver, timeslot), group in by_receiver_time.items():
        if len(group) > 1:
            violations.append(_v("PRIMARY_COLLISION",
                                 f"{len(group)} senders target receiver {receiver} at timeslot {timeslot}.",
                                 nodes=tuple(e.sender for e in group) + (receiver,),
                                 links=((e.sender, receiver) for e in group), timeslots=(timeslot,)))
    for (timeslot, channel), group in by_time_channel.items():
        for index, first in enumerate(group):
            for second in group[index + 1:]:
                if first.receiver != second.receiver and _interferes(
                        network, first, second, collision_model, float(interference_ratio)):
                    violations.append(_v("SECONDARY_COLLISION",
                                         f"Links {first.sender}->{first.receiver} and "
                                         f"{second.sender}->{second.receiver} conflict at timeslot {timeslot}, "
                                         f"channel {channel} under {collision_model}.",
                                         nodes=(first.sender, first.receiver, second.sender, second.receiver),
                                         links=((first.sender, first.receiver), (second.sender, second.receiver)),
                                         timeslots=(timeslot,),
                                         details={"channel": channel, "collision_model": collision_model}))

    result, seen = [], set()
    for item in violations:
        key = (item.code, item.nodes, item.links, item.timeslots, json.dumps(item.details, sort_keys=True))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return ValidationReport(not result, tuple(result), len(non_sink), collision_model,
                            CHECKED_CONSTRAINTS, VALIDATOR_VERSION)


def validation_certificate(report: ValidationReport) -> dict:
    if not isinstance(report, ValidationReport):
        raise SchemaError("must be a ValidationReport", path="report", code="INVALID_VALIDATION_REPORT")
    payload = {"certificate_format": "agentic_anex.validation_certificate.v1", **report.to_dict()}
    # Normalize tuples to JSON arrays so embedding the certificate in another
    # schema preserves equality across a JSON round trip.
    return json.loads(json.dumps(payload, sort_keys=True))


def export_validation_certificate(report: ValidationReport, path: str | Path) -> None:
    destination = Path(path)
    try:
        destination.write_text(json.dumps(validation_certificate(report), indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
    except (OSError, TypeError) as exc:
        raise SchemaError(f"cannot write validation certificate: {exc}", path=str(destination),
                          code="CERTIFICATE_WRITE_ERROR") from exc


__all__ = ["CollisionModel", "VALIDATOR_VERSION", "CHECKED_CONSTRAINTS", "validate_schedule",
           "validation_certificate", "export_validation_certificate"]
