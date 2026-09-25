"""Typed, JSON-safe domain schemas for the Paper 1 scheduling boundary.

These types intentionally contain no legacy ``Node`` objects.  Conversion to
the mutable published implementation belongs at an adapter boundary.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, Literal, Mapping, TypeVar


class DomainError(ValueError):
    """Base class for errors intended to be shown to API users."""

    category: ClassVar[str] = "domain_error"

    def __init__(self, message: str, *, path: str | None = None, code: str | None = None):
        self.message = message
        self.path = path
        self.code = code or self.category.upper()
        location = f" at {path}" if path else ""
        super().__init__(f"[{self.code}] {message}{location}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "code": self.code,
            "message": self.message,
            "path": self.path,
        }


class SchemaError(DomainError):
    """The serialized shape or a field value is malformed."""

    category = "schema_error"


class UnsupportedRequestError(DomainError):
    """The request is well-formed but outside the Paper 1 scope."""

    category = "unsupported_request"


class InfeasibleNetworkError(DomainError):
    """The network is well-formed but cannot be scheduled as requested."""

    category = "infeasible_network"


T = TypeVar("T", bound="JsonSchema")


class JsonSchema:
    """Small serialization mixin shared by every public schema."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls: type[T], payload: str) -> T:
        try:
            value = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise SchemaError(f"invalid JSON: {exc}", code="INVALID_JSON") from exc
        if not isinstance(value, dict):
            raise SchemaError("top-level JSON value must be an object", code="INVALID_JSON_OBJECT")
        return cls.from_dict(value)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaError("must be an object", path=name, code="INVALID_OBJECT")
    return value


def _int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaError("must be an integer", path=path, code="INVALID_INTEGER")
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SchemaError("must be a finite number", path=path, code="INVALID_NUMBER")
    return float(value)


def _tuple_of_ints(value: Any, path: str) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        raise SchemaError("must be an array of integers", path=path, code="INVALID_ARRAY")
    return tuple(_int(item, f"{path}[{index}]") for index, item in enumerate(value))


@dataclass(frozen=True)
class NodeSpec(JsonSchema):
    id: int
    x: float
    y: float
    active_slots: tuple[int, ...]
    neighbor_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        _int(self.id, "id")
        if self.id < 0:
            raise SchemaError("must be non-negative", path="id", code="INVALID_NODE_ID")
        _number(self.x, "x")
        _number(self.y, "y")
        slots = _tuple_of_ints(self.active_slots, "active_slots")
        neighbors = _tuple_of_ints(self.neighbor_ids, "neighbor_ids")
        object.__setattr__(self, "active_slots", slots)
        object.__setattr__(self, "neighbor_ids", neighbors)
        if not slots:
            raise SchemaError("must not be empty", path="active_slots", code="EMPTY_ACTIVE_SLOTS")
        if len(set(slots)) != len(slots):
            raise SchemaError("must not contain duplicates", path="active_slots", code="DUPLICATE_ACTIVE_SLOT")
        if len(set(neighbors)) != len(neighbors):
            raise SchemaError("must not contain duplicates", path="neighbor_ids", code="DUPLICATE_NEIGHBOR")
        if self.id in neighbors:
            raise SchemaError("must not contain the node itself", path="neighbor_ids", code="SELF_NEIGHBOR")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NodeSpec":
        data = _mapping(data, "node")
        try:
            return cls(
                id=data["id"], x=data["x"], y=data["y"],
                active_slots=data["active_slots"], neighbor_ids=data["neighbor_ids"],
            )
        except KeyError as exc:
            raise SchemaError("required field is missing", path=str(exc.args[0]), code="MISSING_FIELD") from exc


@dataclass(frozen=True)
class NetworkInstance(JsonSchema):
    nodes: tuple[NodeSpec, ...]
    sink_id: int
    working_period: int
    communication_range: float
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        nodes = tuple(self.nodes)
        object.__setattr__(self, "nodes", nodes)
        if not nodes:
            raise SchemaError("must contain at least one node", path="nodes", code="EMPTY_NETWORK")
        _int(self.working_period, "working_period")
        if self.working_period <= 0:
            raise SchemaError("must be positive", path="working_period", code="INVALID_WORKING_PERIOD")
        communication_range = _number(self.communication_range, "communication_range")
        if communication_range <= 0:
            raise SchemaError("must be positive", path="communication_range", code="INVALID_COMMUNICATION_RANGE")
        object.__setattr__(self, "communication_range", communication_range)
        _int(self.sink_id, "sink_id")
        ids = [node.id for node in nodes]
        if len(set(ids)) != len(ids):
            raise SchemaError("node IDs must be unique", path="nodes", code="DUPLICATE_NODE_ID")
        if sorted(ids) != list(range(len(nodes))):
            raise SchemaError(
                f"node IDs must be contiguous from 0 to {len(nodes) - 1}",
                path="nodes", code="NON_CONTIGUOUS_NODE_IDS",
            )
        if self.sink_id not in set(ids):
            raise SchemaError("must identify an existing node", path="sink_id", code="INVALID_SINK_ID")
        valid_ids = set(ids)
        by_id = {node.id: node for node in nodes}
        for node in nodes:
            for slot in node.active_slots:
                if not 0 <= slot < self.working_period:
                    raise SchemaError(
                        f"must be in [0, {self.working_period - 1}]",
                        path=f"nodes[{node.id}].active_slots", code="ACTIVE_SLOT_OUT_OF_RANGE",
                    )
            for neighbor in node.neighbor_ids:
                if neighbor not in valid_ids:
                    raise SchemaError(
                        f"references unknown node {neighbor}",
                        path=f"nodes[{node.id}].neighbor_ids", code="UNKNOWN_NEIGHBOR",
                    )
                if node.id not in by_id[neighbor].neighbor_ids:
                    raise SchemaError(
                        f"edge {node.id}-{neighbor} must be symmetric",
                        path=f"nodes[{node.id}].neighbor_ids", code="ASYMMETRIC_EDGE",
                    )
        reachable = {self.sink_id}
        frontier = [self.sink_id]
        while frontier:
            current = frontier.pop()
            for neighbor in by_id[current].neighbor_ids:
                if neighbor not in reachable:
                    reachable.add(neighbor)
                    frontier.append(neighbor)
        if len(reachable) != len(nodes):
            missing = sorted(valid_ids - reachable)
            raise InfeasibleNetworkError(
                f"sink {self.sink_id} cannot reach nodes {missing}",
                path="nodes", code="DISCONNECTED_TOPOLOGY",
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NetworkInstance":
        data = _mapping(data, "network")
        try:
            raw_nodes = data["nodes"]
            if not isinstance(raw_nodes, (list, tuple)):
                raise SchemaError("must be an array", path="nodes", code="INVALID_ARRAY")
            return cls(
                nodes=tuple(NodeSpec.from_dict(item) for item in raw_nodes),
                sink_id=data["sink_id"],
                working_period=data["working_period"],
                communication_range=data["communication_range"],
                name=data.get("name"),
                metadata=dict(data.get("metadata", {})),
            )
        except KeyError as exc:
            raise SchemaError("required field is missing", path=str(exc.args[0]), code="MISSING_FIELD") from exc


@dataclass(frozen=True)
class SchedulingRequest(JsonSchema):
    network: NetworkInstance
    channels: int
    interference_ratio: float
    workload: Literal["one_shot"] = "one_shot"
    objective: Literal["minimize_latency"] = "minimize_latency"
    seed: int = 0
    collision_model: Literal["legacy_neighbor", "interference_range"] = "legacy_neighbor"
    latency_target_slots: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.network, NetworkInstance):
            raise SchemaError("must be a NetworkInstance", path="network", code="INVALID_NETWORK")
        _int(self.channels, "channels")
        if self.channels < 1:
            raise SchemaError("must be at least 1", path="channels", code="INVALID_CHANNEL_COUNT")
        ratio = _number(self.interference_ratio, "interference_ratio")
        if ratio < 1:
            raise SchemaError("must be at least 1", path="interference_ratio", code="INVALID_INTERFERENCE_RATIO")
        object.__setattr__(self, "interference_ratio", ratio)
        _int(self.seed, "seed")
        if self.workload != "one_shot":
            raise UnsupportedRequestError(
                "Paper 1 supports only one_shot workloads",
                path="workload", code="UNSUPPORTED_WORKLOAD",
            )
        if self.objective != "minimize_latency":
            raise UnsupportedRequestError(
                "Paper 1 supports only minimize_latency",
                path="objective", code="UNSUPPORTED_OBJECTIVE",
            )
        if self.collision_model not in {"legacy_neighbor", "interference_range"}:
            raise SchemaError("invalid collision model", path="collision_model",
                              code="INVALID_COLLISION_MODEL")
        if self.latency_target_slots is not None and (
                isinstance(self.latency_target_slots, bool)
                or not isinstance(self.latency_target_slots, int)
                or self.latency_target_slots < 1):
            raise SchemaError("must be a positive integer", path="latency_target_slots",
                              code="INVALID_LATENCY_TARGET")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SchedulingRequest":
        data = _mapping(data, "request")
        try:
            allowed = {
                "network", "channels", "interference_ratio", "workload", "objective",
                "seed", "collision_model", "latency_target_slots",
            }
            unknown = sorted(set(data) - allowed)
            if unknown:
                raise SchemaError(f"unknown request fields: {unknown}", path="request",
                                  code="UNKNOWN_REQUEST_FIELD")
            network = data["network"]
            return cls(
                network=network if isinstance(network, NetworkInstance) else NetworkInstance.from_dict(network),
                channels=data["channels"],
                interference_ratio=data["interference_ratio"],
                workload=data.get("workload", "one_shot"),
                objective=data.get("objective", "minimize_latency"),
                seed=data.get("seed", 0),
                collision_model=data.get("collision_model", "legacy_neighbor"),
                latency_target_slots=data.get("latency_target_slots"),
            )
        except KeyError as exc:
            raise SchemaError("required field is missing", path=str(exc.args[0]), code="MISSING_FIELD") from exc

    @classmethod
    def from_anex_config(cls, config: Any, network: NetworkInstance) -> "SchedulingRequest":
        return cls(
            network=network,
            channels=config.channels,
            interference_ratio=config.interference_ratio,
            seed=config.seed,
        )

    def to_anex_config(self) -> Any:
        from .models import AnexConfig

        return AnexConfig(
            working_period=self.network.working_period,
            channels=self.channels,
            communication_range=self.network.communication_range,
            interference_ratio=self.interference_ratio,
            seed=self.seed,
        )


@dataclass(frozen=True)
class ScheduleEntry(JsonSchema):
    sender: int
    receiver: int
    timeslot: int
    channel: int
    receiver_active_slot: int

    def __post_init__(self) -> None:
        for name in ("sender", "receiver", "timeslot", "channel", "receiver_active_slot"):
            _int(getattr(self, name), name)
        if self.sender < 0 or self.receiver < 0 or self.timeslot < 0 or self.receiver_active_slot < 0:
            raise SchemaError("node IDs and slots must be non-negative", code="NEGATIVE_SCHEDULE_VALUE")
        if self.channel < 1:
            raise SchemaError("must be at least 1", path="channel", code="INVALID_CHANNEL")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScheduleEntry":
        data = _mapping(data, "schedule_entry")
        try:
            return cls(**{key: data[key] for key in (
                "sender", "receiver", "timeslot", "channel", "receiver_active_slot"
            )})
        except KeyError as exc:
            raise SchemaError("required field is missing", path=str(exc.args[0]), code="MISSING_FIELD") from exc


@dataclass(frozen=True)
class Violation(JsonSchema):
    code: str
    message: str
    nodes: tuple[int, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)
    links: tuple[tuple[int, int], ...] = ()
    timeslots: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise SchemaError("must be a nonempty string", path="code", code="INVALID_VIOLATION_CODE")
        if not isinstance(self.message, str) or not self.message:
            raise SchemaError("must be a nonempty string", path="message", code="INVALID_VIOLATION_MESSAGE")
        object.__setattr__(self, "nodes", _tuple_of_ints(self.nodes, "nodes"))
        try:
            links = tuple(tuple(link) for link in self.links)
        except TypeError as exc:
            raise SchemaError("must be an array of two-node links", path="links", code="INVALID_LINK_WITNESS") from exc
        if any(len(link) != 2 for link in links):
            raise SchemaError("each link must contain two node IDs", path="links", code="INVALID_LINK_WITNESS")
        object.__setattr__(self, "links", tuple(
            (_int(link[0], "links[][0]"), _int(link[1], "links[][1]")) for link in links
        ))
        object.__setattr__(self, "timeslots", _tuple_of_ints(self.timeslots, "timeslots"))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Violation":
        data = _mapping(data, "violation")
        try:
            return cls(
                code=data["code"], message=data["message"],
                nodes=data.get("nodes", ()), details=dict(data.get("details", {})),
                links=data.get("links", ()), timeslots=data.get("timeslots", ()),
            )
        except KeyError as exc:
            raise SchemaError("required field is missing", path=str(exc.args[0]), code="MISSING_FIELD") from exc


@dataclass(frozen=True)
class ValidationReport(JsonSchema):
    valid: bool
    violations: tuple[Violation, ...]
    checked_nodes: int
    collision_model: str
    checked_constraints: tuple[str, ...] = ()
    validator_version: str = "1.0.0"
    trace: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.valid, bool):
            raise SchemaError("must be boolean", path="valid", code="INVALID_BOOLEAN")
        violations = tuple(self.violations)
        object.__setattr__(self, "violations", violations)
        _int(self.checked_nodes, "checked_nodes")
        if self.checked_nodes < 0:
            raise SchemaError("must be non-negative", path="checked_nodes", code="INVALID_CHECKED_NODES")
        if self.valid == bool(violations):
            raise SchemaError(
                "valid must be true exactly when violations is empty",
                path="valid", code="INCONSISTENT_VALIDATION_REPORT",
            )
        if not isinstance(self.collision_model, str) or not self.collision_model:
            raise SchemaError("must be a nonempty string", path="collision_model", code="INVALID_COLLISION_MODEL")
        if not isinstance(self.validator_version, str) or not self.validator_version:
            raise SchemaError("must be a nonempty string", path="validator_version", code="INVALID_VALIDATOR_VERSION")
        if not isinstance(self.checked_constraints, (list, tuple)) or any(
            not isinstance(item, str) or not item for item in self.checked_constraints
        ):
            raise SchemaError("must contain nonempty strings", path="checked_constraints", code="INVALID_CHECKED_CONSTRAINTS")
        object.__setattr__(self, "checked_constraints", tuple(self.checked_constraints))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ValidationReport":
        data = _mapping(data, "validation")
        try:
            return cls(
                valid=data["valid"],
                violations=tuple(Violation.from_dict(item) for item in data["violations"]),
                checked_nodes=data["checked_nodes"],
                collision_model=data["collision_model"],
                checked_constraints=tuple(data.get("checked_constraints", ())),
                validator_version=data.get("validator_version", "1.0.0"),
                trace=dict(data["trace"]) if data.get("trace") is not None else None,
            )
        except KeyError as exc:
            raise SchemaError("required field is missing", path=str(exc.args[0]), code="MISSING_FIELD") from exc


@dataclass(frozen=True)
class SchedulingResult(JsonSchema):
    schedule: tuple[ScheduleEntry, ...]
    validation: ValidationReport
    latency_slots: int
    max_timeslot_index: int
    node_count: int
    metadata: dict[str, Any] = field(default_factory=dict)
    validation_certificate: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "schedule", tuple(self.schedule))
        for name in ("latency_slots", "max_timeslot_index", "node_count"):
            _int(getattr(self, name), name)
        if self.latency_slots < 0 or self.node_count < 1 or self.max_timeslot_index < -1:
            raise SchemaError("result counts are outside their valid range", code="INVALID_RESULT_COUNT")
        expected = 0 if self.max_timeslot_index == -1 else self.max_timeslot_index + 1
        if self.latency_slots != expected:
            raise SchemaError(
                f"must equal max_timeslot_index + 1 ({expected})",
                path="latency_slots", code="INCONSISTENT_LATENCY",
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SchedulingResult":
        data = _mapping(data, "result")
        try:
            validation = data["validation"]
            return cls(
                schedule=tuple(ScheduleEntry.from_dict(item) for item in data["schedule"]),
                validation=validation if isinstance(validation, ValidationReport) else ValidationReport.from_dict(validation),
                latency_slots=data["latency_slots"],
                max_timeslot_index=data["max_timeslot_index"],
                node_count=data["node_count"],
                metadata=dict(data.get("metadata", {})),
                validation_certificate=(dict(data["validation_certificate"])
                                        if data.get("validation_certificate") is not None else None),
                trace=dict(data["trace"]) if data.get("trace") is not None else None,
            )
        except KeyError as exc:
            raise SchemaError("required field is missing", path=str(exc.args[0]), code="MISSING_FIELD") from exc

    @classmethod
    def from_anex_result(cls, result: Any) -> "SchedulingResult":
        report = ValidationReport(
            valid=result.validation.valid,
            violations=tuple(Violation.from_dict(asdict(item)) for item in result.validation.violations),
            checked_nodes=result.validation.checked_nodes,
            collision_model=result.validation.secondary_collision_model,
            checked_constraints=tuple(getattr(result.validation, "checked_constraints", ())),
            validator_version=getattr(result.validation, "validator_version", "legacy-adapter"),
        )
        return cls(
            schedule=tuple(ScheduleEntry.from_dict(asdict(item)) for item in result.schedule),
            validation=report,
            latency_slots=result.elapsed_slots,
            max_timeslot_index=result.legacy_max_timeslot,
            node_count=result.node_count,
            metadata=dict(result.metadata),
        )


@dataclass(frozen=True)
class RequirementDecision(JsonSchema):
    requirement: str
    decision: str
    rationale: str
    status: Literal["accepted", "rejected", "deferred"] = "accepted"

    def __post_init__(self) -> None:
        for name in ("requirement", "decision", "rationale"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise SchemaError("must be a nonempty string", path=name, code="INVALID_DECISION_TEXT")
        if self.status not in {"accepted", "rejected", "deferred"}:
            raise SchemaError("must be accepted, rejected, or deferred", path="status", code="INVALID_DECISION_STATUS")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RequirementDecision":
        data = _mapping(data, "requirement_decision")
        try:
            return cls(
                requirement=data["requirement"], decision=data["decision"],
                rationale=data["rationale"], status=data.get("status", "accepted"),
            )
        except KeyError as exc:
            raise SchemaError("required field is missing", path=str(exc.args[0]), code="MISSING_FIELD") from exc


def to_json(value: JsonSchema, *, indent: int | None = None) -> str:
    """Serialize any public schema without embedding Python class metadata."""
    if not isinstance(value, JsonSchema):
        raise SchemaError("value must be a public schema", code="INVALID_SCHEMA_VALUE")
    return value.to_json(indent=indent)


def from_json(schema: type[T], payload: str) -> T:
    """Deserialize JSON into the explicitly selected schema type."""
    if not isinstance(schema, type) or not issubclass(schema, JsonSchema):
        raise SchemaError("schema must be a JsonSchema type", code="INVALID_SCHEMA_TYPE")
    return schema.from_json(payload)


__all__ = [
    "DomainError", "SchemaError", "UnsupportedRequestError", "InfeasibleNetworkError",
    "NodeSpec", "NetworkInstance", "SchedulingRequest", "ScheduleEntry",
    "SchedulingResult", "ValidationReport", "Violation", "RequirementDecision",
    "to_json", "from_json",
]
