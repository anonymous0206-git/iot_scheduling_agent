"""Reproducible append-only experiment execution and paired analysis."""

from __future__ import annotations

import csv
import fcntl
import json
import math
import os
import random
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from .schemas import JsonSchema, NetworkInstance
from .topology_io import generate_network_instance
from .workflows.rule_based import WorkflowReport, process_request
from .llm_clients.base import LLMClient
from .llm_clients.factory import ProviderConfig, create_llm_client
from .orchestration import OrchestrationReport, Orchestrator, RequirementAgent
from .scope_policy import evaluate_scope_policy, scope_error_code

RAW_SCHEMA_VERSION = "agentic_anex.experiment_record.v1"


@dataclass(frozen=True)
class SystemRunOutput:
    parsed_fields: dict[str, Any]
    action: str
    tool_trace: tuple[dict[str, Any], ...] = ()
    schedule_metrics: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_calls: int = 0
    success: bool = False
    failure_category: str | None = None
    clarification_fields: tuple[str, ...] = ()
    error_code: str | None = None
    decision_summary: str | None = None
    llm_logs: tuple[dict[str, Any], ...] = ()
    scope_policy: dict[str, Any] | None = None


class ExperimentSystem(Protocol):
    system_name: str
    model_name: str

    def run(self, item: Mapping[str, Any], topology: NetworkInstance | None, seed: int) -> SystemRunOutput:
        ...


@dataclass(frozen=True)
class ExperimentRecord(JsonSchema):
    schema_version: str
    request_id: str
    paraphrase_group_id: str
    topology_id: str | None
    system: str
    model: str
    seed: int
    parsed_fields: dict[str, Any]
    action: str
    gold_action: str
    tool_trace: tuple[dict[str, Any], ...]
    schedule_metrics: dict[str, Any] | None
    validation: dict[str, Any] | None
    retries: int
    wall_time_seconds: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model_calls: int
    success: bool
    failure_category: str | None
    category: str
    complexity_level: str
    clarification_fields: tuple[str, ...] = ()
    error_code: str | None = None
    decision_summary: str | None = None
    llm_logs: tuple[dict[str, Any], ...] = ()
    scope_policy: dict[str, Any] | None = None

    @property
    def key(self) -> tuple[str, str | None, str, str, int]:
        return self.request_id, self.topology_id, self.system, self.model, self.seed

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExperimentRecord":
        payload = dict(data)
        payload["tool_trace"] = tuple(payload.get("tool_trace", ()))
        payload["clarification_fields"] = tuple(payload.get("clarification_fields", ()))
        payload["llm_logs"] = tuple(payload.get("llm_logs", ()))
        return cls(**payload)


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    records = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{source}:{line_number}: corrupt JSONL record: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{source}:{line_number}: record must be an object")
        records.append(value)
    return records


def load_experiment_records(path: str | Path) -> list[ExperimentRecord]:
    records = [ExperimentRecord.from_dict(item) for item in load_jsonl(path)]
    keys = [record.key for record in records]
    if len(keys) != len(set(keys)):
        raise ValueError("raw experiment ledger contains duplicate completed keys")
    return records


def resolve_topology(topology_id: str | None) -> NetworkInstance | None:
    if topology_id is None:
        return None
    if topology_id == "legacy30_seed7":
        return generate_network_instance(
            node_count=30, x_range=40, y_range=40, communication_range=18,
            working_period=10, active_slots_per_node=2, seed=7,
        )
    raise ValueError(f"unknown topology_id: {topology_id}")


def _number(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


class RuleBasedBenchmarkSystem:
    """Controlled-template parser used as the deterministic benchmark baseline.

    The arm runs the same pre-model scope gate the agent runs, for the same
    reason the agent does: the gate reads the raw request and is not part of
    any one interpreter, so an arm that skipped it would not be the pipeline
    minus its model, it would be a different pipeline. The parser's own
    objective and workload rules still apply to whatever the gate passes, and
    the two are distinguishable in the ledger because a gate refusal carries a
    `scope_policy` block and a parser refusal does not.
    """

    system_name = "rule_based"
    model_name = "deterministic"

    def run(self, item: Mapping[str, Any], topology: NetworkInstance | None, seed: int) -> SystemRunOutput:
        text = str(item["user_text"])
        scope_policy = evaluate_scope_policy(text)
        if not scope_policy.supported:
            return SystemRunOutput(
                parsed_fields={},
                action="UNSUPPORTED",
                success=False,
                failure_category="unsupported",
                error_code=scope_error_code(scope_policy),
                decision_summary="The independent raw-request scope policy rejected an "
                                 "unsupported capability.",
                scope_policy=scope_policy.to_dict(),
            )
        lowered = text.lower()
        objective = "minimize_latency"
        if "energy" in lowered or "battery" in lowered or "network lifetime" in lowered:
            objective = "minimize_energy"
        elif "digital twin" in lowered or "virtual replica" in lowered:
            objective = "digital_twin"
        channels = None
        if "zero channels" in lowered or "no available radio channel" in lowered:
            channels = 0
        else:
            parsed_channels = _number(lowered, r"(?:use|using|with)\s+(\d+)\s+(?:channels|frequencies)")
            channels = int(parsed_channels) if parsed_channels is not None else None
        ratio = _number(lowered, r"(?:alpha|interference ratio)\s+(?:of\s+)?([0-9]+(?:\.[0-9]+)?)")
        if "alpha of one half" in lowered:
            ratio = 0.5
        target = _number(lowered, r"(?:target of|within)\s+(\d+)\s+slots")
        collision_model = ("interference_range" if any(
            phrase in lowered for phrase in ("geometric collision", "times the communication range")
        ) else None)
        request = {
            "topology": topology,
            "workload": "one_shot",
            "objective": objective,
            "latency_target_slots": int(target) if target is not None else None,
            "channels": channels,
            "interference_ratio": ratio,
            "collision_model": collision_model,
            "seed": seed,
        }
        report = process_request(request)
        output = workflow_report_to_output(report, request)
        return replace(output, scope_policy=scope_policy.to_dict())


# One arm name per scope mode, so the ledger never has to be read alongside a
# separate note about which configuration produced it. The enforcing and off
# names are the ones already written into the v3 ledgers.
SCOPE_MODE_SYSTEM_NAMES = {
    "enforcing": "llm_agent",
    "advisory": "llm_agent_advisory_scope_gate",
    "off": "llm_agent_no_scope_gate",
}


class AgentBenchmarkSystem:
    """Provider-neutral experiment adapter for the bounded LLM orchestrator."""

    system_name = "llm_agent"

    def __init__(self, client: LLMClient, model_name: str, *, max_retries: int = 2,
                 scope_mode: str = "enforcing"):
        if not model_name:
            raise ValueError("model_name must be nonempty")
        if scope_mode not in SCOPE_MODE_SYSTEM_NAMES:
            raise ValueError(f"scope_mode must be one of {tuple(SCOPE_MODE_SYSTEM_NAMES)}")
        self.client = client
        self.model_name = model_name
        self.max_retries = max_retries
        self.scope_mode = scope_mode
        self.system_name = SCOPE_MODE_SYSTEM_NAMES[scope_mode]

    def run(self, item: Mapping[str, Any], topology: NetworkInstance | None, seed: int) -> SystemRunOutput:
        report = Orchestrator(RequirementAgent(
            self.client, max_retries=self.max_retries
        ), scope_mode=self.scope_mode).run(str(item["user_text"]), topology)
        return orchestration_report_to_output(report)


class ProviderAgentBenchmarkSystem:
    """Create the explicitly configured provider afresh for each seeded run."""

    system_name = "llm_agent"

    def __init__(self, config: ProviderConfig, *, scope_mode: str = "enforcing"):
        if not isinstance(config, ProviderConfig):
            raise TypeError("config must be a ProviderConfig")
        if config.provider == "mock":
            raise ValueError("mock is not a production experiment provider")
        if scope_mode not in SCOPE_MODE_SYSTEM_NAMES:
            raise ValueError(f"scope_mode must be one of {tuple(SCOPE_MODE_SYSTEM_NAMES)}")
        self.config = config
        self.model_name = config.model
        self.scope_mode = scope_mode
        self.system_name = SCOPE_MODE_SYSTEM_NAMES[scope_mode]

    def run(self, item: Mapping[str, Any], topology: NetworkInstance | None,
            seed: int) -> SystemRunOutput:
        seeded_config = replace(self.config, seed=seed)
        client = create_llm_client(seeded_config)
        return AgentBenchmarkSystem(
            client, self.model_name, max_retries=seeded_config.max_retries,
            scope_mode=self.scope_mode,
        ).run(item, topology, seed)


def workflow_report_to_output(report: WorkflowReport,
                              parsed_fields: Mapping[str, Any]) -> SystemRunOutput:
    validation = report.final_validation.to_dict() if report.final_validation else None
    metrics = report.metrics.to_dict() if report.metrics else None
    success = report.status == "EXECUTE" and report.final_validation is not None and report.final_validation.valid
    if success and report.target_satisfied is False:
        failure = "latency_target_not_met"
    elif success:
        failure = None
    elif report.status == "UNSUPPORTED":
        failure = "unsupported"
    elif report.status == "CLARIFY":
        failure = "clarification_required"
    elif report.error and report.error.get("code") == "SCHEDULE_VALIDATION_FAILED":
        failure = "invalid_schedule"
    else:
        failure = "rejected"
    serializable_fields = {
        key: (value.to_dict() if isinstance(value, JsonSchema) else value)
        for key, value in parsed_fields.items()
    }
    return SystemRunOutput(
        parsed_fields=serializable_fields,
        action=report.status,
        tool_trace=tuple(trace.to_dict() for trace in report.tool_trace),
        schedule_metrics=metrics,
        validation=validation,
        retries=0,
        success=success,
        failure_category=failure,
        clarification_fields=tuple(question.field for question in report.clarification_questions),
        error_code=report.error.get("code") if report.error else None,
    )


def orchestration_report_to_output(report: OrchestrationReport) -> SystemRunOutput:
    validation = report.final_validation.to_dict() if report.final_validation else None
    metrics = report.metrics.to_dict() if report.metrics else None
    success = report.status == "EXECUTE" and bool(
        report.validation_certificate and report.validation_certificate.get("valid")
    )
    if success and report.target_satisfied is False:
        failure = "latency_target_not_met"
    elif success:
        failure = None
    elif report.status == "UNSUPPORTED":
        failure = "unsupported"
    elif report.status == "CLARIFY":
        failure = "clarification_required"
    elif report.error and report.error.get("code") == "VALIDATION_CERTIFICATE_FAILED":
        failure = "invalid_schedule"
    else:
        failure = "rejected"
    prompt_tokens = completion_tokens = 0
    for log in report.llm_logs:
        metadata = log.model_metadata
        usage = metadata.get("usage", {}) if isinstance(metadata.get("usage", {}), Mapping) else {}
        prompt_tokens += int(metadata.get("prompt_tokens", usage.get("prompt_tokens", 0)) or 0)
        completion_tokens += int(metadata.get("completion_tokens", usage.get("completion_tokens", 0)) or 0)
    parsed = report.request.to_dict() if report.request else {}
    return SystemRunOutput(
        parsed_fields=parsed,
        action=report.status,
        tool_trace=tuple(trace.to_dict() for trace in report.tool_trace),
        schedule_metrics=metrics,
        validation=validation,
        retries=report.retry_count,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model_calls=len(report.llm_logs),
        success=success,
        failure_category=failure,
        clarification_fields=tuple(question.field for question in report.clarification_questions),
        error_code=report.error.get("code") if report.error else None,
        decision_summary=report.decision_summary,
        llm_logs=tuple(log.to_dict() for log in report.llm_logs),
        scope_policy=report.scope_policy.to_dict() if report.scope_policy else None,
    )


def _append_record(path: Path, record: ExperimentRecord) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        existing = []
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                existing.append(ExperimentRecord.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: corrupt raw ledger") from exc
        keys = [item.key for item in existing]
        if len(keys) != len(set(keys)):
            raise ValueError("raw experiment ledger contains duplicate completed keys")
        if record.key in set(keys):
            return False
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        return True


def run_experiment_matrix(
    benchmark_items: Sequence[Mapping[str, Any]],
    systems: Sequence[ExperimentSystem],
    seeds: Sequence[int],
    raw_output: str | Path,
    *, topology_resolver: Callable[[str | None], NetworkInstance | None] = resolve_topology,
) -> dict[str, int]:
    if not benchmark_items or not systems or not seeds:
        raise ValueError("benchmark_items, systems, and seeds must be nonempty")
    request_ids = [str(item["request_id"]) for item in benchmark_items]
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("benchmark request IDs must be unique")
    system_ids = [(system.system_name, system.model_name) for system in systems]
    if len(system_ids) != len(set(system_ids)):
        raise ValueError("system/model pairs must be unique")
    if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds):
        raise ValueError("seeds must be integers")

    output_path = Path(raw_output)
    completed = {record.key for record in load_experiment_records(output_path)}
    expected_keys = {
        (item["request_id"], item.get("topology_id"), system.system_name, system.model_name, seed)
        for item in benchmark_items for system in systems for seed in seeds
    }
    written = skipped = 0
    topology_cache: dict[str | None, NetworkInstance | None] = {}
    for item in benchmark_items:
        topology_id = item.get("topology_id")
        if topology_id not in topology_cache:
            topology_cache[topology_id] = topology_resolver(topology_id)
        for system in systems:
            for seed in seeds:
                key = (item["request_id"], topology_id, system.system_name, system.model_name, seed)
                if key in completed:
                    skipped += 1
                    continue
                started = time.perf_counter()
                try:
                    output = system.run(item, topology_cache[topology_id], seed)
                except Exception as exc:
                    output = SystemRunOutput(
                        parsed_fields={}, action="REJECT", success=False,
                        failure_category=f"internal_exception:{type(exc).__name__}",
                        error_code="INTERNAL_EXPERIMENT_EXCEPTION",
                    )
                wall_time = time.perf_counter() - started
                record = ExperimentRecord(
                    schema_version=RAW_SCHEMA_VERSION,
                    request_id=item["request_id"],
                    paraphrase_group_id=item["paraphrase_group_id"],
                    topology_id=topology_id,
                    system=system.system_name,
                    model=system.model_name,
                    seed=seed,
                    parsed_fields=output.parsed_fields,
                    action=output.action,
                    gold_action=item["gold_action"],
                    tool_trace=output.tool_trace,
                    schedule_metrics=output.schedule_metrics,
                    validation=output.validation,
                    retries=output.retries,
                    wall_time_seconds=wall_time,
                    prompt_tokens=output.prompt_tokens,
                    completion_tokens=output.completion_tokens,
                    total_tokens=output.prompt_tokens + output.completion_tokens,
                    model_calls=output.model_calls,
                    success=output.success,
                    failure_category=output.failure_category,
                    category=item["category"],
                    complexity_level=item["complexity_level"],
                    clarification_fields=output.clarification_fields,
                    error_code=output.error_code,
                    decision_summary=output.decision_summary,
                    llm_logs=output.llm_logs,
                    scope_policy=output.scope_policy,
                )
                if _append_record(output_path, record):
                    written += 1; completed.add(key)
                else:
                    skipped += 1; completed.add(key)
    return {"expected": len(expected_keys), "completed": len(completed & expected_keys),
            "written": written, "skipped": skipped}


def _metric(record: ExperimentRecord, name: str) -> float | None:
    if name == "success": return float(record.success)
    if name == "action_accuracy": return float(record.action == record.gold_action)
    if name == "latency_slots":
        value = (record.schedule_metrics or {}).get("latency_slots")
        return float(value) if value is not None else None
    if name == "wall_time_seconds": return record.wall_time_seconds
    if name == "total_tokens": return float(record.total_tokens)
    if name == "retries": return float(record.retries)
    raise ValueError(f"unsupported paired metric: {name}")


def paired_comparison(records: Sequence[ExperimentRecord], *, baseline: tuple[str, str],
                      candidate: tuple[str, str], metric: str,
                      bootstrap_samples: int = 10_000, seed: int = 0) -> dict[str, Any]:
    if bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be positive")
    by_arm: dict[tuple[str, str], dict[tuple[str, str | None, int], ExperimentRecord]] = defaultdict(dict)
    for record in records:
        by_arm[(record.system, record.model)][(record.request_id, record.topology_id, record.seed)] = record
    left, right = by_arm[baseline], by_arm[candidate]
    if set(left) != set(right):
        missing_candidate = len(set(left) - set(right))
        missing_baseline = len(set(right) - set(left))
        raise ValueError(
            "paired arms do not contain identical request/topology/seed keys: "
            f"candidate missing {missing_candidate}, baseline missing {missing_baseline}"
        )
    paired_keys = sorted(set(left) & set(right))
    differences = []
    for key in paired_keys:
        left_value, right_value = _metric(left[key], metric), _metric(right[key], metric)
        if left_value is not None and right_value is not None:
            differences.append(right_value - left_value)
    if not differences:
        raise ValueError("no paired non-missing observations")
    rng = random.Random(seed)
    boot = sorted(mean(rng.choice(differences) for _ in differences)
                  for _ in range(bootstrap_samples))
    lower_index = max(0, math.floor(0.025 * (bootstrap_samples - 1)))
    upper_index = min(bootstrap_samples - 1, math.ceil(0.975 * (bootstrap_samples - 1)))
    return {
        "metric": metric,
        "baseline": {"system": baseline[0], "model": baseline[1]},
        "candidate": {"system": candidate[0], "model": candidate[1]},
        "paired_observations": len(differences),
        "mean_paired_difference_candidate_minus_baseline": mean(differences),
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_seed": seed,
        "confidence_level": 0.95,
        "confidence_interval": [boot[lower_index], boot[upper_index]],
    }


SUMMARY_COLUMNS = (
    "system", "model", "records", "action_accuracy", "task_success_rate",
    "schedule_validity", "false_acceptance_rate", "average_latency_slots",
    "average_retries", "average_wall_time_seconds", "total_tokens", "model_calls",
)


def generate_summary_csv(records: Sequence[ExperimentRecord], destination: str | Path,
                         *, overwrite: bool = False) -> None:
    path = Path(destination)
    if path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite summary CSV: {path}")
    grouped: dict[tuple[str, str], list[ExperimentRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.system, record.model)].append(record)
    rows = []
    for (system, model), group in sorted(grouped.items()):
        latencies = [(record.schedule_metrics or {}).get("latency_slots") for record in group]
        latencies = [float(value) for value in latencies if value is not None]
        execute = [record for record in group if record.gold_action == "EXECUTE"]
        false_accepts = sum(record.action == "EXECUTE" and (
            record.gold_action != "EXECUTE" or not record.success
        ) for record in group)
        rows.append({
            "system": system, "model": model, "records": len(group),
            "action_accuracy": sum(r.action == r.gold_action for r in group) / len(group),
            "task_success_rate": sum(r.success for r in group) / len(group),
            "schedule_validity": sum(bool((r.validation or {}).get("valid")) for r in execute) / len(execute)
            if execute else 0.0,
            "false_acceptance_rate": false_accepts / len(group),
            "average_latency_slots": mean(latencies) if latencies else "",
            "average_retries": mean(r.retries for r in group),
            "average_wall_time_seconds": mean(r.wall_time_seconds for r in group),
            "total_tokens": sum(r.total_tokens for r in group),
            "model_calls": sum(r.model_calls for r in group),
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with path.open(mode, newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader(); writer.writerows(rows)


__all__ = [
    "RAW_SCHEMA_VERSION", "SystemRunOutput", "ExperimentSystem", "ExperimentRecord",
    "RuleBasedBenchmarkSystem", "AgentBenchmarkSystem", "ProviderAgentBenchmarkSystem",
    "SCOPE_MODE_SYSTEM_NAMES",
    "load_jsonl", "load_experiment_records", "resolve_topology",
    "run_experiment_matrix", "paired_comparison", "generate_summary_csv",
]
