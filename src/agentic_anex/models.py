from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class AnexConfig:
    working_period: int = 10
    channels: int = 2
    communication_range: float = 20.0
    interference_ratio: float = 1.0
    seed: int = 0

    def __post_init__(self) -> None:
        if self.working_period <= 0:
            raise ValueError("working_period must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")
        if self.communication_range <= 0:
            raise ValueError("communication_range must be positive")
        if self.interference_ratio < 1.0:
            raise ValueError("interference_ratio must be at least 1.0")


@dataclass(frozen=True)
class ScheduleEntry:
    sender: int
    receiver: int
    timeslot: int
    channel: int
    receiver_active_slot: int


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    nodes: tuple[int, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    violations: tuple[Violation, ...]
    checked_nodes: int
    secondary_collision_model: Literal["legacy_neighbor"] = "legacy_neighbor"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnexResult:
    config: AnexConfig
    schedule: tuple[ScheduleEntry, ...]
    validation: ValidationReport
    legacy_max_timeslot: int
    elapsed_slots: int
    max_layer: int
    node_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

