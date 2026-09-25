"""Hand-rolled validators for the Frozen Test v2 input documents.

Four document kinds are validated: generator benchmarks, blind reviews, human
decisions, and model metadata. Validation separates fatal schema errors (the
document cannot be processed) from per-group defects (the group is processed
but classified as DEFECTIVE_ITEM).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .contract import (
    ACTIONS,
    AMBIGUITY_RISKS,
    DIFFICULTIES,
    ITEM_QUALITIES,
    PARAPHRASES_PER_GROUP,
    PROTOCOL_CATEGORY_ACTIONS,
    execute_configuration_problems,
    get_profile,
    is_integer,
    unconfirmed_invalid_fields,
)

RESOLUTIONS: tuple[str, ...] = ("keep", "keep_with_edits", "exclude")
DECISIONS_VERSION = "frozen-test-v2-decisions/1"
GROUP_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def normalized_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def _is_string(value: Any) -> bool:
    return isinstance(value, str)


def _is_nonempty(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


@dataclass
class BenchmarkValidation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    group_defects: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add_defect(self, group_id: str, defect: str) -> None:
        self.group_defects.setdefault(group_id, []).append(defect)


@dataclass
class ReviewValidation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    entry_defects: dict[str, list[str]] = field(default_factory=dict)
    missing_reviews: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _gold_defects(group: Mapping[str, Any], action: str,
                  catalogue: Mapping[str, Mapping[str, Any]] | None,
                  profile: Any = None) -> list[str]:
    fields = group.get("proposed_gold_fields")
    invalid = group.get("invalid_fields")
    defects: list[str] = []
    if action == "EXECUTE":
        defects.extend(f"EXECUTE gold: {problem}"
                       for problem in execute_configuration_problems(fields, catalogue, profile))
        if invalid:
            defects.append("EXECUTE gold must not carry invalid_fields")
    elif action == "REJECT":
        if fields is not None and not isinstance(fields, Mapping):
            defects.append("REJECT proposed_gold_fields must be an object or null")
        if not isinstance(invalid, Mapping) or not invalid:
            defects.append("REJECT gold must enumerate invalid_fields")
        else:
            malformed = [
                name for name, entry in invalid.items()
                if not isinstance(entry, Mapping) or "observed" not in entry
                or not _is_nonempty(entry.get("reason"))
            ]
            if malformed:
                defects.append(f"invalid_fields entries need observed and reason: {malformed}")
            else:
                unconfirmed = unconfirmed_invalid_fields(fields, invalid, catalogue, profile)
                if unconfirmed and len(unconfirmed) == len(invalid):
                    defects.append(
                        "no invalid field is confirmed by the configuration contract: "
                        f"{unconfirmed}")
    else:
        if fields is not None and not isinstance(fields, Mapping):
            defects.append(f"{action} proposed_gold_fields must be an object or null")
        if invalid:
            defects.append(f"{action} gold must not carry invalid_fields")
    return defects


def _self_check_warnings(doc: Mapping[str, Any], groups: list[Any]) -> list[str]:
    declared = doc.get("self_check")
    if not isinstance(declared, Mapping):
        return ["self_check block is missing; counts were recomputed"]
    counts = {action: 0 for action in ACTIONS}
    items = 0
    for group in groups:
        if isinstance(group, Mapping):
            action = group.get("proposed_gold_action")
            if action in counts:
                counts[action] += 1
            paraphrases = group.get("paraphrases")
            items += len(paraphrases) if isinstance(paraphrases, list) else 0
    expected = {
        "group_count": len(groups),
        "item_count": items,
        "execute_groups": counts["EXECUTE"],
        "clarify_groups": counts["CLARIFY"],
        "reject_groups": counts["REJECT"],
        "unsupported_groups": counts["UNSUPPORTED"],
    }
    warnings = [
        f"self_check.{key} declares {declared.get(key)!r} but the document contains {value}"
        for key, value in expected.items() if declared.get(key) != value
    ]
    declared_categories = declared.get("protocol_category_counts")
    if isinstance(declared_categories, Mapping):
        observed: dict[str, int] = {}
        for group in groups:
            if isinstance(group, Mapping) and group.get("protocol_category") is not None:
                category = str(group["protocol_category"])
                observed[category] = observed.get(category, 0) + 1
        for category in sorted(set(declared_categories) | set(observed)):
            if declared_categories.get(category) != observed.get(category, 0):
                warnings.append(
                    f"self_check.protocol_category_counts.{category} declares "
                    f"{declared_categories.get(category)!r} but the document contains "
                    f"{observed.get(category, 0)}")
    return warnings


def validate_benchmark(doc: Any, *, catalogue: Mapping[str, Mapping[str, Any]] | None = None,
                       profile: Any = None) -> BenchmarkValidation:
    profile = get_profile(profile)
    result = BenchmarkValidation()
    if not isinstance(doc, Mapping):
        result.errors.append("benchmark document must be a JSON object")
        return result
    for key in ("benchmark_version", "batch_id", "generator_role"):
        if not _is_nonempty(doc.get(key)):
            result.errors.append(f"{key} must be a non-empty string")
    groups = doc.get("groups")
    if not isinstance(groups, list) or not groups:
        result.errors.append("groups must be a non-empty list")
        return result
    seen_groups: set[str] = set()
    seen_requests: dict[str, str] = {}
    seen_texts: dict[str, str] = {}
    for index, group in enumerate(groups):
        if not isinstance(group, Mapping) or not _is_nonempty(group.get("semantic_group_id")):
            result.errors.append(f"groups[{index}] must be an object with a semantic_group_id")
            continue
        group_id = group["semantic_group_id"]
        if group_id in seen_groups:
            result.errors.append(f"duplicate semantic_group_id {group_id}")
            continue
        seen_groups.add(group_id)
        defects: list[str] = []
        if not GROUP_ID_PATTERN.match(group_id):
            defects.append(f"semantic_group_id {group_id!r} contains unsupported characters")
        if group.get("difficulty") not in DIFFICULTIES:
            defects.append(f"difficulty {group.get('difficulty')!r} not in {list(DIFFICULTIES)}")
        if not _is_nonempty(group.get("capability_category")):
            defects.append("capability_category must be a non-empty string")
        if group.get("ambiguity_risk") not in AMBIGUITY_RISKS:
            defects.append(
                f"ambiguity_risk {group.get('ambiguity_risk')!r} not in {list(AMBIGUITY_RISKS)}")
        if not _is_string(group.get("annotation_reason")):
            defects.append("annotation_reason must be a string")
        action = group.get("proposed_gold_action")
        if action not in ACTIONS:
            defects.append(f"proposed_gold_action {action!r} not in {list(ACTIONS)}")
        else:
            defects.extend(_gold_defects(group, action, catalogue, profile))
        protocol_category = group.get("protocol_category")
        if protocol_category is not None:
            implied = PROTOCOL_CATEGORY_ACTIONS.get(protocol_category)
            if implied is None:
                defects.append(f"protocol_category {protocol_category!r} is not one of "
                               f"{sorted(PROTOCOL_CATEGORY_ACTIONS)}")
            elif action in ACTIONS and implied != action:
                defects.append(f"protocol_category {protocol_category!r} implies {implied} "
                               f"but proposed_gold_action is {action}")
        paraphrases = group.get("paraphrases")
        if not isinstance(paraphrases, list):
            defects.append("paraphrases must be a list")
            paraphrases = []
        elif len(paraphrases) != PARAPHRASES_PER_GROUP:
            defects.append(
                f"expected exactly {PARAPHRASES_PER_GROUP} paraphrases, found {len(paraphrases)}")
        local_texts: set[str] = set()
        for p_index, paraphrase in enumerate(paraphrases):
            if not isinstance(paraphrase, Mapping):
                defects.append(f"paraphrases[{p_index}] must be an object")
                continue
            request_id = paraphrase.get("request_id")
            text = paraphrase.get("request_text")
            if not _is_nonempty(request_id):
                defects.append(f"paraphrases[{p_index}].request_id missing")
            else:
                if request_id in seen_requests:
                    result.errors.append(
                        f"duplicate request_id {request_id} (groups "
                        f"{seen_requests[request_id]} and {group_id})")
                seen_requests[request_id] = group_id
                if not request_id.startswith(group_id):
                    defects.append(f"request_id {request_id} does not belong to group {group_id}")
            if not _is_nonempty(text):
                defects.append(f"paraphrases[{p_index}].request_text missing or empty")
                continue
            key = normalized_text(text)
            if key in local_texts:
                defects.append("paraphrases are identical after whitespace and case normalization")
            local_texts.add(key)
            owner = seen_texts.setdefault(key, group_id)
            if owner != group_id:
                defects.append(f"request_text duplicates group {owner}")
                result.add_defect(owner, f"request_text duplicated by group {group_id}")
        for defect in defects:
            result.add_defect(group_id, defect)
    result.warnings.extend(_self_check_warnings(doc, groups))
    return result


def validate_review(doc: Any, benchmark_doc: Mapping[str, Any], *,
                    catalogue: Mapping[str, Mapping[str, Any]] | None = None,
                    profile: Any = None) -> ReviewValidation:
    profile = get_profile(profile)
    result = ReviewValidation()
    if not isinstance(doc, Mapping):
        result.errors.append("review document must be a JSON object")
        return result
    expected_batch = benchmark_doc.get("batch_id") if isinstance(benchmark_doc, Mapping) else None
    if doc.get("reviewed_batch") != expected_batch:
        result.errors.append(
            f"reviewed_batch {doc.get('reviewed_batch')!r} does not match batch_id "
            f"{expected_batch!r}")
    reviews = doc.get("reviews")
    if not isinstance(reviews, list):
        result.errors.append("reviews must be a list")
        return result
    known: set[str] = set()
    if isinstance(benchmark_doc, Mapping) and isinstance(benchmark_doc.get("groups"), list):
        for group in benchmark_doc["groups"]:
            if isinstance(group, Mapping) and _is_nonempty(group.get("semantic_group_id")):
                known.add(group["semantic_group_id"])
    seen: set[str] = set()
    for index, entry in enumerate(reviews):
        if not isinstance(entry, Mapping) or not _is_nonempty(entry.get("semantic_group_id")):
            result.errors.append(f"reviews[{index}] must be an object with a semantic_group_id")
            continue
        group_id = entry["semantic_group_id"]
        if group_id in seen:
            result.errors.append(f"duplicate review for {group_id}")
            continue
        seen.add(group_id)
        if group_id not in known:
            result.errors.append(f"review for unknown group {group_id}")
            continue
        defects: list[str] = []
        action = entry.get("adjudicated_action")
        if action not in ACTIONS:
            defects.append(f"adjudicated_action {action!r} not in {list(ACTIONS)}")
        if not isinstance(entry.get("paraphrase_equivalent"), bool):
            defects.append("paraphrase_equivalent must be true or false")
        if entry.get("item_quality") not in ITEM_QUALITIES:
            defects.append(f"item_quality {entry.get('item_quality')!r} not in {list(ITEM_QUALITIES)}")
        if not _is_nonempty(entry.get("reason")):
            defects.append("reason must be a non-empty string")
        fields = entry.get("adjudicated_fields")
        if fields is not None and not isinstance(fields, Mapping):
            defects.append("adjudicated_fields must be an object or null")
        elif action == "EXECUTE":
            defects.extend(f"reviewer EXECUTE fields: {problem}"
                           for problem in execute_configuration_problems(fields, catalogue,
                                                                         profile))
        if defects:
            result.entry_defects[group_id] = defects
    result.missing_reviews = sorted(known - seen)
    return result


def validate_decisions(doc: Any) -> list[str]:
    """Structural validation of a human-decisions document."""
    errors: list[str] = []
    if not isinstance(doc, Mapping):
        return ["decisions document must be a JSON object"]
    for key in ("decisions_version", "decided_by", "decided_at"):
        if not _is_nonempty(doc.get(key)):
            errors.append(f"{key} must be a non-empty string")
    quotas = doc.get("quotas")
    if quotas is not None:
        if (not isinstance(quotas, Mapping) or set(quotas) != set(ACTIONS)
                or any(not is_integer(value) or value < 0 for value in quotas.values())):
            errors.append("quotas must map every action to a non-negative integer")
        if not _is_nonempty(doc.get("quota_rationale")):
            errors.append("quota_rationale is required when quotas are declared")
    decisions = doc.get("decisions")
    if not isinstance(decisions, list):
        errors.append("decisions must be a list")
        return errors
    seen: set[str] = set()
    for index, decision in enumerate(decisions):
        if not isinstance(decision, Mapping):
            errors.append(f"decisions[{index}] must be an object")
            continue
        group_id = decision.get("semantic_group_id")
        if not _is_nonempty(group_id):
            errors.append(f"decisions[{index}]: semantic_group_id missing")
            continue
        prefix = f"decision {group_id}"
        if group_id in seen:
            errors.append(f"duplicate decision for {group_id}")
        seen.add(group_id)
        resolution = decision.get("resolution")
        if resolution not in RESOLUTIONS:
            errors.append(f"{prefix}: resolution {resolution!r} not in {list(RESOLUTIONS)}")
            continue
        if not _is_nonempty(decision.get("rationale")):
            errors.append(f"{prefix}: rationale is required")
        if resolution == "exclude":
            continue
        if decision.get("final_action") not in ACTIONS:
            errors.append(
                f"{prefix}: final_action {decision.get('final_action')!r} not in {list(ACTIONS)}")
        for key in ("final_fields", "final_invalid_fields"):
            value = decision.get(key)
            if value is not None and not isinstance(value, Mapping):
                errors.append(f"{prefix}: {key} must be an object or null")
        if not isinstance(decision.get("paraphrase_equivalent"), bool):
            errors.append(f"{prefix}: paraphrase_equivalent must be true or false")
        overrides = decision.get("paraphrase_overrides")
        if overrides is not None:
            if (not isinstance(overrides, Mapping)
                    or any(not _is_nonempty(key) or not _is_nonempty(value)
                           for key, value in overrides.items())):
                errors.append(f"{prefix}: paraphrase_overrides must map request_id to non-empty text")
            elif overrides and resolution != "keep_with_edits":
                errors.append(f"{prefix}: paraphrase_overrides require resolution keep_with_edits")
    return errors


def validate_model_metadata(doc: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(doc, Mapping):
        return ["model metadata document must be a JSON object"]
    for key in ("model_a", "model_b"):
        entry = doc.get(key)
        if not isinstance(entry, Mapping) or not _is_nonempty(entry.get("model_id")):
            errors.append(f"{key}.model_id must be a non-empty string")
    return errors
