"""Rule-based Paper 1 requirement processor; no LLM is involved.

Documented non-critical defaults:

* channels: 2
* interference_ratio: 1.0
* collision_model: legacy_neighbor
* seed: 0

Topology, workload, and objective are critical and are never inferred.
Working period and communication range default only to values already carried by
the supplied topology.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping

from ..models import AnexConfig
from ..schemas import (
    DomainError, JsonSchema, NetworkInstance, RequirementDecision,
    SchedulingRequest, SchedulingResult, SchemaError, ValidationReport,
)
from ..tools import (
    NetworkInspection, ScheduleMetrics, TraceRecord, ValidationMode,
    explain_violations, inspect_network, measure_schedule, run_anex,
    validate_schedule,
)
from ..validator import validation_certificate

DEFAULT_CHANNELS = 2
DEFAULT_INTERFERENCE_RATIO = 1.0
DEFAULT_COLLISION_MODEL = "legacy_neighbor"
DEFAULT_SEED = 0


class WorkflowStatus(str, Enum):
    EXECUTE = "EXECUTE"
    CLARIFY = "CLARIFY"
    REJECT = "REJECT"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class ClarificationQuestion(JsonSchema):
    field: str
    question: str
    expected_type: str
    reason: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClarificationQuestion":
        return cls(**dict(data))


@dataclass(frozen=True)
class RuleBasedRequest(JsonSchema):
    topology: NetworkInstance | None = None
    workload: str | None = None
    objective: str | None = None
    latency_target_slots: int | None = None
    channels: int | None = None
    working_period: int | None = None
    communication_range: float | None = None
    interference_ratio: float | None = None
    collision_model: str | None = None
    seed: int | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuleBasedRequest":
        if not isinstance(data, Mapping):
            raise SchemaError("request must be an object", path="request", code="INVALID_REQUEST")
        payload = dict(data)
        topology = payload.get("topology")
        if topology is not None and not isinstance(topology, NetworkInstance):
            topology = NetworkInstance.from_dict(topology)
        allowed = {
            "topology", "workload", "objective", "latency_target_slots", "channels",
            "working_period", "communication_range", "interference_ratio",
            "collision_model", "seed",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise SchemaError(f"unknown request fields: {unknown}", path="request",
                              code="UNKNOWN_REQUEST_FIELD")
        payload["topology"] = topology
        return cls(**payload)


@dataclass(frozen=True)
class WorkflowReport(JsonSchema):
    status: Literal["EXECUTE", "CLARIFY", "REJECT", "UNSUPPORTED"]
    message: str
    clarification_questions: tuple[ClarificationQuestion, ...] = ()
    decisions: tuple[RequirementDecision, ...] = ()
    inspection: NetworkInspection | None = None
    result: SchedulingResult | None = None
    final_validation: ValidationReport | None = None
    final_validation_certificate: dict[str, Any] | None = None
    metrics: ScheduleMetrics | None = None
    latency_target_slots: int | None = None
    target_satisfied: bool | None = None
    tool_trace: tuple[TraceRecord, ...] = ()
    error: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkflowReport":
        payload = dict(data)
        payload["clarification_questions"] = tuple(
            ClarificationQuestion.from_dict(item) for item in payload.get("clarification_questions", ())
        )
        payload["decisions"] = tuple(
            RequirementDecision.from_dict(item) for item in payload.get("decisions", ())
        )
        if payload.get("inspection") is not None:
            payload["inspection"] = NetworkInspection.from_dict(payload["inspection"])
        if payload.get("result") is not None:
            payload["result"] = SchedulingResult.from_dict(payload["result"])
        if payload.get("final_validation") is not None:
            payload["final_validation"] = ValidationReport.from_dict(payload["final_validation"])
        if payload.get("metrics") is not None:
            payload["metrics"] = ScheduleMetrics.from_dict(payload["metrics"])
        payload["tool_trace"] = tuple(TraceRecord.from_dict(item) for item in payload.get("tool_trace", ()))
        return cls(**payload)


def _question(field_name: str) -> ClarificationQuestion:
    questions = {
        "topology": ClarificationQuestion(
            "topology", "Which validated network topology should be scheduled?",
            "NetworkInstance", "ANEX cannot execute without nodes, links, active slots, and a sink.",
        ),
        "workload": ClarificationQuestion(
            "workload", "Is this a one-shot data aggregation request?",
            'literal "one_shot"', "Paper 1 supports one-shot aggregation only.",
        ),
        "objective": ClarificationQuestion(
            "objective", "Should the workflow minimize latency?",
            'literal "minimize_latency"', "Paper 1 supports latency minimization only.",
        ),
    }
    return questions[field_name]


def _trace_from(*outputs: Any) -> tuple[TraceRecord, ...]:
    traces = []
    for output in outputs:
        raw = getattr(output, "trace", None)
        if raw:
            traces.append(TraceRecord.from_dict(raw))
    return tuple(traces)


def _default_decisions(request: RuleBasedRequest) -> tuple[RequirementDecision, ...]:
    decisions = []
    defaults = (
        ("channels", request.channels, DEFAULT_CHANNELS),
        ("interference_ratio", request.interference_ratio, DEFAULT_INTERFERENCE_RATIO),
        ("collision_model", request.collision_model, DEFAULT_COLLISION_MODEL),
        ("seed", request.seed, DEFAULT_SEED),
    )
    for name, supplied, default in defaults:
        if supplied is None:
            decisions.append(RequirementDecision(
                name, str(default), "Applied documented rule-based workflow default."
            ))
    if request.working_period is None and request.topology is not None:
        decisions.append(RequirementDecision(
            "working_period", str(request.topology.working_period),
            "Used the working period declared by the topology.",
        ))
    if request.communication_range is None and request.topology is not None:
        decisions.append(RequirementDecision(
            "communication_range", str(request.topology.communication_range),
            "Used the communication range declared by the topology.",
        ))
    return tuple(decisions)


def process_request(request: RuleBasedRequest | Mapping[str, Any]) -> WorkflowReport:
    """Execute the complete deterministic Paper 1 workflow."""
    try:
        parsed = request if isinstance(request, RuleBasedRequest) else RuleBasedRequest.from_dict(request)
    except DomainError as exc:
        return WorkflowReport(
            WorkflowStatus.REJECT.value, "The request is malformed.", error=exc.to_dict()
        )

    missing = tuple(name for name in ("topology", "workload", "objective")
                    if getattr(parsed, name) is None)
    if missing:
        return WorkflowReport(
            WorkflowStatus.CLARIFY.value,
            "Critical information is missing; no scientific tool was executed.",
            clarification_questions=tuple(_question(name) for name in missing),
        )
    if parsed.workload != "one_shot":
        return WorkflowReport(
            WorkflowStatus.UNSUPPORTED.value,
            f"Workload {parsed.workload!r} is outside the Paper 1 scope.",
            error={"code": "UNSUPPORTED_WORKLOAD", "field": "workload"},
        )
    if parsed.objective != "minimize_latency":
        return WorkflowReport(
            WorkflowStatus.UNSUPPORTED.value,
            f"Objective {parsed.objective!r} is outside the Paper 1 scope.",
            error={"code": "UNSUPPORTED_OBJECTIVE", "field": "objective"},
        )

    topology = parsed.topology
    assert topology is not None
    channels = parsed.channels if parsed.channels is not None else DEFAULT_CHANNELS
    ratio = (parsed.interference_ratio if parsed.interference_ratio is not None
             else DEFAULT_INTERFERENCE_RATIO)
    collision_model = parsed.collision_model or DEFAULT_COLLISION_MODEL
    seed = parsed.seed if parsed.seed is not None else DEFAULT_SEED
    working_period = (parsed.working_period if parsed.working_period is not None
                      else topology.working_period)
    communication_range = (parsed.communication_range if parsed.communication_range is not None
                           else topology.communication_range)
    decisions = _default_decisions(parsed)
    inspection = result = final_validation = metrics = explanations = None

    try:
        if parsed.latency_target_slots is not None and (
                isinstance(parsed.latency_target_slots, bool)
                or not isinstance(parsed.latency_target_slots, int)
                or parsed.latency_target_slots < 1):
            raise SchemaError("must be a positive integer", path="latency_target_slots",
                              code="INVALID_LATENCY_TARGET")
        if collision_model not in {"legacy_neighbor", "interference_range"}:
            raise SchemaError(
                "must be legacy_neighbor or interference_range",
                path="collision_model", code="INVALID_COLLISION_MODEL",
            )
        # This typed request is the rule-validation boundary for Paper 1 scope.
        SchedulingRequest(
            network=topology, channels=channels, interference_ratio=ratio,
            workload="one_shot", objective="minimize_latency", seed=seed,
        )
        config = AnexConfig(
            working_period=working_period, channels=channels,
            communication_range=communication_range,
            interference_ratio=ratio, seed=seed,
        )
        inspection = inspect_network(topology)
        result = run_anex(topology, config)
        final_validation = validate_schedule(
            topology, result.schedule,
            ValidationMode(collision_model, channels, ratio),
        )
        metrics = measure_schedule(topology, result.schedule)
        if not final_validation.valid:
            explanations = explain_violations(final_validation)
            return WorkflowReport(
                WorkflowStatus.REJECT.value,
                "ANEX produced a schedule that fails the selected validation model.",
                decisions=decisions, inspection=inspection, result=result,
                final_validation=final_validation,
                final_validation_certificate=validation_certificate(final_validation),
                metrics=metrics, latency_target_slots=parsed.latency_target_slots,
                target_satisfied=False,
                tool_trace=_trace_from(inspection, result, final_validation, metrics, explanations),
                error={"code": "SCHEDULE_VALIDATION_FAILED"},
            )
        target_satisfied = (
            None if parsed.latency_target_slots is None
            else metrics.latency_slots <= parsed.latency_target_slots
        )
        message = "ANEX completed and the schedule is valid."
        if target_satisfied is False:
            message = "ANEX produced a valid schedule, but it does not meet the latency target."
        return WorkflowReport(
            WorkflowStatus.EXECUTE.value, message, decisions=decisions,
            inspection=inspection, result=result, final_validation=final_validation,
            final_validation_certificate=validation_certificate(final_validation),
            metrics=metrics, latency_target_slots=parsed.latency_target_slots,
            target_satisfied=target_satisfied,
            tool_trace=_trace_from(inspection, result, final_validation, metrics),
        )
    except DomainError as exc:
        trace = getattr(exc, "trace", None)
        accumulated = list(_trace_from(inspection, result, final_validation, metrics, explanations))
        if trace:
            accumulated.append(TraceRecord.from_dict(trace))
        return WorkflowReport(
            WorkflowStatus.REJECT.value, "The validated request could not be executed.",
            decisions=decisions, inspection=inspection, result=result,
            final_validation=final_validation, metrics=metrics,
            latency_target_slots=parsed.latency_target_slots,
            tool_trace=tuple(accumulated), error=exc.to_dict(),
        )


__all__ = [
    "WorkflowStatus", "ClarificationQuestion", "RuleBasedRequest", "WorkflowReport",
    "DEFAULT_CHANNELS", "DEFAULT_INTERFERENCE_RATIO", "DEFAULT_COLLISION_MODEL",
    "DEFAULT_SEED", "process_request",
]
