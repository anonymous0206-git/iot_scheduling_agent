"""Evaluator-side export of the sealed Frozen Test v2 into the experiment-runner format.

The sealed requests file is target-facing and carries no labels. The
experiment runner (``scripts/run_experiments.py``), the summary and paired
comparison tools, and the policy replay all consume a benchmark file whose
items carry ``user_text``, the network to bind, the gold action, a category,
and a complexity level. This module builds that file on the evaluator side by
joining the sealed requests with the sealed gold records, after verifying the
text-hash binding between them. It never imports ``agentic_anex``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contract import ACTIONS, DEFAULT_TOPOLOGY_CATALOGUE
from .documents import sha256_text

HARNESS_FORMAT = "agentic_anex.frozen_test_v2_harness.v1"
TOPOLOGY_BINDING_RULE = (
    "A catalogue topology is bound to a request only when exactly one topology_id appears as a "
    "whole token in the request text; otherwise no network is supplied. A request that names a "
    "topology outside the catalogue receives no network because no such network exists, and a "
    "request that names two catalogue topologies receives none because the selection is ambiguous."
)
COMPLEXITY_BY_DIFFICULTY = {"easy": "basic", "medium": "intermediate", "hard": "advanced"}


class HarnessExportError(ValueError):
    """The sealed requests and gold records cannot be joined into a harness file."""


@dataclass
class HarnessExport:
    items: list[dict[str, Any]]
    summary: dict[str, Any]


def bind_topologies(text: str, catalogue: Mapping[str, Any] | None = None) -> list[str]:
    """Return every catalogue topology named as a whole token in ``text``."""
    catalogue = DEFAULT_TOPOLOGY_CATALOGUE if catalogue is None else catalogue
    return [
        topology_id for topology_id in sorted(catalogue)
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(topology_id)}(?![A-Za-z0-9_])", text)
    ]


def bind_topology(text: str, catalogue: Mapping[str, Any] | None = None) -> str | None:
    """Return the single catalogue topology named in ``text``, else ``None``.

    A request that names two catalogue topologies selects neither: it is an
    ambiguous selection, and the system under test receives no network.
    """
    matches = bind_topologies(text, catalogue)
    return matches[0] if len(matches) == 1 else None


def build_harness_items(requests: Sequence[Mapping[str, Any]],
                        gold: Sequence[Mapping[str, Any]], *,
                        catalogue: Mapping[str, Any] | None = None,
                        benchmark_version: str = "frozen-test-v2") -> HarnessExport:
    catalogue = DEFAULT_TOPOLOGY_CATALOGUE if catalogue is None else catalogue
    gold_by_id: dict[str, Mapping[str, Any]] = {}
    for record in gold:
        request_id = record.get("request_id")
        if not isinstance(request_id, str) or request_id in gold_by_id:
            raise HarnessExportError(f"duplicate or missing gold request_id {request_id!r}")
        gold_by_id[request_id] = record
    request_ids = [record.get("request_id") for record in requests]
    if len(set(request_ids)) != len(request_ids):
        raise HarnessExportError("duplicate request ids in the sealed requests file")
    if set(request_ids) != set(gold_by_id):
        raise HarnessExportError("sealed requests and gold records do not cover the same ids")
    items: list[dict[str, Any]] = []
    per_action = {action: 0 for action in ACTIONS}
    bound = 0
    uncatalogued: list[str] = []
    ambiguous: list[str] = []
    for record in requests:
        request_id = record["request_id"]
        text = record.get("request_text")
        if not isinstance(text, str) or not text.strip():
            raise HarnessExportError(f"{request_id}: empty request_text")
        label = gold_by_id[request_id]
        if label.get("request_text_sha256") != sha256_text(text):
            raise HarnessExportError(f"{request_id}: gold record is not bound to this request text")
        action = label.get("gold_action")
        if action not in ACTIONS:
            raise HarnessExportError(f"{request_id}: invalid gold_action {action!r}")
        matches = bind_topologies(text, catalogue)
        topology_id = matches[0] if len(matches) == 1 else None
        gold_topology = label.get("topology_id")
        note = None
        if len(matches) > 1:
            note = (f"request names {len(matches)} catalogue topologies "
                    f"({', '.join(matches)}); no network is supplied because the selection "
                    "is ambiguous")
            ambiguous.append(request_id)
        elif isinstance(gold_topology, str) and gold_topology not in catalogue:
            note = (f"request names topology {gold_topology!r}, which is not in the catalogue; "
                    "no network is supplied")
            uncatalogued.append(request_id)
        difficulty = label.get("difficulty")
        items.append({
            "request_id": request_id,
            "paraphrase_group_id": label.get("semantic_group_id"),
            "topology_id": topology_id,
            "user_text": text,
            "gold_action": action,
            "category": label.get("capability_category"),
            "complexity_level": COMPLEXITY_BY_DIFFICULTY.get(difficulty, str(difficulty)),
            "template_split": "test",
            "benchmark_version": benchmark_version,
            "batch_id": label.get("batch_id"),
            "difficulty": difficulty,
            "gold_topology_id": gold_topology,
            "gold_fields": label.get("gold_fields"),
            "invalid_fields": label.get("invalid_fields"),
            "topology_binding_note": note,
        })
        per_action[action] += 1
        bound += int(topology_id is not None)
    summary = {
        "harness_format": HARNESS_FORMAT,
        "items": len(items),
        "per_action": per_action,
        "topology_bound": bound,
        "topology_unbound": len(items) - bound,
        "requests_naming_uncatalogued_topology": uncatalogued,
        "requests_naming_multiple_topologies": ambiguous,
        "topology_binding_rule": TOPOLOGY_BINDING_RULE,
    }
    return HarnessExport(items=items, summary=summary)
