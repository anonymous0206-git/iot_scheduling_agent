"""Join generator batches with their blind reviews and classify every group.

The classification is descriptive only. Nothing here picks a winner between a
generator proposal and a reviewer adjudication: every group that is not in
FULL_AGREEMENT is exported to the human-adjudication worksheet and blocks
sealing until a recorded human decision covers it.

Classification precedence (first match wins):

1. DEFECTIVE_ITEM      structural defect in the generator item, missing or
                       malformed reviewer record, or reviewer item_quality
                       ``exclude``
2. ACTION_DISAGREEMENT proposed and adjudicated actions differ
3. PARAPHRASE_MISMATCH reviewer judged the paraphrases not equivalent
4. FIELD_DISAGREEMENT  gold fields differ for the agreed action
5. DEFECTIVE_ITEM      reviewer item_quality ``revise``
6. FULL_AGREEMENT
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from .contract import (
    ACTIONS,
    CONTRACT_FIELDS,
    DEFAULT_CONTRACT,
    DEFAULT_TOPOLOGY_CATALOGUE,
    contract_fields_only,
    get_profile,
    values_equal,
)
from .documents import LoadedDocument, utc_now_iso
from .schemas import DECISIONS_VERSION, normalized_text, validate_benchmark, validate_review

FULL_AGREEMENT = "FULL_AGREEMENT"
FIELD_DISAGREEMENT = "FIELD_DISAGREEMENT"
ACTION_DISAGREEMENT = "ACTION_DISAGREEMENT"
PARAPHRASE_MISMATCH = "PARAPHRASE_MISMATCH"
DEFECTIVE_ITEM = "DEFECTIVE_ITEM"
CLASSIFICATIONS: tuple[str, ...] = (
    FULL_AGREEMENT, FIELD_DISAGREEMENT, ACTION_DISAGREEMENT, PARAPHRASE_MISMATCH, DEFECTIVE_ITEM,
)
WORKSHEET_VERSION = "frozen-test-v2-worksheet/1"
ADJUDICATION_RULE = (
    "Every group whose classification is not FULL_AGREEMENT requires a recorded human "
    "decision before sealing; the pipeline never selects between generator and reviewer values."
)

_MISSING = object()


class ReconciliationError(ValueError):
    def __init__(self, message: str, problems: list[str]):
        super().__init__(message + ": " + "; ".join(problems))
        self.problems = list(problems)


@dataclass
class GroupReconciliation:
    batch_id: str
    semantic_group_id: str
    classification: str
    requires_human_decision: bool
    generator: dict[str, Any]
    reviewer: dict[str, Any] | None
    paraphrases: list[dict[str, Any]]
    signals: list[str] = field(default_factory=list)
    structural_defects: list[str] = field(default_factory=list)
    reviewer_defects: list[str] = field(default_factory=list)
    field_differences: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "semantic_group_id": self.semantic_group_id,
            "classification": self.classification,
            "requires_human_decision": self.requires_human_decision,
            "generator": self.generator,
            "reviewer": self.reviewer,
            "paraphrases": self.paraphrases,
            "signals": list(self.signals),
            "structural_defects": list(self.structural_defects),
            "reviewer_record_defects": list(self.reviewer_defects),
            "field_differences": list(self.field_differences),
        }


@dataclass
class BatchReconciliation:
    batch_id: str
    benchmark: LoadedDocument
    review: LoadedDocument
    groups: list[GroupReconciliation]
    warnings: list[str]
    declared_counts: dict[str, int | None]


@dataclass
class Reconciliation:
    batches: list[BatchReconciliation]
    generated_at_utc: str
    catalogue: dict[str, dict[str, Any]]
    contract_version: str = DEFAULT_CONTRACT.version

    def all_groups(self) -> list[GroupReconciliation]:
        return [group for batch in self.batches for group in batch.groups]

    def group(self, semantic_group_id: str) -> GroupReconciliation:
        for group in self.all_groups():
            if group.semantic_group_id == semantic_group_id:
                return group
        raise KeyError(semantic_group_id)

    def summary(self) -> dict[str, Any]:
        groups = self.all_groups()
        by_class = {name: 0 for name in CLASSIFICATIONS}
        for group in groups:
            by_class[group.classification] += 1
        per_batch: dict[str, Any] = {}
        for batch in self.batches:
            counts = {name: 0 for name in CLASSIFICATIONS}
            proposed = {action: 0 for action in ACTIONS}
            for group in batch.groups:
                counts[group.classification] += 1
                action = group.generator.get("proposed_gold_action")
                if action in proposed:
                    proposed[action] += 1
            per_batch[batch.batch_id] = {
                "groups": len(batch.groups),
                "by_classification": counts,
                "proposed_action_counts": proposed,
                "declared_counts": batch.declared_counts,
                "requires_human_decision": sum(
                    1 for group in batch.groups if group.requires_human_decision),
            }
        return {
            "groups": len(groups),
            "requests": sum(len(group.paraphrases) for group in groups),
            "by_classification": by_class,
            "requires_human_decision": sum(1 for group in groups if group.requires_human_decision),
            "per_batch": per_batch,
        }

    def worksheet(self) -> dict[str, Any]:
        return {
            "worksheet_version": WORKSHEET_VERSION,
            "generated_at_utc": self.generated_at_utc,
            "adjudication_policy": {"automatic_resolution": False, "rule": ADJUDICATION_RULE},
            "topology_catalogue": self.catalogue,
            "contract_version": self.contract_version,
            "inputs": {
                batch.batch_id: {
                    "benchmark": batch.benchmark.to_manifest_entry(),
                    "review": batch.review.to_manifest_entry(),
                }
                for batch in self.batches
            },
            "batch_warnings": {batch.batch_id: list(batch.warnings) for batch in self.batches},
            "summary": self.summary(),
            "groups": [group.to_dict() for group in self.all_groups()],
        }

    def decisions_template(self) -> dict[str, Any]:
        entries = []
        for group in self.all_groups():
            if not group.requires_human_decision:
                continue
            entries.append({
                "semantic_group_id": group.semantic_group_id,
                "context": {
                    "batch_id": group.batch_id,
                    "classification": group.classification,
                    "signals": list(group.signals),
                    "generator": group.generator,
                    "reviewer": group.reviewer,
                    "paraphrases": group.paraphrases,
                },
                "resolution": None,
                "final_action": None,
                "final_fields": None,
                "final_invalid_fields": None,
                "paraphrase_equivalent": None,
                "paraphrase_overrides": {},
                "rationale": "",
            })
        return {
            "decisions_version": DECISIONS_VERSION,
            "decided_by": "",
            "decided_at": "",
            "decisions": entries,
        }

    def markdown(self) -> str:
        return render_markdown(self.worksheet())


def _generator_view(group: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "proposed_gold_action": group.get("proposed_gold_action"),
        "proposed_gold_fields": group.get("proposed_gold_fields"),
        "invalid_fields": group.get("invalid_fields"),
        "difficulty": group.get("difficulty"),
        "capability_category": group.get("capability_category"),
        "ambiguity_risk": group.get("ambiguity_risk"),
        "annotation_reason": group.get("annotation_reason"),
    }


def _reviewer_view(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "adjudicated_action": entry.get("adjudicated_action"),
        "adjudicated_fields": entry.get("adjudicated_fields"),
        "paraphrase_equivalent": entry.get("paraphrase_equivalent"),
        "item_quality": entry.get("item_quality"),
        "reason": entry.get("reason"),
    }


def _paraphrase_view(group: Mapping[str, Any]) -> list[dict[str, Any]]:
    paraphrases = group.get("paraphrases")
    if not isinstance(paraphrases, list):
        return []
    return [
        {"request_id": item.get("request_id"), "request_text": item.get("request_text")}
        for item in paraphrases if isinstance(item, Mapping)
    ]


def compare_fields(action: str, group: Mapping[str, Any], entry: Mapping[str, Any]
                   ) -> tuple[list[dict[str, Any]], list[str]]:
    """Compare gold fields for an agreed action; return ``(differences, notes)``.

    EXECUTE compares the complete contract configuration. REJECT compares the
    explicit values both sides supplied plus the set of invalid field names
    when the reviewer enumerated them. CLARIFY and UNSUPPORTED carry no
    structured configuration to compare.
    """
    differences: list[dict[str, Any]] = []
    notes: list[str] = []
    generator_fields = contract_fields_only(group.get("proposed_gold_fields"))
    reviewer_raw = entry.get("adjudicated_fields")
    reviewer_fields = contract_fields_only(reviewer_raw)
    if action == "EXECUTE":
        for key in CONTRACT_FIELDS:
            left = generator_fields.get(key, _MISSING)
            right = reviewer_fields.get(key, _MISSING)
            if left is _MISSING or right is _MISSING or not values_equal(left, right):
                differences.append({
                    "field": key,
                    "generator": None if left is _MISSING else left,
                    "reviewer": None if right is _MISSING else right,
                })
    elif action == "REJECT":
        for key in CONTRACT_FIELDS:
            if key in generator_fields and key in reviewer_fields:
                if not values_equal(generator_fields[key], reviewer_fields[key]):
                    differences.append({
                        "field": key,
                        "generator": generator_fields[key],
                        "reviewer": reviewer_fields[key],
                    })
        generator_invalid = group.get("invalid_fields")
        reviewer_invalid = (reviewer_raw.get("invalid_fields")
                            if isinstance(reviewer_raw, Mapping) else None)
        if isinstance(reviewer_invalid, Mapping) and reviewer_invalid:
            left_names = sorted(generator_invalid) if isinstance(generator_invalid, Mapping) else []
            right_names = sorted(reviewer_invalid)
            if left_names != right_names:
                differences.append({
                    "field": "invalid_fields",
                    "generator": left_names,
                    "reviewer": right_names,
                })
        else:
            notes.append("reviewer did not enumerate invalid_fields; only overlapping explicit "
                         "values were compared")
    return differences, notes


def classify(*, structural_defects: list[str], reviewer: Mapping[str, Any] | None,
             reviewer_defects: list[str], action_match: bool,
             paraphrase_equivalent: Any, differences: list[dict[str, Any]],
             item_quality: Any) -> str:
    if structural_defects or reviewer is None or reviewer_defects or item_quality == "exclude":
        return DEFECTIVE_ITEM
    if not action_match:
        return ACTION_DISAGREEMENT
    if paraphrase_equivalent is False:
        return PARAPHRASE_MISMATCH
    if differences:
        return FIELD_DISAGREEMENT
    if item_quality == "revise":
        return DEFECTIVE_ITEM
    return FULL_AGREEMENT


def _declared_counts(doc: Mapping[str, Any]) -> dict[str, int | None]:
    declared = doc.get("self_check")
    keys = {
        "EXECUTE": "execute_groups",
        "CLARIFY": "clarify_groups",
        "REJECT": "reject_groups",
        "UNSUPPORTED": "unsupported_groups",
    }
    if not isinstance(declared, Mapping):
        return {action: None for action in keys}
    counts: dict[str, int | None] = {}
    for action, key in keys.items():
        value = declared.get(key)
        counts[action] = value if isinstance(value, int) and not isinstance(value, bool) else None
    return counts


def reconcile_batch(benchmark: LoadedDocument, review: LoadedDocument, *,
                    catalogue: Mapping[str, Mapping[str, Any]] | None = None,
                    profile: Any = None) -> BatchReconciliation:
    catalogue = DEFAULT_TOPOLOGY_CATALOGUE if catalogue is None else catalogue
    profile = get_profile(profile)
    benchmark_validation = validate_benchmark(benchmark.data, catalogue=catalogue,
                                              profile=profile)
    if benchmark_validation.errors:
        raise ReconciliationError(f"{benchmark.path}: benchmark schema errors",
                                  benchmark_validation.errors)
    review_validation = validate_review(review.data, benchmark.data, catalogue=catalogue,
                                        profile=profile)
    if review_validation.errors:
        raise ReconciliationError(f"{review.path}: review schema errors",
                                  review_validation.errors)
    reviews_by_id = {entry["semantic_group_id"]: entry for entry in review.data["reviews"]}
    batch_id = benchmark.data["batch_id"]
    groups: list[GroupReconciliation] = []
    for group in benchmark.data["groups"]:
        group_id = group["semantic_group_id"]
        entry = reviews_by_id.get(group_id)
        structural = list(benchmark_validation.group_defects.get(group_id, []))
        reviewer_defects = list(review_validation.entry_defects.get(group_id, []))
        action = group.get("proposed_gold_action")
        reviewer_action = entry.get("adjudicated_action") if entry is not None else None
        action_match = entry is not None and action in ACTIONS and reviewer_action == action
        differences: list[dict[str, Any]] = []
        notes: list[str] = []
        if action_match and not reviewer_defects and not structural:
            differences, notes = compare_fields(action, group, entry)
        paraphrase_equivalent = entry.get("paraphrase_equivalent") if entry is not None else None
        item_quality = entry.get("item_quality") if entry is not None else None
        classification = classify(
            structural_defects=structural,
            reviewer=entry,
            reviewer_defects=reviewer_defects,
            action_match=action_match,
            paraphrase_equivalent=paraphrase_equivalent,
            differences=differences,
            item_quality=item_quality,
        )
        signals = [f"structural defect: {defect}" for defect in structural]
        if entry is None:
            signals.append("no reviewer record for this group")
        signals.extend(f"reviewer record defect: {defect}" for defect in reviewer_defects)
        if entry is not None and not action_match:
            signals.append(f"action disagreement: generator {action} vs reviewer {reviewer_action}")
        if paraphrase_equivalent is False:
            signals.append("reviewer judged the paraphrases not equivalent")
        if item_quality in ("revise", "exclude"):
            signals.append(f"reviewer item_quality={item_quality}")
        signals.extend(
            f"field disagreement: {diff['field']} generator={diff['generator']!r} "
            f"reviewer={diff['reviewer']!r}" for diff in differences)
        signals.extend(notes)
        risk = group.get("ambiguity_risk")
        if risk in ("medium", "high"):
            signals.append(f"generator ambiguity_risk={risk}")
        groups.append(GroupReconciliation(
            batch_id=batch_id,
            semantic_group_id=group_id,
            classification=classification,
            requires_human_decision=classification != FULL_AGREEMENT,
            generator=_generator_view(group),
            reviewer=_reviewer_view(entry) if entry is not None else None,
            paraphrases=_paraphrase_view(group),
            signals=signals,
            structural_defects=structural,
            reviewer_defects=reviewer_defects,
            field_differences=differences,
        ))
    warnings = list(benchmark_validation.warnings) + list(review_validation.warnings)
    warnings.extend(f"unreviewed group {group_id}" for group_id in review_validation.missing_reviews)
    warnings.extend(f"benchmark document defect ({defect.kind}): {defect.detail}"
                    for defect in benchmark.defects)
    warnings.extend(f"review document defect ({defect.kind}): {defect.detail}"
                    for defect in review.defects)
    return BatchReconciliation(
        batch_id=batch_id,
        benchmark=benchmark,
        review=review,
        groups=groups,
        warnings=warnings,
        declared_counts=_declared_counts(benchmark.data),
    )


def _flag_cross_batch_duplicates(batches: list[BatchReconciliation]) -> None:
    owners: dict[str, tuple[str, GroupReconciliation]] = {}
    for batch in batches:
        for group in batch.groups:
            for paraphrase in group.paraphrases:
                text = paraphrase.get("request_text")
                if not isinstance(text, str) or not text.strip():
                    continue
                key = normalized_text(text)
                owner = owners.get(key)
                if owner is None:
                    owners[key] = (batch.batch_id, group)
                elif owner[1] is not group and owner[0] != batch.batch_id:
                    for victim, other in ((group, owner[1]), (owner[1], group)):
                        defect = (f"request_text duplicates {other.semantic_group_id} "
                                  f"in another batch")
                        if defect not in victim.structural_defects:
                            victim.structural_defects.append(defect)
                            victim.signals.append(f"structural defect: {defect}")
                            victim.classification = DEFECTIVE_ITEM
                            victim.requires_human_decision = True


def reconcile(batch_a: LoadedDocument, review_of_a: LoadedDocument,
              batch_b: LoadedDocument, review_of_b: LoadedDocument, *,
              catalogue: Mapping[str, Mapping[str, Any]] | None = None,
              profile: Any = None) -> Reconciliation:
    catalogue_dict = {key: dict(value) for key, value in
                      (DEFAULT_TOPOLOGY_CATALOGUE if catalogue is None else catalogue).items()}
    profile = get_profile(profile)
    batches = [
        reconcile_batch(batch_a, review_of_a, catalogue=catalogue_dict, profile=profile),
        reconcile_batch(batch_b, review_of_b, catalogue=catalogue_dict, profile=profile),
    ]
    if batches[0].batch_id == batches[1].batch_id:
        raise ReconciliationError("both benchmark documents carry the same batch_id",
                                  [batches[0].batch_id])
    ids = [group.semantic_group_id for batch in batches for group in batch.groups]
    collisions = sorted({group_id for group_id in ids if ids.count(group_id) > 1})
    if collisions:
        raise ReconciliationError("semantic_group_id collides across batches", collisions)
    _flag_cross_batch_duplicates(batches)
    return Reconciliation(batches=batches, generated_at_utc=utc_now_iso(),
                          catalogue=catalogue_dict, contract_version=profile.version)


def _cell(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(worksheet: Mapping[str, Any]) -> str:
    summary = worksheet["summary"]
    lines = [
        "# Frozen Test v2 human-adjudication worksheet",
        "",
        f"Generated: {worksheet['generated_at_utc']}",
        "",
        "No disagreement was resolved automatically. Record a decision for every group "
        "listed under \"Groups requiring a human decision\" in a decisions JSON file "
        "(start from human_decisions_template.json) before sealing.",
        "",
        "## Summary",
        "",
        "| Classification | Groups |",
        "|---|---:|",
    ]
    for name, count in summary["by_classification"].items():
        lines.append(f"| {name} | {count} |")
    lines.extend([
        "",
        f"Groups: {summary['groups']}; requests: {summary['requests']}; "
        f"groups requiring a human decision: {summary['requires_human_decision']}",
        "",
    ])
    warnings = {batch: items for batch, items in worksheet.get("batch_warnings", {}).items() if items}
    if warnings:
        lines.extend(["## Batch-level warnings", ""])
        for batch, items in warnings.items():
            for item in items:
                lines.append(f"- {_cell(batch)}: {_cell(item)}")
        lines.append("")
    pending = [group for group in worksheet["groups"] if group["requires_human_decision"]]
    lines.extend(["## Groups requiring a human decision", ""])
    if not pending:
        lines.extend(["None.", ""])
    for group in pending:
        generator = group["generator"]
        reviewer = group["reviewer"]
        lines.append(f"### {group['semantic_group_id']} ({group['batch_id']}) - "
                     f"{group['classification']}")
        lines.append("")
        lines.append(
            f"- Generator: action={generator.get('proposed_gold_action')}, "
            f"difficulty={generator.get('difficulty')}, "
            f"category={_cell(generator.get('capability_category'))}, "
            f"ambiguity_risk={generator.get('ambiguity_risk')}")
        lines.append(f"- Generator fields: `{_cell(generator.get('proposed_gold_fields'))}`")
        if generator.get("invalid_fields"):
            lines.append(f"- Generator invalid_fields: `{_cell(generator.get('invalid_fields'))}`")
        if reviewer is None:
            lines.append("- Reviewer: no record")
        else:
            lines.append(
                f"- Reviewer: action={reviewer.get('adjudicated_action')}, "
                f"paraphrase_equivalent={reviewer.get('paraphrase_equivalent')}, "
                f"item_quality={reviewer.get('item_quality')}")
            lines.append(f"- Reviewer fields: `{_cell(reviewer.get('adjudicated_fields'))}`")
            lines.append(f"- Reviewer reason: {_cell(reviewer.get('reason'))}")
        lines.append("- Signals:")
        for signal in group["signals"]:
            lines.append(f"  - {_cell(signal)}")
        lines.append("- Paraphrases:")
        for paraphrase in group["paraphrases"]:
            lines.append(f"  - `{_cell(paraphrase.get('request_id'))}`: "
                         f"{_cell(paraphrase.get('request_text'))}")
        lines.append("- Decision needed: resolution (keep, keep_with_edits, exclude), "
                     "final_action, final_fields, final_invalid_fields, "
                     "paraphrase_equivalent, rationale.")
        lines.append("")
    agreed = [group for group in worksheet["groups"] if not group["requires_human_decision"]]
    lines.extend([
        "## Groups in full agreement",
        "",
        "| Group | Batch | Action | Difficulty | Category |",
        "|---|---|---|---|---|",
    ])
    for group in agreed:
        generator = group["generator"]
        lines.append(
            f"| {_cell(group['semantic_group_id'])} | {_cell(group['batch_id'])} | "
            f"{generator.get('proposed_gold_action')} | {generator.get('difficulty')} | "
            f"{_cell(generator.get('capability_category'))} |")
    lines.append("")
    return "\n".join(lines)
