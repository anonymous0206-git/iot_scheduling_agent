"""Synthetic fixtures for the Frozen Test v2 pipeline tests.

Everything here is fabricated for testing. No real benchmark text, review, or
decision is used, so the tests run fully offline and never touch the sealed
benchmark inputs.
"""

from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path
from typing import Any

from frozen_test_v2.contract import ACTIONS, DEFAULT_FIELDS
from frozen_test_v2.documents import LoadedDocument, document_from_data

TOPOLOGY_ID = "legacy30_seed7"
_counter = itertools.count(1)


def execute_fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {"topology_id": TOPOLOGY_ID, **DEFAULT_FIELDS}
    fields.update(overrides)
    return fields


def synthetic_texts() -> tuple[str, str]:
    number = next(_counter)
    return (
        f"Synthetic operator request number {number} asks for a schedule.",
        f"A differently worded synthetic request, number {number}, for the same schedule.",
    )


def make_group(semantic_group_id: str, action: str, *, fields: Any = "auto",
               invalid_fields: dict[str, Any] | None = None,
               texts: tuple[str, str] | None = None, difficulty: str = "easy",
               category: str = "synthetic_case", ambiguity_risk: str = "none",
               annotation_reason: str = "Synthetic annotation.") -> dict[str, Any]:
    if fields == "auto":
        fields = execute_fields() if action == "EXECUTE" else None
    first, second = texts or synthetic_texts()
    group = {
        "semantic_group_id": semantic_group_id,
        "difficulty": difficulty,
        "capability_category": category,
        "proposed_gold_action": action,
        "proposed_gold_fields": copy.deepcopy(fields),
        "paraphrases": [
            {"request_id": f"{semantic_group_id}-p1", "request_text": first},
            {"request_id": f"{semantic_group_id}-p2", "request_text": second},
        ],
        "annotation_reason": annotation_reason,
        "ambiguity_risk": ambiguity_risk,
    }
    if invalid_fields is not None:
        group["invalid_fields"] = copy.deepcopy(invalid_fields)
    return group


def reject_group(semantic_group_id: str, **kwargs: Any) -> dict[str, Any]:
    return make_group(
        semantic_group_id, "REJECT",
        fields=execute_fields(channels=0),
        invalid_fields={"channels": {"observed": 0, "reason": "channels must be >= 1"}},
        **kwargs,
    )


def make_benchmark(batch_letter: str, groups: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {action: sum(1 for group in groups if group["proposed_gold_action"] == action)
              for action in ACTIONS}
    return {
        "benchmark_version": "frozen-test-v2-candidate",
        "batch_id": f"synthetic-model-{batch_letter}",
        "generator_role": "independent_generator",
        "groups": copy.deepcopy(groups),
        "self_check": {
            "group_count": len(groups),
            "item_count": sum(len(group["paraphrases"]) for group in groups),
            "execute_groups": counts["EXECUTE"],
            "clarify_groups": counts["CLARIFY"],
            "reject_groups": counts["REJECT"],
            "unsupported_groups": counts["UNSUPPORTED"],
        },
    }


def make_review_entry(group: dict[str, Any], *, action: str | None = None,
                      fields: Any = "mirror", paraphrase_equivalent: bool = True,
                      item_quality: str = "accept",
                      reason: str = "Synthetic reviewer agrees.") -> dict[str, Any]:
    if fields == "mirror":
        fields = copy.deepcopy(group.get("proposed_gold_fields"))
        if group.get("invalid_fields") and isinstance(fields, dict):
            fields["invalid_fields"] = copy.deepcopy(group["invalid_fields"])
    return {
        "semantic_group_id": group["semantic_group_id"],
        "adjudicated_action": action or group["proposed_gold_action"],
        "adjudicated_fields": fields,
        "paraphrase_equivalent": paraphrase_equivalent,
        "item_quality": item_quality,
        "reason": reason,
    }


def make_review(benchmark: dict[str, Any], overrides: dict[str, dict[str, Any]] | None = None,
                *, drop: tuple[str, ...] = ()) -> dict[str, Any]:
    overrides = overrides or {}
    entries = []
    for group in benchmark["groups"]:
        group_id = group["semantic_group_id"]
        if group_id in drop:
            continue
        entries.append(copy.deepcopy(overrides[group_id]) if group_id in overrides
                       else make_review_entry(group))
    return {"reviewed_batch": benchmark["batch_id"], "reviews": entries}


def standard_groups(batch_letter: str) -> list[dict[str, Any]]:
    prefix = f"syn-{batch_letter}"
    return [
        make_group(f"{prefix}-001", "EXECUTE", fields=execute_fields(channels=3, seed=5),
                   difficulty="easy", category="explicit_channels"),
        make_group(f"{prefix}-002", "CLARIFY", fields=None, difficulty="medium",
                   category="missing_topology"),
        reject_group(f"{prefix}-003", difficulty="easy", category="zero_channels"),
        make_group(f"{prefix}-004", "UNSUPPORTED", fields=None, difficulty="hard",
                   category="digital_twin"),
    ]


def standard_documents() -> dict[str, dict[str, Any]]:
    benchmark_a = make_benchmark("a", standard_groups("a"))
    benchmark_b = make_benchmark("b", standard_groups("b"))
    return {
        "benchmark_a": benchmark_a,
        "review_of_a": make_review(benchmark_a),
        "benchmark_b": benchmark_b,
        "review_of_b": make_review(benchmark_b),
    }


def loaded(documents: dict[str, dict[str, Any]]) -> dict[str, LoadedDocument]:
    return {key: document_from_data(value, path=f"<memory:{key}>")
            for key, value in documents.items()}


def make_decisions(decisions: list[dict[str, Any]], *, quotas: dict[str, int] | None = None,
                   quota_rationale: str | None = None,
                   decided_by: str = "synthetic adjudicator",
                   decided_at: str = "2026-09-08T00:00:00Z") -> dict[str, Any]:
    document: dict[str, Any] = {
        "decisions_version": "frozen-test-v2-decisions/1",
        "decided_by": decided_by,
        "decided_at": decided_at,
        "decisions": copy.deepcopy(decisions),
    }
    if quotas is not None:
        document["quotas"] = dict(quotas)
        document["quota_rationale"] = quota_rationale or "synthetic quota override"
    return document


def keep_decision(semantic_group_id: str, action: str, *, fields: Any = None,
                  invalid_fields: dict[str, Any] | None = None, resolution: str = "keep",
                  overrides: dict[str, str] | None = None, equivalent: bool = True,
                  rationale: str = "Synthetic human decision.") -> dict[str, Any]:
    decision = {
        "semantic_group_id": semantic_group_id,
        "resolution": resolution,
        "final_action": action,
        "final_fields": copy.deepcopy(fields),
        "final_invalid_fields": copy.deepcopy(invalid_fields),
        "paraphrase_equivalent": equivalent,
        "rationale": rationale,
    }
    if overrides:
        decision["paraphrase_overrides"] = dict(overrides)
    return decision


def exclude_decision(semantic_group_id: str,
                     rationale: str = "Synthetic exclusion.") -> dict[str, Any]:
    return {"semantic_group_id": semantic_group_id, "resolution": "exclude",
            "rationale": rationale}


def write_sealing_support_files(directory: Path) -> dict[str, Any]:
    """Create a prompt file, a topology file, and model metadata for sealing tests."""
    directory = Path(directory)
    prompt = directory / "generator_prompt.txt"
    prompt.write_text("Synthetic generator prompt.\n", encoding="utf-8")
    topology = directory / "topology.json"
    topology.write_text(json.dumps({
        "name": TOPOLOGY_ID,
        "working_period": 10,
        "communication_range": 18.0,
        "sink_id": 0,
        "nodes": [{"id": index} for index in range(3)],
    }), encoding="utf-8")
    metadata = {
        "model_a": {"model_id": "synthetic-model-a", "provider": "synthetic"},
        "model_b": {"model_id": "synthetic-model-b", "provider": "synthetic"},
    }
    return {
        "prompt_files": {"generator_prompt": prompt},
        "topology_file": topology,
        "topology_files": {TOPOLOGY_ID: topology},
        "model_metadata": document_from_data(metadata, path="<memory:model_metadata>"),
    }
