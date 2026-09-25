"""Deterministic, JSON-compatible scientific tools for Paper 1."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence, TypeVar

from .legacy import anex_module
from .models import AnexConfig
from .schemas import (
    DomainError, InfeasibleNetworkError, JsonSchema, NetworkInstance,
    ScheduleEntry, SchedulingResult, SchemaError, ValidationReport,
)
from .topology_io import load_json_topology, network_instance_to_legacy_nodes, topology_statistics
from .validator import (
    CollisionModel, validate_schedule as _validate_schedule,
    validation_certificate,
)

TOOL_LAYER_VERSION = "1.0.0"
DEFAULT_MAX_WORKING_PERIODS = 10_000


@dataclass(frozen=True)
class TraceRecord(JsonSchema):
    tool_name: str
    input_hash: str
    start_time: str
    end_time: str
    status: Literal["success", "domain_failure", "internal_exception"]
    error_type: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TraceRecord":
        return cls(**dict(data))


@dataclass(frozen=True)
class ValidationMode(JsonSchema):
    collision_model: CollisionModel = "legacy_neighbor"
    channels: int = 1
    interference_ratio: float = 1.0

    def __post_init__(self) -> None:
        if self.collision_model not in {"legacy_neighbor", "interference_range"}:
            raise SchemaError("invalid collision model", path="collision_model", code="INVALID_COLLISION_MODEL")
        if isinstance(self.channels, bool) or not isinstance(self.channels, int) or self.channels < 1:
            raise SchemaError("must be at least 1", path="channels", code="INVALID_CHANNEL_COUNT")
        if not isinstance(self.interference_ratio, (int, float)) or self.interference_ratio < 1:
            raise SchemaError("must be at least 1", path="interference_ratio",
                              code="INVALID_INTERFERENCE_RATIO")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ValidationMode":
        return cls(**dict(data))


@dataclass(frozen=True)
class NetworkInspection(JsonSchema):
    name: str | None
    sink_id: int
    working_period: int
    communication_range: float
    statistics: dict[str, int | float]
    active_slot_minimum: int
    active_slot_maximum: int
    active_slot_average: float
    connected_to_sink: bool
    trace: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NetworkInspection":
        return cls(**dict(data))


@dataclass(frozen=True)
class ScheduleMetrics(JsonSchema):
    node_count: int
    expected_transmissions: int
    scheduled_transmissions: int
    missing_senders: tuple[int, ...]
    max_timeslot_index: int
    latency_slots: int
    used_channels: tuple[int, ...]
    used_timeslots: tuple[int, ...]
    transmissions_per_timeslot: dict[str, int]
    trace: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScheduleMetrics":
        payload = dict(data)
        for key in ("missing_senders", "used_channels", "used_timeslots"):
            payload[key] = tuple(payload[key])
        return cls(**payload)


@dataclass(frozen=True)
class ViolationExplanation(JsonSchema):
    code: str
    summary: str
    severity: Literal["error"]
    node_witnesses: tuple[int, ...]
    link_witnesses: tuple[tuple[int, int], ...]
    timeslot_witnesses: tuple[int, ...]
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ViolationExplanation":
        payload = dict(data)
        payload["node_witnesses"] = tuple(payload["node_witnesses"])
        payload["link_witnesses"] = tuple(tuple(link) for link in payload["link_witnesses"])
        payload["timeslot_witnesses"] = tuple(payload["timeslot_witnesses"])
        return cls(**payload)


@dataclass(frozen=True)
class ViolationExplanations(JsonSchema):
    valid: bool
    explanations: tuple[ViolationExplanation, ...]
    validator_version: str
    collision_model: str
    trace: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ViolationExplanations":
        payload = dict(data)
        payload["explanations"] = tuple(ViolationExplanation.from_dict(item)
                                        for item in payload["explanations"])
        return cls(**payload)


TRACE_RECORDS: list[TraceRecord] = []
R = TypeVar("R")


def _jsonable(value: Any) -> Any:
    if isinstance(value, JsonSchema):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _input_hash(value: Any) -> str:
    encoded = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _call(tool_name: str, inputs: Any, operation: Callable[[], R],
          attach: Callable[[R, dict[str, Any]], R]) -> R:
    start = _now()
    digest = _input_hash(inputs)
    try:
        result = operation()
    except DomainError as exc:
        trace = TraceRecord(tool_name, digest, start, _now(), "domain_failure", type(exc).__name__)
        TRACE_RECORDS.append(trace)
        setattr(exc, "trace", trace.to_dict())
        raise
    except Exception as exc:
        trace = TraceRecord(tool_name, digest, start, _now(), "internal_exception", type(exc).__name__)
        TRACE_RECORDS.append(trace)
        try:
            setattr(exc, "trace", trace.to_dict())
        except (AttributeError, TypeError):
            pass
        raise
    trace = TraceRecord(tool_name, digest, start, _now(), "success")
    TRACE_RECORDS.append(trace)
    return attach(result, trace.to_dict())


def inspect_network(instance: NetworkInstance) -> NetworkInspection:
    def operation() -> NetworkInspection:
        if not isinstance(instance, NetworkInstance):
            raise SchemaError("must be a NetworkInstance", path="instance", code="INVALID_NETWORK")
        counts = [len(node.active_slots) for node in instance.nodes]
        return NetworkInspection(
            name=instance.name, sink_id=instance.sink_id,
            working_period=instance.working_period,
            communication_range=instance.communication_range,
            statistics=topology_statistics(instance),
            active_slot_minimum=min(counts), active_slot_maximum=max(counts),
            active_slot_average=sum(counts) / len(counts), connected_to_sink=True,
        )
    return _call("inspect_network", instance, operation,
                 lambda result, trace: replace(result, trace=trace))


def _guarded_legacy_anex(nodes: list[Any], config: AnexConfig) -> tuple[list[Any], int]:
    nodes, max_layer = anex_module.tree_construction_based_minimum_link_delay(
        nodes, config.working_period
    )
    for left in range(len(nodes) - 1):
        for right in range(left + 1, len(nodes)):
            if anex_module.distance(nodes[left], nodes[right]) <= (
                    config.communication_range * config.interference_ratio):
                nodes[left].interfereIDs.append(nodes[right].ID)
                nodes[right].interfereIDs.append(nodes[left].ID)
    completed = [0]
    working_period_index = 1
    while len(completed) != len(nodes):
        if working_period_index > DEFAULT_MAX_WORKING_PERIODS:
            raise InfeasibleNetworkError(
                f"ANEX exceeded {DEFAULT_MAX_WORKING_PERIODS} working periods",
                path="schedule", code="MAX_WORKING_PERIODS_EXCEEDED",
            )
        before = len(completed)
        for slot in range(config.working_period):
            candidates = anex_module.find_candidate_senders_at_current_slot(nodes, slot)
            for node_id in candidates:
                anex_module.weight_calc(nodes, node_id, slot)
            candidates = sorted(candidates, key=lambda node_id: nodes[node_id].weight)
            senders, receivers = [], []
            anex_module.dynamic_schedule(
                nodes, candidates, senders, receivers, config.working_period,
                config.channels, slot, working_period_index,
            )
            completed.extend(senders)
        if len(completed) == before:
            remaining = [node.ID for node in nodes if node.ID != 0 and node.timeslot is None]
            raise InfeasibleNetworkError(
                f"ANEX made no progress during working period {working_period_index}; "
                f"remaining nodes: {remaining}",
                path="schedule", code="ANEX_NO_PROGRESS",
            )
        working_period_index += 1
    return nodes, max_layer


def run_anex(instance: NetworkInstance, config: AnexConfig) -> SchedulingResult:
    def operation() -> SchedulingResult:
        if not isinstance(instance, NetworkInstance):
            raise SchemaError("must be a NetworkInstance", path="instance", code="INVALID_NETWORK")
        if not isinstance(config, AnexConfig):
            raise SchemaError("must be an AnexConfig", path="config", code="INVALID_CONFIG")
        if config.working_period != instance.working_period:
            raise SchemaError("must equal network working_period", path="config.working_period",
                              code="CONFIG_NETWORK_MISMATCH")
        if config.communication_range != instance.communication_range:
            raise SchemaError("must equal network communication_range", path="config.communication_range",
                              code="CONFIG_NETWORK_MISMATCH")
        nodes, max_layer = _guarded_legacy_anex(network_instance_to_legacy_nodes(instance), config)
        schedule = tuple(ScheduleEntry(
            sender=node.ID, receiver=node.parentID, timeslot=node.timeslot,
            channel=node.channel, receiver_active_slot=node.timeslot % instance.working_period,
        ) for node in nodes if node.ID != instance.sink_id)
        report = _validate_schedule(
            instance, schedule, channels=config.channels,
            interference_ratio=config.interference_ratio,
            collision_model="legacy_neighbor",
        )
        max_index = max((entry.timeslot for entry in schedule), default=-1)
        certificate = validation_certificate(report)
        return SchedulingResult(
            schedule=schedule, validation=report,
            latency_slots=max_index + 1, max_timeslot_index=max_index,
            node_count=len(instance.nodes),
            metadata={
                "max_layer": max_layer,
                "tool_layer_version": TOOL_LAYER_VERSION,
                "active_slot_mode": instance.metadata.get("active_slot_mode"),
            },
            validation_certificate=certificate,
        )
    return _call("run_anex", {"instance": instance, "config": config}, operation,
                 lambda result, trace: replace(result, trace=trace))


def validate_schedule(instance: NetworkInstance, schedule: Sequence[ScheduleEntry],
                      mode: ValidationMode | CollisionModel) -> ValidationReport:
    def operation() -> ValidationReport:
        if isinstance(mode, str):
            if not isinstance(schedule, (list, tuple)) or any(
                    not isinstance(entry, ScheduleEntry) for entry in schedule):
                raise SchemaError("must contain ScheduleEntry values", path="schedule",
                                  code="INVALID_SCHEDULE")
            parsed_mode: Any = ValidationMode(
                mode, max((entry.channel for entry in schedule), default=1), 1.0
            )
        else:
            parsed_mode = mode
        if not isinstance(parsed_mode, ValidationMode):
            raise SchemaError("must be a ValidationMode", path="mode", code="INVALID_VALIDATION_MODE")
        return _validate_schedule(
            instance, schedule, channels=parsed_mode.channels,
            interference_ratio=parsed_mode.interference_ratio,
            collision_model=parsed_mode.collision_model,
        )
    return _call("validate_schedule", {"instance": instance, "schedule": schedule, "mode": mode},
                 operation, lambda result, trace: replace(result, trace=trace))


def measure_schedule(instance: NetworkInstance, schedule: Sequence[ScheduleEntry]) -> ScheduleMetrics:
    def operation() -> ScheduleMetrics:
        if not isinstance(instance, NetworkInstance):
            raise SchemaError("must be a NetworkInstance", path="instance", code="INVALID_NETWORK")
        if not isinstance(schedule, (list, tuple)) or any(not isinstance(e, ScheduleEntry) for e in schedule):
            raise SchemaError("must contain ScheduleEntry values", path="schedule", code="INVALID_SCHEDULE")
        senders = {entry.sender for entry in schedule}
        expected = {node.id for node in instance.nodes} - {instance.sink_id}
        max_index = max((entry.timeslot for entry in schedule), default=-1)
        per_slot: dict[int, int] = defaultdict(int)
        for entry in schedule:
            per_slot[entry.timeslot] += 1
        return ScheduleMetrics(
            node_count=len(instance.nodes), expected_transmissions=len(expected),
            scheduled_transmissions=len(schedule), missing_senders=tuple(sorted(expected - senders)),
            max_timeslot_index=max_index, latency_slots=max_index + 1,
            used_channels=tuple(sorted({entry.channel for entry in schedule})),
            used_timeslots=tuple(sorted(per_slot)),
            transmissions_per_timeslot={str(slot): per_slot[slot] for slot in sorted(per_slot)},
        )
    return _call("measure_schedule", {"instance": instance, "schedule": schedule}, operation,
                 lambda result, trace: replace(result, trace=trace))


def explain_violations(report: ValidationReport) -> ViolationExplanations:
    def operation() -> ViolationExplanations:
        if not isinstance(report, ValidationReport):
            raise SchemaError("must be a ValidationReport", path="report", code="INVALID_VALIDATION_REPORT")
        explanations = tuple(ViolationExplanation(
            code=item.code, summary=item.message, severity="error",
            node_witnesses=item.nodes, link_witnesses=item.links,
            timeslot_witnesses=item.timeslots, details=dict(item.details),
        ) for item in report.violations)
        return ViolationExplanations(report.valid, explanations, report.validator_version,
                                     report.collision_model)
    return _call("explain_violations", report, operation,
                 lambda result, trace: replace(result, trace=trace))


def _load_schedule(path: str | Path) -> tuple[ScheduleEntry, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = payload.get("schedule", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise SchemaError("schedule JSON must be an array or result object", code="INVALID_SCHEDULE_JSON")
    return tuple(ScheduleEntry.from_dict(item) for item in raw)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Agentic ANEX deterministic scientific tools")
    subparsers = parser.add_subparsers(dest="tool", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--network", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--network", required=True); run_parser.add_argument("--config", required=True)
    for name in ("validate", "measure"):
        command = subparsers.add_parser(name)
        command.add_argument("--network", required=True); command.add_argument("--schedule", required=True)
        if name == "validate":
            command.add_argument("--mode", choices=("legacy_neighbor", "interference_range"), default="legacy_neighbor")
            command.add_argument("--channels", type=int, required=True)
            command.add_argument("--interference-ratio", type=float, default=1.0)
    explain_parser = subparsers.add_parser("explain"); explain_parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    if args.tool == "inspect":
        result = inspect_network(load_json_topology(args.network))
    elif args.tool == "run":
        network = load_json_topology(args.network)
        config = AnexConfig(**json.loads(Path(args.config).read_text(encoding="utf-8")))
        result = run_anex(network, config)
    elif args.tool == "validate":
        network = load_json_topology(args.network)
        result = validate_schedule(network, _load_schedule(args.schedule), ValidationMode(
            args.mode, args.channels, args.interference_ratio))
    elif args.tool == "measure":
        result = measure_schedule(load_json_topology(args.network), _load_schedule(args.schedule))
    else:
        report = ValidationReport.from_json(Path(args.report).read_text(encoding="utf-8"))
        result = explain_violations(report)
    print(result.to_json(indent=2))


if __name__ == "__main__":
    main()


__all__ = [
    "TraceRecord", "ValidationMode", "NetworkInspection", "ScheduleMetrics",
    "ViolationExplanation", "ViolationExplanations", "TRACE_RECORDS",
    "inspect_network", "run_anex", "validate_schedule", "measure_schedule",
    "explain_violations", "main",
]
