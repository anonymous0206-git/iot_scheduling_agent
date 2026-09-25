"""Produce a blind copy of a generator batch for independent adjudication.

The blind copy keeps only what a reviewer needs: batch identity, group ids,
and the two request texts per group. Every generator annotation is removed,
including the ones the Frozen Test v2 blind files still carried
(``difficulty``, ``capability_category``, ``ambiguity_risk`` and, for REJECT
groups, ``invalid_fields``), because category names and invalid-field lists
hint at the gold action.
"""

from __future__ import annotations

from typing import Any, Mapping

REMOVED_GROUP_KEYS: tuple[str, ...] = (
    "proposed_gold_action",
    "proposed_gold_fields",
    "invalid_fields",
    "annotation_reason",
    "ambiguity_risk",
    "capability_category",
    "difficulty",
    "protocol_category",
)


def blind_benchmark(doc: Any) -> dict[str, Any]:
    """Return the reviewer-facing copy of a generator batch."""
    if not isinstance(doc, Mapping) or not isinstance(doc.get("groups"), list):
        raise ValueError("benchmark document must be an object with a groups list")
    groups: list[dict[str, Any]] = []
    for index, group in enumerate(doc["groups"]):
        if not isinstance(group, Mapping) or not isinstance(group.get("semantic_group_id"), str):
            raise ValueError(f"groups[{index}] lacks a semantic_group_id")
        group_id = group["semantic_group_id"]
        paraphrases = group.get("paraphrases")
        if not isinstance(paraphrases, list) or not paraphrases:
            raise ValueError(f"{group_id}: paraphrases must be a non-empty list")
        items: list[dict[str, str]] = []
        for paraphrase in paraphrases:
            if (not isinstance(paraphrase, Mapping)
                    or not isinstance(paraphrase.get("request_id"), str)
                    or not isinstance(paraphrase.get("request_text"), str)):
                raise ValueError(f"{group_id}: paraphrases must carry request_id and request_text")
            items.append({"request_id": paraphrase["request_id"],
                          "request_text": paraphrase["request_text"]})
        groups.append({"semantic_group_id": group_id, "paraphrases": items})
    return {
        "benchmark_version": doc.get("benchmark_version"),
        "batch_id": doc.get("batch_id"),
        "generator_role": doc.get("generator_role"),
        "blinded": True,
        "groups": groups,
        "self_check": {
            "group_count": len(groups),
            "item_count": sum(len(group["paraphrases"]) for group in groups),
        },
    }


def leaked_keys(value: Any) -> list[str]:
    """Return every removed annotation key that still occurs anywhere in ``value``."""
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in REMOVED_GROUP_KEYS:
                found.append(key)
            found.extend(leaked_keys(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.extend(leaked_keys(child))
    return found
