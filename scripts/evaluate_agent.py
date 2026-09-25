#!/usr/bin/env python3
"""Offline evaluator for the Paper 1 request benchmark.

The script consumes already-produced predictions. It contains no prompt search,
training, threshold fitting, or model calls. ``requests_test.jsonl`` is treated
as a frozen evaluation-only set; prompt iteration belongs on the dev split.

Prediction JSONL fields:
  request_id, action, structured_request, tool_calls, task_completed,
  schedule_valid, validation_certificate, clarification_fields, error_code,
  retry_count, prompt_tokens, completion_tokens, model_calls.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

ALLOWED_ACTIONS = {"EXECUTE", "CLARIFY", "REJECT", "UNSUPPORTED"}
ALLOWED_TOOLS = {
    "inspect_network", "run_anex", "validate_schedule",
    "measure_schedule", "explain_violations",
}
REQUIRED_FIELDS = {
    "request_id", "paraphrase_group_id", "template_id", "template_split",
    "user_text", "topology_id", "gold_action", "gold_structured_request",
    "expected_defaults", "expected_error", "clarification_fields",
    "expected_tool_calls", "complexity_level", "category",
}


class BenchmarkFormatError(ValueError):
    pass


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records = []
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BenchmarkFormatError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise BenchmarkFormatError(f"{path}:{line_number}: item must be an object")
        records.append(value)
    return records


def validate_benchmark_item(item: Mapping[str, Any], expected_split: str | None = None) -> None:
    missing = sorted(REQUIRED_FIELDS - set(item))
    if missing:
        raise BenchmarkFormatError(f"{item.get('request_id', '<unknown>')}: missing fields {missing}")
    if item["gold_action"] not in ALLOWED_ACTIONS:
        raise BenchmarkFormatError(f"{item['request_id']}: invalid gold_action")
    if expected_split is not None and item["template_split"] != expected_split:
        raise BenchmarkFormatError(f"{item['request_id']}: wrong template_split")
    if not isinstance(item["user_text"], str) or not item["user_text"].strip():
        raise BenchmarkFormatError(f"{item['request_id']}: empty user_text")
    if not set(item["expected_tool_calls"]).issubset(ALLOWED_TOOLS):
        raise BenchmarkFormatError(f"{item['request_id']}: unapproved expected tool")
    if item["gold_action"] == "EXECUTE" and not isinstance(item["gold_structured_request"], dict):
        raise BenchmarkFormatError(f"{item['request_id']}: EXECUTE requires structured request")
    if item["gold_action"] != "EXECUTE" and item["gold_structured_request"] is not None:
        raise BenchmarkFormatError(f"{item['request_id']}: non-EXECUTE must not carry request")


def validate_split(items: Iterable[Mapping[str, Any]], expected_split: str | None = None) -> None:
    ids, groups = set(), defaultdict(int)
    for item in items:
        validate_benchmark_item(item, expected_split)
        if item["request_id"] in ids:
            raise BenchmarkFormatError(f"duplicate request_id: {item['request_id']}")
        ids.add(item["request_id"])
        groups[item["paraphrase_group_id"]] += 1
    undersized = sorted(group for group, count in groups.items() if count < 2)
    if undersized:
        raise BenchmarkFormatError(f"paraphrase groups need at least two items: {undersized}")


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(value, dict):
        return {prefix or "$": value}
    flattened = {}
    for key in sorted(value):
        path = f"{prefix}.{key}" if prefix else key
        flattened.update(_flatten(value[key], path))
    return flattened


def _certificate_passes(prediction: Mapping[str, Any]) -> bool:
    certificate = prediction.get("validation_certificate")
    return (
        isinstance(certificate, Mapping)
        and certificate.get("certificate_format") == "agentic_anex.validation_certificate.v1"
        and certificate.get("valid") is True
        and not certificate.get("violations")
    )


def _task_completed(gold: Mapping[str, Any], prediction: Mapping[str, Any]) -> bool:
    if prediction.get("action") != gold["gold_action"]:
        return False
    action = gold["gold_action"]
    if action == "EXECUTE":
        return (prediction.get("task_completed") is True
                and prediction.get("schedule_valid") is True
                and _certificate_passes(prediction))
    if action == "CLARIFY":
        return set(prediction.get("clarification_fields", ())) == set(gold["clarification_fields"])
    return prediction.get("error_code") == gold["expected_error"]


def evaluate(benchmark: list[Mapping[str, Any]],
             predictions: list[Mapping[str, Any]]) -> dict[str, Any]:
    validate_split(benchmark)
    prediction_by_id = {}
    for prediction in predictions:
        request_id = prediction.get("request_id")
        if not request_id or request_id in prediction_by_id:
            raise BenchmarkFormatError(f"missing or duplicate prediction request_id: {request_id}")
        prediction_by_id[request_id] = prediction
    unknown = sorted(set(prediction_by_id) - {item["request_id"] for item in benchmark})
    if unknown:
        raise BenchmarkFormatError(f"predictions contain unknown request IDs: {unknown}")

    action_correct = tool_valid = completed = schedule_valid = false_acceptance = 0
    field_matches = field_total = 0
    retries = prompt_tokens = completion_tokens = model_calls = 0
    group_signatures: dict[str, list[str]] = defaultdict(list)
    category_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"items": 0, "action_correct": 0})

    for gold in benchmark:
        prediction = prediction_by_id.get(gold["request_id"], {})
        action_ok = prediction.get("action") == gold["gold_action"]
        action_correct += int(action_ok)
        category = category_counts[gold["category"]]
        category["items"] += 1; category["action_correct"] += int(action_ok)

        gold_fields = _flatten(gold["gold_structured_request"])
        predicted_fields = _flatten(prediction.get("structured_request"))
        paths = set(gold_fields) | set(predicted_fields)
        field_matches += sum(gold_fields.get(path, object()) == predicted_fields.get(path, object())
                             for path in paths)
        field_total += len(paths)

        predicted_tools = prediction.get("tool_calls", [])
        tools_ok = (
            isinstance(predicted_tools, list)
            and len(predicted_tools) == len(set(predicted_tools))
            and set(predicted_tools).issubset(ALLOWED_TOOLS)
            and set(predicted_tools) == set(gold["expected_tool_calls"])
        )
        tool_valid += int(tools_ok)
        completed += int(_task_completed(gold, prediction))

        if gold["gold_action"] == "EXECUTE":
            schedule_valid += int(
                prediction.get("schedule_valid") is True and _certificate_passes(prediction)
            )
        accepted = prediction.get("action") == "EXECUTE" or prediction.get("task_completed") is True
        invalid_acceptance = accepted and (
            gold["gold_action"] != "EXECUTE"
            or prediction.get("schedule_valid") is not True
            or not _certificate_passes(prediction)
        )
        false_acceptance += int(invalid_acceptance)

        retries += max(0, int(prediction.get("retry_count", 0) or 0))
        prompt_tokens += max(0, int(prediction.get("prompt_tokens", 0) or 0))
        completion_tokens += max(0, int(prediction.get("completion_tokens", 0) or 0))
        model_calls += max(0, int(prediction.get("model_calls", 0) or 0))
        signature = json.dumps({
            "action": prediction.get("action"),
            "structured_request": prediction.get("structured_request"),
            "clarification_fields": sorted(prediction.get("clarification_fields", ())),
            "error_code": prediction.get("error_code"),
        }, sort_keys=True, separators=(",", ":"))
        group_signatures[gold["paraphrase_group_id"]].append(signature)

    count = len(benchmark)
    execute_count = sum(item["gold_action"] == "EXECUTE" for item in benchmark)
    consistent_groups = sum(len(set(signatures)) == 1 for signatures in group_signatures.values())
    result = {
        "items": count,
        "coverage": len(prediction_by_id) / count if count else 0.0,
        "field_exact_match": field_matches / field_total if field_total else 0.0,
        "action_accuracy": action_correct / count if count else 0.0,
        "tool_call_validity": tool_valid / count if count else 0.0,
        "task_completion": completed / count if count else 0.0,
        "schedule_validity": schedule_valid / execute_count if execute_count else 0.0,
        "false_acceptance_count": false_acceptance,
        "false_acceptance_rate": false_acceptance / count if count else 0.0,
        "paraphrase_consistency": consistent_groups / len(group_signatures) if group_signatures else 0.0,
        "average_retry_count": retries / count if count else 0.0,
        "overhead": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "model_calls": model_calls,
            "average_tokens_per_item": (prompt_tokens + completion_tokens) / count if count else 0.0,
            "average_model_calls_per_item": model_calls / count if count else 0.0
        },
        "by_category": {
            category: {
                **values,
                "action_accuracy": values["action_correct"] / values["items"]
            }
            for category, values in sorted(category_counts.items())
        },
        "evaluation_policy": {
            "model_calls_performed_by_evaluator": 0,
            "prompt_tuning_supported": False,
            "frozen_test_set": any(item["template_split"] == "test" for item in benchmark)
        }
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate offline agent predictions")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    benchmark = load_jsonl(args.benchmark)
    predictions = load_jsonl(args.predictions)
    metrics = evaluate(benchmark, predictions)
    rendered = json.dumps(metrics, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
