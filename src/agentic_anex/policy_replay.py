"""Retrospective, no-execution replay of locked scope-policy outcomes."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .scope_policy import evaluate_scope_policy, scope_error_code

REPLAY_FORMAT = "agentic_anex.retrospective_policy_ablation.v1"
V1_POLICY_VERSION = "paper1-flat-scope-policy.v1"

_V1_DIGITAL_TWIN_PHRASES = (
    "digital twin", "virtual replica", "virtual representation",
    "synchronize sensor state", "synchronize network state",
    "forecast future node states", "forecast network state",
)
_V1_ENERGY_PHRASES = (
    "minimize energy", "optimise energy", "optimize energy", "energy optimization",
    "energy consumption", "battery use", "battery consumption", "network lifetime",
    "residual energy", "energy efficiency",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate_v1_scope(text: str) -> dict[str, Any]:
    """Reproduce the exact flat phrase scope gate from frozen policy v1."""
    normalized = text.lower().replace("-", " ").replace("_", " ")
    matches = []
    for category, code, phrases in (
        ("digital_twin", "UNSUPPORTED_DIGITAL_TWIN", _V1_DIGITAL_TWIN_PHRASES),
        ("energy", "UNSUPPORTED_OBJECTIVE", _V1_ENERGY_PHRASES),
    ):
        for phrase in phrases:
            if phrase in normalized:
                matches.append({"category": category, "phrase": phrase, "code": code})
    return {
        "policy_version": V1_POLICY_VERSION,
        "supported": not matches,
        "matches": matches,
        "error_code": matches[0]["code"] if matches else None,
    }


def _replayed(record: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    blocked = not policy["supported"]
    return {
        "action": "UNSUPPORTED" if blocked else record["action"],
        "blocked_before_model": blocked,
        "model_calls": 0 if blocked else record["model_calls"],
        "blocked_before_tools": blocked,
        "tool_calls": 0 if blocked else len(record.get("tool_trace", ())),
        "error_code": policy.get("error_code") if blocked else record.get("error_code"),
    }


def replay_locked_outputs(
    benchmark_items: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    *,
    benchmark_path: str,
    raw_path: str,
    benchmark_sha256: str,
    raw_sha256: str,
) -> dict[str, Any]:
    items = {item["request_id"]: item for item in benchmark_items}
    if len(items) != len(benchmark_items):
        raise ValueError("benchmark request IDs must be unique")
    rows = []
    for record in records:
        request_id = record["request_id"]
        if request_id not in items:
            raise ValueError(f"record has no benchmark item: {request_id}")
        item = items[request_id]
        text = item["user_text"]
        v1_policy = evaluate_v1_scope(text)
        v2_report = evaluate_scope_policy(text)
        v2_policy = {
            "policy_version": v2_report.policy_version,
            "supported": v2_report.supported,
            "matches": [violation.to_dict() for violation in v2_report.violations],
            "error_code": None if v2_report.supported else scope_error_code(v2_report),
        }
        rows.append({
            "request_id": request_id,
            "model": record["model"],
            "seed": record["seed"],
            "category": item["category"],
            "gold_action": item["gold_action"],
            "locked_action": record["action"],
            "locked_model_calls": record["model_calls"],
            "locked_tool_calls": len(record.get("tool_trace", ())),
            "policy_v1": {"scope": v1_policy, "outcome": _replayed(record, v1_policy)},
            "policy_v2": {"scope": v2_policy, "outcome": _replayed(record, v2_policy)},
        })
    summaries = {}
    for policy_name in ("policy_v1", "policy_v2"):
        outcomes = [row[policy_name]["outcome"] for row in rows]
        summaries[policy_name] = {
            "records": len(rows),
            "action_accuracy": sum(outcome["action"] == row["gold_action"]
                                   for row, outcome in zip(rows, outcomes)) / len(rows),
            "false_acceptance_count": sum(row["gold_action"] == "UNSUPPORTED"
                                          and outcome["action"] == "EXECUTE"
                                          for row, outcome in zip(rows, outcomes)),
            "supported_overblock_count": sum(row["gold_action"] == "EXECUTE"
                                             and outcome["action"] == "UNSUPPORTED"
                                             for row, outcome in zip(rows, outcomes)),
            "blocked_before_model_count": sum(outcome["blocked_before_model"]
                                              for outcome in outcomes),
            "counterfactual_model_calls": sum(outcome["model_calls"] for outcome in outcomes),
            "counterfactual_tool_calls": sum(outcome["tool_calls"] for outcome in outcomes),
        }
    changed = sum(row["policy_v1"]["outcome"]["action"] !=
                  row["policy_v2"]["outcome"]["action"] for row in rows)
    return {
        "artifact_format": REPLAY_FORMAT,
        "classification": "retrospective/regression; not unbiased generalization performance",
        "execution": {"llm_called": False, "scientific_tools_called": False,
                      "schedule_recomputed": False},
        "sources": {
            "benchmark": {"path": benchmark_path, "sha256": benchmark_sha256},
            "raw_ledger": {"path": raw_path, "sha256": raw_sha256},
        },
        "summary": {**summaries, "changed_actions_v1_to_v2": changed},
        "records": rows,
    }


def replay_files(benchmark: Path, raw: Path) -> dict[str, Any]:
    benchmark_items = [json.loads(line) for line in benchmark.read_text(encoding="utf-8").splitlines()
                       if line.strip()]
    records = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    return replay_locked_outputs(
        benchmark_items, records, benchmark_path=str(benchmark), raw_path=str(raw),
        benchmark_sha256=_sha256(benchmark), raw_sha256=_sha256(raw),
    )


__all__ = ["REPLAY_FORMAT", "V1_POLICY_VERSION", "evaluate_v1_scope",
           "replay_locked_outputs", "replay_files"]
