"""Bounded, provider-neutral LLM orchestration over deterministic tools."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping, Sequence

from .llm_clients.base import LLMClient, LLMClientError
from .models import AnexConfig
from .request_consistency import (
    RequestConsistencyError, check_request_consistency, explicit_request_fields,
)
from .scope_policy import (CHECKED_TAXONOMY, ScopePolicyReport, evaluate_scope_policy,
                           scope_error_code)
from .schemas import (
    DomainError, JsonSchema, NetworkInstance, SchedulingRequest,
    SchedulingResult, SchemaError, ValidationReport,
)
from .tools import (
    NetworkInspection, ScheduleMetrics, TraceRecord, ValidationMode,
    explain_violations, inspect_network, measure_schedule, run_anex,
    validate_schedule,
)
from .validator import validation_certificate
from .workflows.rule_based import ClarificationQuestion, WorkflowStatus

MAX_RETRIES = 2
PROMPT_VERSION = "paper1-requirements-v4"
# The advisory arm sends the model an extra block, so it is a different prompt
# and says so. The gated and ungated arms are byte-identical to before.
ADVISORY_PROMPT_VERSION = "paper1-requirements-v4-advisory"
# Kept verbatim from the ablation runner so ungated ledgers stay comparable.
ABLATED_POLICY_VERSION = "paper1-scope-policy.v2-ABLATED"
SCOPE_MODES = ("enforcing", "advisory", "off")
APPROVED_TOOL_CALLS = frozenset({
    "inspect_network", "run_anex", "validate_schedule",
    "measure_schedule", "explain_violations",
})
REQUIRED_EXECUTION_TOOLS = frozenset({
    "inspect_network", "run_anex", "validate_schedule", "measure_schedule",
})


class RetryAction(str, Enum):
    REFORMAT_STRUCTURED_OUTPUT = "REFORMAT_STRUCTURED_OUTPUT"
    CORRECT_TYPED_REQUEST = "CORRECT_TYPED_REQUEST"
    RETRY_CLIENT_ERROR = "RETRY_CLIENT_ERROR"


RETRY_ACTION_ALLOWLIST = frozenset(action.value for action in RetryAction)

# SchedulingRequest fields whose contract default applies when the user states
# nothing. A strict structured-output mode has no way to omit a property, so it
# sends null; treating that null as "use the default" keeps a strict-mode
# provider behaving like a provider that can omit the field.
NULL_MEANS_CONTRACT_DEFAULT = frozenset({"seed", "collision_model", "workload", "objective"})


AGENT_DECISION_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "decision_summary", "request", "approved_tool_calls"],
    "properties": {
        "status": {"enum": ["EXECUTE", "CLARIFY", "REJECT", "UNSUPPORTED"]},
        "decision_summary": {"type": "string", "minLength": 1, "maxLength": 500},
        "request": {
            "type": ["object", "null"],
            "description": (
                "Topology-free SchedulingRequest fields. The caller binds the validated network; "
                "network and schedule entries are forbidden here."
            ),
            "additionalProperties": False,
            "required": [
                "channels", "interference_ratio", "workload", "objective",
                "collision_model",
            ],
            "properties": {
                "channels": {"type": "integer", "minimum": 1},
                "interference_ratio": {"type": "number", "minimum": 1},
                "workload": {"const": "one_shot"},
                "objective": {"const": "minimize_latency"},
                "seed": {
                    "type": "integer", "default": 0,
                    "description": (
                        "Use 0 unless the user explicitly states a seed. Never infer it "
                        "from topology names or metadata."
                    ),
                },
                "collision_model": {"enum": ["legacy_neighbor", "interference_range"]},
                "latency_target_slots": {
                    "type": ["integer", "null"], "minimum": 1, "default": None,
                    "description": (
                        "Must be null unless the user explicitly states a numeric latency "
                        "target. Never infer it from topology or working-period values."
                    ),
                },
            },
        },
        "clarification_questions": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["field", "question", "expected_type", "reason"],
                "properties": {
                    "field": {"type": "string"}, "question": {"type": "string"},
                    "expected_type": {"type": "string"}, "reason": {"type": "string"},
                },
            },
        },
        "approved_tool_calls": {
            "type": "array", "uniqueItems": True,
            "items": {"enum": sorted(APPROVED_TOOL_CALLS)},
        },
    },
}


@dataclass(frozen=True)
class AgentDecision(JsonSchema):
    status: Literal["EXECUTE", "CLARIFY", "REJECT", "UNSUPPORTED"]
    decision_summary: str
    request: SchedulingRequest | None = None
    clarification_questions: tuple[ClarificationQuestion, ...] = ()
    approved_tool_calls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {status.value for status in WorkflowStatus}:
            raise SchemaError("invalid orchestration status", path="status", code="INVALID_AGENT_STATUS")
        if not isinstance(self.decision_summary, str) or not self.decision_summary.strip():
            raise SchemaError("must be a concise nonempty summary", path="decision_summary",
                              code="INVALID_DECISION_SUMMARY")
        if len(self.decision_summary) > 500:
            raise SchemaError("must not exceed 500 characters", path="decision_summary",
                              code="DECISION_SUMMARY_TOO_LONG")
        calls = tuple(self.approved_tool_calls)
        if len(set(calls)) != len(calls):
            raise SchemaError("tool calls must be unique", path="approved_tool_calls",
                              code="DUPLICATE_TOOL_CALL")
        unknown = sorted(set(calls) - APPROVED_TOOL_CALLS)
        if unknown:
            raise SchemaError(f"unapproved tool calls: {unknown}", path="approved_tool_calls",
                              code="UNAPPROVED_TOOL_CALL")
        object.__setattr__(self, "approved_tool_calls", calls)
        if self.status == WorkflowStatus.EXECUTE.value and self.request is None:
            raise SchemaError("EXECUTE requires a typed SchedulingRequest", path="request",
                              code="MISSING_SCHEDULING_REQUEST")
        if self.status != WorkflowStatus.EXECUTE.value and self.request is not None:
            raise SchemaError("only EXECUTE may include SchedulingRequest", path="request",
                              code="UNEXPECTED_SCHEDULING_REQUEST")
        if self.status == WorkflowStatus.CLARIFY.value and not self.clarification_questions:
            raise SchemaError("CLARIFY requires questions", path="clarification_questions",
                              code="MISSING_CLARIFICATION_QUESTIONS")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AgentDecision":
        if not isinstance(data, Mapping):
            raise SchemaError("LLM output must be an object", code="MALFORMED_LLM_OUTPUT")
        allowed = {"status", "decision_summary", "request", "clarification_questions",
                   "approved_tool_calls"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise SchemaError(f"unknown LLM output fields: {unknown}", code="MALFORMED_LLM_OUTPUT")
        try:
            raw_request = data.get("request")
            request = (raw_request if isinstance(raw_request, SchedulingRequest)
                       else SchedulingRequest.from_dict(raw_request) if raw_request is not None else None)
            # A strict structured-output mode cannot express an optional property,
            # so an absent list arrives as null rather than missing.
            questions = data.get("clarification_questions") or ()
            return cls(
                status=data["status"], decision_summary=data["decision_summary"], request=request,
                clarification_questions=tuple(ClarificationQuestion.from_dict(item)
                                              for item in questions),
                approved_tool_calls=tuple(data["approved_tool_calls"] or ()),
            )
        except KeyError as exc:
            raise SchemaError("required LLM output field is missing", path=str(exc.args[0]),
                              code="MALFORMED_LLM_OUTPUT") from exc

    @classmethod
    def from_llm_dict(cls, data: Mapping[str, Any],
                      topology: NetworkInstance | None) -> "AgentDecision":
        """Bind trusted caller topology to an untrusted topology-free draft."""
        if not isinstance(data, Mapping):
            raise SchemaError("LLM output must be an object", code="MALFORMED_LLM_OUTPUT")
        payload = dict(data)
        raw_request = payload.get("request")
        if raw_request is not None:
            if not isinstance(raw_request, Mapping):
                raise SchemaError("request must be an object or null", path="request",
                                  code="MALFORMED_LLM_OUTPUT")
            forbidden = sorted(set(raw_request) & {"network", "schedule"})
            if forbidden:
                raise SchemaError(
                    f"LLM request contains forbidden fields: {forbidden}", path="request",
                    code="TOPOLOGY_OR_SCHEDULE_OUTPUT_FORBIDDEN",
                )
            if topology is None:
                raise SchemaError("EXECUTE requires a caller-supplied topology",
                                  path="request", code="MISSING_TOPOLOGY")
            # Under a strict structured-output mode every property must be present,
            # so a field the user did not state arrives as null. For fields that
            # carry a contract default, null means "not stated": drop it and let the
            # default apply, rather than failing the type check. latency_target_slots
            # is not in this set because null is its meaningful value.
            stated = {name: value for name, value in dict(raw_request).items()
                      if not (value is None and name in NULL_MEANS_CONTRACT_DEFAULT)}
            payload["request"] = {"network": topology.to_dict(), **stated}
        return cls.from_dict(payload)


@dataclass(frozen=True)
class LLMInteractionLog(JsonSchema):
    attempt: int
    prompt: str
    model_metadata: dict[str, Any]
    structured_output: dict[str, Any] | None
    decision_summary: str | None
    error: dict[str, Any] | None = None
    retry_action: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LLMInteractionLog":
        return cls(**dict(data))


@dataclass(frozen=True)
class RequirementAgentResult(JsonSchema):
    decision: AgentDecision | None
    logs: tuple[LLMInteractionLog, ...]
    retry_count: int
    error: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RequirementAgentResult":
        payload = dict(data)
        if payload.get("decision") is not None:
            payload["decision"] = AgentDecision.from_dict(payload["decision"])
        payload["logs"] = tuple(LLMInteractionLog.from_dict(item) for item in payload["logs"])
        return cls(**payload)


@dataclass(frozen=True)
class OrchestrationReport(JsonSchema):
    status: Literal["EXECUTE", "CLARIFY", "REJECT", "UNSUPPORTED"]
    message: str
    decision_summary: str
    request: SchedulingRequest | None = None
    clarification_questions: tuple[ClarificationQuestion, ...] = ()
    inspection: NetworkInspection | None = None
    result: SchedulingResult | None = None
    final_validation: ValidationReport | None = None
    validation_certificate: dict[str, Any] | None = None
    metrics: ScheduleMetrics | None = None
    target_satisfied: bool | None = None
    llm_logs: tuple[LLMInteractionLog, ...] = ()
    tool_trace: tuple[TraceRecord, ...] = ()
    retry_count: int = 0
    error: dict[str, Any] | None = None
    scope_policy: ScopePolicyReport | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OrchestrationReport":
        payload = dict(data)
        for name, schema in (("request", SchedulingRequest), ("inspection", NetworkInspection),
                             ("result", SchedulingResult), ("final_validation", ValidationReport),
                             ("metrics", ScheduleMetrics)):
            if payload.get(name) is not None:
                payload[name] = schema.from_dict(payload[name])
        payload["clarification_questions"] = tuple(
            ClarificationQuestion.from_dict(item) for item in payload.get("clarification_questions", ()))
        payload["llm_logs"] = tuple(LLMInteractionLog.from_dict(item) for item in payload.get("llm_logs", ()))
        payload["tool_trace"] = tuple(TraceRecord.from_dict(item) for item in payload.get("tool_trace", ()))
        if payload.get("scope_policy") is not None:
            payload["scope_policy"] = ScopePolicyReport.from_dict(payload["scope_policy"])
        return cls(**payload)


def _advisory_block(report: "ScopePolicyReport") -> str:
    """Hand the gate's finding to the model instead of acting on it.

    The enforcing gate short-circuits, so its over-blocks are unrecoverable by
    construction: no later stage ever sees the request. An advisory gate keeps
    the same detector and moves the decision, which is the only difference the
    arm is meant to measure. The notice therefore states what matched and says
    plainly that it is not binding --- a notice the model cannot overrule is
    the enforcing gate with extra steps.
    """
    matched = ", ".join(sorted({violation.category for violation in report.violations}))
    witnesses = "; ".join(f"{violation.category}: {violation.witness!r}"
                          for violation in report.violations)
    return (
        "\nADVISORY SCOPE NOTICE:\n"
        "- A separate scope policy read the raw request before you and matched "
        f"these out-of-scope capability categories: {matched}.\n"
        f"- The text it matched on: {witnesses}.\n"
        "- This notice is advisory and not binding. The policy matches wording, "
        "not meaning, and it is wrong when a request mentions a capability "
        "without asking for it.\n"
        "- Decide the action yourself under the DECISION POLICY below. Return "
        "UNSUPPORTED only if the request actually asks for a capability the "
        "system does not have.\n"
    )


def _prompt(user_request: str, topology: NetworkInstance | None,
            correction: str | None = None,
            scope_advisory: "ScopePolicyReport | None" = None) -> str:
    context = "null" if topology is None else json.dumps({
        "supplied": True,
        "node_count": len(topology.nodes),
        "sink_id": topology.sink_id,
    }, sort_keys=True, separators=(",", ":"))
    # prompt = (
    #     "Extract Paper 1 scheduling requirements into the supplied JSON schema. "
    #     "Never create, edit, or return schedule entries. Use only approved tool names. "
    #     "Return a concise decision_summary, never hidden reasoning.\n"
    #     f"USER_REQUEST={json.dumps(user_request)}\nTOPOLOGY={context}"
    # )
    advisory = (_advisory_block(scope_advisory)
                if scope_advisory is not None and scope_advisory.violations else "")
    prompt = (
        f"PROMPT_VERSION={ADVISORY_PROMPT_VERSION if advisory else PROMPT_VERSION}\n"
        f"CALLER_NETWORK_STATE={'VALIDATED_AND_BOUND' if topology is not None else 'ABSENT'}\n"
        "The orchestrator owns topology availability. When CALLER_NETWORK_STATE is "
        "VALIDATED_AND_BOUND, the network exists and is already bound: never ask for, "
        "resolve, load, or infer a topology.\n"
        "Interpret the user's request for the Paper 1 ANEX workflow and return "
        "one object matching the supplied JSON schema.\n\n"

        "ROLE BOUNDARY:\n"
        "- You must never construct, edit, or return ScheduleEntry values.\n"
        "- This restriction does not prohibit scheduling requests.\n"
        "- The deterministic run_anex tool, not the LLM, computes the schedule.\n"
        "- For a supported one-shot minimum-latency request, return EXECUTE and "
        "approve the required deterministic tools.\n"
        "- Do not return UNSUPPORTED merely because a schedule must be computed.\n\n"

        "SUPPORTED PAPER 1 SCOPE:\n"
        "- workload: one_shot\n"
        "- objective: minimize_latency\n"
        "- required tools: inspect_network, run_anex, validate_schedule, "
        "measure_schedule\n\n"

        "DOCUMENTED NON-CRITICAL DEFAULTS:\n"
        "- channels: 2\n"
        "- interference_ratio: 1.0\n"
        "- collision_model: legacy_neighbor\n"
        "- seed: 0\n"
        "- Apply a default only when that field is omitted.\n"
        "- Never replace an explicitly invalid value with a default.\n\n"

        "FIELD PROVENANCE RULES:\n"
        "- latency_target_slots must be null unless USER_REQUEST explicitly states "
        "a numeric latency target.\n"
        "- Never infer a latency target from working_period, active slots, topology "
        "metadata, node count, or communication parameters.\n"
        "- seed must be 0 unless USER_REQUEST explicitly states another seed.\n"
        "- A topology identifier containing text such as seed7 is not an explicit "
        "SchedulingRequest seed. Only a separate instruction such as 'seed 7' is explicit.\n"
        "- Never infer seed from topology names, topology metadata, or filenames.\n\n"

        "DECISION POLICY:\n"
        "Apply these rules in order:\n"
        "- UNSUPPORTED: unsupported objective or workload, such as energy "
        "optimization or Digital Twin execution.\n"
        "- Topology presence is not an LLM decision. The orchestrator handles an absent "
        "topology before calling you. Never return a topology clarification.\n"
        "- REJECT: any explicitly malformed or invalid parameter. Zero channels, "
        "negative channels, or a statement that no radio channel is available must "
        "be REJECT, with request=null and no approved tool calls.\n"
        "- Never repair, ignore, or replace an explicitly invalid parameter.\n"
        "- EXECUTE: only after the scope, topology, and explicit parameter checks pass.\n"
        "- For EXECUTE, approve all four tools exactly: inspect_network, run_anex, "
        "validate_schedule, measure_schedule.\n\n"

        "TOPOLOGY POLICY:\n"
        "- TOPOLOGY_CONTEXT only confirms caller-supplied network metadata.\n"
        "- Never return a network or schedule in structured output.\n"
        "- The RequirementAgent deterministically binds the validated caller topology.\n\n"

        "OUTPUT REQUIREMENTS:\n"
        "- The request field is mandatory in every response.\n"
        "- If status is EXECUTE, request must be a complete non-null topology-free "
        "request object matching the schema.\n"
        "- If status is CLARIFY, REJECT, or UNSUPPORTED, request must be null.\n"
        "- Never omit request when status is EXECUTE.\n\n"
        "Return only structured output matching the supplied schema. "
        "Use a concise decision_summary and never hidden reasoning.\n"
        f"USER_REQUEST={json.dumps(user_request)}\n"
        f"TOPOLOGY_CONTEXT={context}"
        + advisory
    )
    if correction:
        prompt += f"\nCORRECTION={json.dumps(correction)}"
    return prompt


class RequirementAgent:
    def __init__(self, client: LLMClient, *, max_retries: int = MAX_RETRIES):
        if not 0 <= max_retries <= MAX_RETRIES:
            raise ValueError(f"max_retries must be in [0, {MAX_RETRIES}]")
        self.client = client
        self.max_retries = max_retries

    def analyze(self, user_request: str, topology: NetworkInstance | None,
                scope_advisory: ScopePolicyReport | None = None) -> RequirementAgentResult:
        if not isinstance(user_request, str) or not user_request.strip():
            error = SchemaError("must be nonempty text", path="user_request", code="INVALID_USER_REQUEST")
            return RequirementAgentResult(None, (), 0, error.to_dict())
        logs: list[LLMInteractionLog] = []
        correction = None
        for attempt in range(self.max_retries + 1):
            prompt = _prompt(user_request, topology, correction, scope_advisory)
            raw: dict[str, Any] | None = None
            metadata: dict[str, Any] = {}
            try:
                response = self.client.generate_structured(
                    prompt=prompt, response_schema=AGENT_DECISION_JSON_SCHEMA
                )
                raw = json.loads(json.dumps(dict(response.structured_output), sort_keys=True))
                metadata = json.loads(json.dumps(dict(response.model_metadata), sort_keys=True))
                decision = AgentDecision.from_llm_dict(raw, topology)
                if (decision.status == WorkflowStatus.CLARIFY.value and topology is not None
                        and any(question.field == "topology"
                                for question in decision.clarification_questions)):
                    raise SchemaError(
                        "LLM requested topology although validated topology context was supplied",
                        path="topology", code="FALSE_MISSING_TOPOLOGY",
                    )
                if decision.status == WorkflowStatus.EXECUTE.value and topology is None:
                    raise SchemaError("EXECUTE requires a caller-supplied topology",
                                      path="request.network", code="MISSING_TOPOLOGY")
                if decision.request is not None and topology is not None and decision.request.network != topology:
                    raise SchemaError("LLM must not replace or edit the supplied topology",
                                      path="request.network", code="TOPOLOGY_SUBSTITUTION_FORBIDDEN")
                if decision.request is not None and topology is not None:
                    check_request_consistency(user_request, topology, decision.request)
                logs.append(LLMInteractionLog(
                    attempt, prompt, metadata, raw, decision.decision_summary
                ))
                return RequirementAgentResult(decision, tuple(logs), attempt)
            except (DomainError, TypeError, ValueError) as exc:
                error = exc.to_dict() if isinstance(exc, DomainError) else {
                    "category": "schema_error", "code": "MALFORMED_LLM_OUTPUT",
                    "message": str(exc), "path": None,
                }
                retry_action = (RetryAction.CORRECT_TYPED_REQUEST.value
                                if isinstance(exc, DomainError) and exc.code != "MALFORMED_LLM_OUTPUT"
                                else RetryAction.REFORMAT_STRUCTURED_OUTPUT.value)
                if retry_action not in RETRY_ACTION_ALLOWLIST:
                    raise RuntimeError("retry action escaped allowlist")
                # A topology clarification contradicts trusted caller state and
                # repeated retries have no scientific value.
                will_retry = attempt < self.max_retries and error["code"] != "FALSE_MISSING_TOPOLOGY"
                logs.append(LLMInteractionLog(
                    attempt, prompt, metadata, raw, None, error,
                    retry_action if will_retry else None,
                ))
                if not will_retry:
                    return RequirementAgentResult(None, tuple(logs), attempt, error)
                correction = f"{retry_action}: {error['code']} - {error['message']}"
                if isinstance(exc, RequestConsistencyError):
                    mismatches = [item for item in exc.report.to_dict()["checks"]
                                  if item["status"] == "mismatch"]
                    correction += f"; required_field_corrections={json.dumps(mismatches, sort_keys=True)}"
            except Exception as exc:
                error = {
                    "category": "client_error",
                    "code": exc.code if isinstance(exc, LLMClientError) else "LLM_CLIENT_ERROR",
                    "message": str(exc), "path": None,
                }
                will_retry = attempt < self.max_retries
                action = RetryAction.RETRY_CLIENT_ERROR.value
                logs.append(LLMInteractionLog(
                    attempt, prompt, metadata, raw, None, error,
                    action if will_retry else None,
                ))
                if not will_retry:
                    return RequirementAgentResult(None, tuple(logs), attempt, error)
                correction = f"{action}: {type(exc).__name__}"
        raise RuntimeError("unreachable retry state")


class DeterministicFinalReporter:
    def report_non_execute(self, agent: RequirementAgentResult) -> OrchestrationReport:
        if agent.decision is None:
            return OrchestrationReport(
                WorkflowStatus.REJECT.value,
                "The model did not return a valid structured decision.", "Structured output rejected.",
                llm_logs=agent.logs, retry_count=agent.retry_count, error=agent.error,
            )
        decision = agent.decision
        messages = {
            "CLARIFY": "Additional structured requirements are needed before execution.",
            "REJECT": "The request was rejected before scientific execution.",
            "UNSUPPORTED": "The request is outside the Paper 1 scope.",
        }
        return OrchestrationReport(
            decision.status, messages[decision.status], decision.decision_summary,
            clarification_questions=decision.clarification_questions,
            llm_logs=agent.logs, retry_count=agent.retry_count,
        )

    def report_execution(
        self, agent: RequirementAgentResult, inspection: NetworkInspection,
        result: SchedulingResult, final_validation: ValidationReport,
        metrics: ScheduleMetrics, traces: tuple[TraceRecord, ...],
    ) -> OrchestrationReport:
        decision = agent.decision
        assert decision is not None and decision.request is not None
        certificate = validation_certificate(final_validation)
        certificate_passes = (
            certificate.get("certificate_format") == "agentic_anex.validation_certificate.v1"
            and certificate.get("valid") is True
            and not certificate.get("violations")
        )
        if not final_validation.valid or not certificate_passes:
            return OrchestrationReport(
                WorkflowStatus.REJECT.value,
                "Scientific validation failed; no successful response was issued.",
                decision.decision_summary, request=decision.request,
                inspection=inspection, result=result, final_validation=final_validation,
                validation_certificate=certificate, metrics=metrics,
                target_satisfied=False, llm_logs=agent.logs, tool_trace=traces,
                retry_count=agent.retry_count, error={"code": "VALIDATION_CERTIFICATE_FAILED"},
            )
        target = decision.request.latency_target_slots
        target_satisfied = None if target is None else metrics.latency_slots <= target
        message = "ANEX completed with a passing independent validation certificate."
        if target_satisfied is False:
            message = "The schedule is valid but does not satisfy the requested latency target."
        return OrchestrationReport(
            WorkflowStatus.EXECUTE.value, message, decision.decision_summary,
            request=decision.request, inspection=inspection, result=result,
            final_validation=final_validation, validation_certificate=certificate,
            metrics=metrics, target_satisfied=target_satisfied,
            llm_logs=agent.logs, tool_trace=traces, retry_count=agent.retry_count,
        )


def _trace(*outputs: Any) -> tuple[TraceRecord, ...]:
    return tuple(TraceRecord.from_dict(output.trace) for output in outputs
                 if output is not None and getattr(output, "trace", None))


class Orchestrator:
    """The six-stage pipeline, with the scope gate's authority as a parameter.

    `scope_mode` selects what stage 1 does with what it finds, and nothing
    else about the pipeline changes:

      enforcing  a match short-circuits the run to UNSUPPORTED before the
                 model is called. The production configuration.
      advisory   the same match is passed to the model as a non-binding
                 notice and the model decides. Section 8.1's hypothesis: a
                 gate that annotates should degrade more gracefully than one
                 that short-circuits, because its over-blocks stay
                 recoverable.
      off        the gate is not consulted. The ablation arm.

    The detector is identical in all three; only its authority moves.
    """

    def __init__(self, requirement_agent: RequirementAgent,
                 reporter: DeterministicFinalReporter | None = None,
                 *, scope_mode: str = "enforcing"):
        if scope_mode not in SCOPE_MODES:
            raise ValueError(f"scope_mode must be one of {SCOPE_MODES}")
        self.requirement_agent = requirement_agent
        self.reporter = reporter or DeterministicFinalReporter()
        self.scope_mode = scope_mode

    def run(self, user_request: str, topology: NetworkInstance | None) -> OrchestrationReport:
        # Policy v2 reads the raw request before the LLM. Under `enforcing` a
        # later structured request or valid schedule cannot override an
        # unsupported capability.
        if self.scope_mode == "off":
            scope_policy = ScopePolicyReport(True, CHECKED_TAXONOMY, (),
                                             policy_version=ABLATED_POLICY_VERSION)
        else:
            scope_policy = evaluate_scope_policy(user_request)
        advisory = scope_policy if self.scope_mode == "advisory" else None
        if self.scope_mode == "enforcing" and not scope_policy.supported:
            code = scope_error_code(scope_policy)
            return OrchestrationReport(
                WorkflowStatus.UNSUPPORTED.value,
                "The independent raw-request scope policy rejected an unsupported capability.",
                "Paper 1 scope policy takes precedence over LLM interpretation and schedule validity.",
                error={"code": code, "field": "scope", "policy_version": scope_policy.policy_version},
                scope_policy=scope_policy,
            )
        explicit = explicit_request_fields(user_request)
        invalid = (
            ("channels", "INVALID_CHANNEL_COUNT", lambda value: value < 1),
            ("interference_ratio", "INVALID_INTERFERENCE_RATIO", lambda value: value < 1),
            ("latency_target_slots", "INVALID_LATENCY_TARGET", lambda value: value < 1),
            ("working_period", "INVALID_WORKING_PERIOD", lambda value: value < 1),
            ("communication_range", "INVALID_COMMUNICATION_RANGE", lambda value: value <= 0),
            ("seed", "INVALID_SEED", lambda value: value < 0),
        )
        for field_name, code, predicate in invalid:
            if field_name in explicit and predicate(explicit[field_name]):
                return OrchestrationReport(
                    WorkflowStatus.REJECT.value,
                    "An explicit request parameter is invalid.",
                    f"The explicit {field_name} value is outside its valid domain.",
                    error={"code": code, "field": field_name, "value": explicit[field_name]},
                    scope_policy=scope_policy,
                )
        if topology is None:
            return OrchestrationReport(
                WorkflowStatus.CLARIFY.value,
                "A validated network topology is required before requirement interpretation.",
                "Topology availability is resolved deterministically by the orchestrator.",
                clarification_questions=(ClarificationQuestion(
                    "topology", "Which validated network topology should be scheduled?",
                    "NetworkInstance",
                    "ANEX cannot execute without nodes, links, active slots, and a sink.",
                ),),
                error={"code": "MISSING_TOPOLOGY", "field": "topology"},
                scope_policy=scope_policy,
            )
        agent_result = self.requirement_agent.analyze(user_request, topology, advisory)
        if agent_result.decision is None or agent_result.decision.status != WorkflowStatus.EXECUTE.value:
            report = self.reporter.report_non_execute(agent_result)
            return OrchestrationReport.from_dict({**report.to_dict(),
                                                  "scope_policy": scope_policy.to_dict()})
        decision = agent_result.decision
        request = decision.request
        assert request is not None
        missing_tools = sorted(REQUIRED_EXECUTION_TOOLS - set(decision.approved_tool_calls))
        if missing_tools:
            return OrchestrationReport(
                WorkflowStatus.REJECT.value,
                "Required deterministic tools were not approved.", decision.decision_summary,
                request=request, llm_logs=agent_result.logs, retry_count=agent_result.retry_count,
                error={"code": "MISSING_REQUIRED_TOOL_CALL", "tools": missing_tools},
                scope_policy=scope_policy,
            )
        inspection = result = final_validation = metrics = explanations = None
        try:
            inspection = inspect_network(request.network)
            result = run_anex(request.network, request.to_anex_config())
            final_validation = validate_schedule(
                request.network, result.schedule,
                ValidationMode(request.collision_model, request.channels,
                               request.interference_ratio),
            )
            # Metrics are deterministic and needed by the final reporter even
            # if the LLM omitted the optional request for that tool.
            metrics = measure_schedule(request.network, result.schedule)
            if not final_validation.valid and "explain_violations" in decision.approved_tool_calls:
                explanations = explain_violations(final_validation)
            traces = _trace(inspection, result, final_validation, metrics, explanations)
            report = self.reporter.report_execution(
                agent_result, inspection, result, final_validation, metrics, traces
            )
            return OrchestrationReport.from_dict({**report.to_dict(),
                                                  "scope_policy": scope_policy.to_dict()})
        except DomainError as exc:
            traces = list(_trace(inspection, result, final_validation, metrics, explanations))
            if getattr(exc, "trace", None):
                traces.append(TraceRecord.from_dict(exc.trace))
            return OrchestrationReport(
                WorkflowStatus.REJECT.value,
                "A deterministic scientific tool rejected the request.",
                decision.decision_summary, request=request, inspection=inspection,
                result=result, final_validation=final_validation, metrics=metrics,
                llm_logs=agent_result.logs, tool_trace=tuple(traces),
                retry_count=agent_result.retry_count, error=exc.to_dict(),
                scope_policy=scope_policy,
            )
        except Exception as exc:
            traces = list(_trace(inspection, result, final_validation, metrics, explanations))
            if getattr(exc, "trace", None):
                traces.append(TraceRecord.from_dict(exc.trace))
            return OrchestrationReport(
                WorkflowStatus.REJECT.value,
                "An internal scientific-tool exception prevented execution.",
                decision.decision_summary, request=request, inspection=inspection,
                result=result, final_validation=final_validation, metrics=metrics,
                llm_logs=agent_result.logs, tool_trace=tuple(traces),
                retry_count=agent_result.retry_count,
                error={"category": "internal_exception", "code": "INTERNAL_TOOL_EXCEPTION",
                       "error_type": type(exc).__name__},
                scope_policy=scope_policy,
            )


__all__ = [
    "MAX_RETRIES", "PROMPT_VERSION", "ADVISORY_PROMPT_VERSION", "ABLATED_POLICY_VERSION",
    "SCOPE_MODES", "APPROVED_TOOL_CALLS", "REQUIRED_EXECUTION_TOOLS",
    "RetryAction", "RETRY_ACTION_ALLOWLIST", "AGENT_DECISION_JSON_SCHEMA",
    "AgentDecision", "LLMInteractionLog", "RequirementAgentResult",
    "OrchestrationReport", "RequirementAgent", "DeterministicFinalReporter", "Orchestrator",
]
