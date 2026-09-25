"""Apply recorded human decisions to a reconciliation and derive the final gold set.

The pipeline never resolves a disagreement on its own. A group in
FULL_AGREEMENT is sealed with the values both parties agreed on; every other
group must be covered by an explicit decision, and every kept group must
carry an asserted paraphrase equivalence and contract-consistent gold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .contract import (
    ACTIONS,
    PARAPHRASES_PER_GROUP,
    execute_configuration_problems,
    get_profile,
    unconfirmed_invalid_fields,
)
from .reconcile import GroupReconciliation, Reconciliation
from .schemas import normalized_text, validate_decisions


class SealRefusal(RuntimeError):
    """Raised whenever the pipeline refuses to seal; carries every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("refusing to seal: " + "; ".join(self.problems))


@dataclass
class FinalGroup:
    batch_id: str
    semantic_group_id: str
    gold_action: str
    gold_fields: dict[str, Any] | None
    invalid_fields: dict[str, Any] | None
    paraphrases: list[dict[str, str]]
    difficulty: Any
    capability_category: Any
    reconciliation_class: str
    decision_source: str
    paraphrase_equivalence_source: str
    rationale: str | None

    @property
    def topology_id(self) -> str | None:
        if isinstance(self.gold_fields, Mapping):
            value = self.gold_fields.get("topology_id")
            return value if isinstance(value, str) else None
        return None


@dataclass
class FinalSet:
    groups: list[FinalGroup]
    quotas_expected: dict[str, int]
    quotas_observed: dict[str, int]
    quota_source: str
    excluded: list[dict[str, str]]
    decisions_applied: int
    decided_by: str
    decided_at: str


def default_quotas(reconciliation: Reconciliation) -> dict[str, int]:
    """Per-action quotas implied by the generators' declared self-checks.

    When a batch declares no count for an action, the count of proposed
    actions in that batch is used instead.
    """
    totals = {action: 0 for action in ACTIONS}
    for batch in reconciliation.batches:
        for action in ACTIONS:
            declared = batch.declared_counts.get(action)
            if declared is None:
                declared = sum(1 for group in batch.groups
                               if group.generator.get("proposed_gold_action") == action)
            totals[action] += declared
    return totals


def _paraphrases_of(group: GroupReconciliation) -> list[dict[str, str]]:
    return [
        {"request_id": str(item.get("request_id")), "request_text": str(item.get("request_text"))}
        for item in group.paraphrases
    ]


def _from_agreement(group: GroupReconciliation, problems: list[str]) -> FinalGroup:
    reviewer = group.reviewer or {}
    if reviewer.get("paraphrase_equivalent") is not True:
        problems.append(f"{group.semantic_group_id}: paraphrase equivalence was never confirmed")
    generator = group.generator
    action = generator.get("proposed_gold_action")
    return FinalGroup(
        batch_id=group.batch_id,
        semantic_group_id=group.semantic_group_id,
        gold_action=str(action),
        gold_fields=generator.get("proposed_gold_fields"),
        invalid_fields=generator.get("invalid_fields") if action == "REJECT" else None,
        paraphrases=_paraphrases_of(group),
        difficulty=generator.get("difficulty"),
        capability_category=generator.get("capability_category"),
        reconciliation_class=group.classification,
        decision_source="dual_agreement",
        paraphrase_equivalence_source="reviewer",
        rationale=None,
    )


def _from_decision(group: GroupReconciliation, decision: Mapping[str, Any],
                   catalogue: Mapping[str, Mapping[str, Any]], profile: Any,
                   problems: list[str]) -> FinalGroup:
    group_id = group.semantic_group_id
    action = decision["final_action"]
    fields = decision.get("final_fields")
    invalid = decision.get("final_invalid_fields")
    if decision.get("paraphrase_equivalent") is not True:
        problems.append(f"{group_id}: the decision keeps the group but does not assert "
                        "paraphrase equivalence")
    if action == "EXECUTE":
        problems.extend(f"{group_id}: EXECUTE gold {problem}"
                        for problem in execute_configuration_problems(fields, catalogue,
                                                                      profile))
        if invalid:
            problems.append(f"{group_id}: EXECUTE gold must not carry final_invalid_fields")
    elif action == "REJECT":
        if not isinstance(invalid, Mapping) or not invalid:
            problems.append(f"{group_id}: REJECT gold must enumerate final_invalid_fields")
        else:
            malformed = [
                name for name, entry in invalid.items()
                if not isinstance(entry, Mapping) or "observed" not in entry
                or not str(entry.get("reason", "")).strip()
            ]
            if malformed:
                problems.append(f"{group_id}: final_invalid_fields entries need observed and "
                                f"reason: {malformed}")
            else:
                unconfirmed = unconfirmed_invalid_fields(fields, invalid, catalogue, profile)
                if unconfirmed and len(unconfirmed) == len(invalid):
                    problems.append(f"{group_id}: no final invalid field is confirmed by the "
                                    f"configuration contract: {unconfirmed}")
    elif invalid:
        problems.append(f"{group_id}: {action} gold must not carry final_invalid_fields")
    overrides = decision.get("paraphrase_overrides") or {}
    paraphrases = _paraphrases_of(group)
    known_ids = {item["request_id"] for item in paraphrases}
    unknown = sorted(set(overrides) - known_ids)
    if unknown:
        problems.append(f"{group_id}: paraphrase_overrides reference unknown request ids {unknown}")
    for item in paraphrases:
        if item["request_id"] in overrides:
            item["request_text"] = overrides[item["request_id"]]
    if len(paraphrases) != PARAPHRASES_PER_GROUP:
        problems.append(f"{group_id}: a kept group must have exactly {PARAPHRASES_PER_GROUP} "
                        f"paraphrases, found {len(paraphrases)}")
    if any(not item["request_text"].strip() for item in paraphrases):
        problems.append(f"{group_id}: a kept group must not contain empty paraphrases")
    if len({normalized_text(item["request_text"]) for item in paraphrases}) != len(paraphrases):
        problems.append(f"{group_id}: paraphrases are identical after the recorded edits")
    generator = group.generator
    return FinalGroup(
        batch_id=group.batch_id,
        semantic_group_id=group_id,
        gold_action=str(action),
        gold_fields=fields,
        invalid_fields=invalid if action == "REJECT" else None,
        paraphrases=paraphrases,
        difficulty=generator.get("difficulty"),
        capability_category=generator.get("capability_category"),
        reconciliation_class=group.classification,
        decision_source=f"human:{decision['resolution']}",
        paraphrase_equivalence_source="human",
        rationale=str(decision.get("rationale")),
    )


def apply_decisions(reconciliation: Reconciliation, decisions_doc: Any, *,
                    catalogue: Mapping[str, Mapping[str, Any]] | None = None,
                    profile: Any = None) -> FinalSet:
    """Combine agreed groups with recorded decisions; raise SealRefusal on any problem.

    The contract profile defaults to the one the reconciliation was built with.
    """
    catalogue = reconciliation.catalogue if catalogue is None else catalogue
    profile = get_profile(reconciliation.contract_version if profile is None else profile)
    problems = list(validate_decisions(decisions_doc))
    if problems:
        raise SealRefusal([f"decisions document: {problem}" for problem in problems])
    by_id = {decision["semantic_group_id"]: decision for decision in decisions_doc["decisions"]}
    known = {group.semantic_group_id for group in reconciliation.all_groups()}
    problems.extend(f"decision references unknown group {group_id}"
                    for group_id in sorted(set(by_id) - known))
    final_groups: list[FinalGroup] = []
    excluded: list[dict[str, str]] = []
    applied = 0
    for group in reconciliation.all_groups():
        decision = by_id.get(group.semantic_group_id)
        if decision is None:
            if group.requires_human_decision:
                problems.append(f"unresolved {group.classification} for "
                                f"{group.semantic_group_id}: no human decision recorded")
                continue
            final_groups.append(_from_agreement(group, problems))
            continue
        applied += 1
        if decision["resolution"] == "exclude":
            excluded.append({"semantic_group_id": group.semantic_group_id,
                             "rationale": str(decision.get("rationale"))})
            continue
        final_groups.append(_from_decision(group, decision, catalogue, profile, problems))
    seen_texts: dict[str, str] = {}
    for group in final_groups:
        for item in group.paraphrases:
            key = normalized_text(item["request_text"])
            owner = seen_texts.setdefault(key, group.semantic_group_id)
            if owner != group.semantic_group_id:
                problems.append(f"{group.semantic_group_id}: request text duplicates {owner}")
    declared = decisions_doc.get("quotas")
    if declared is not None:
        expected = {action: int(declared[action]) for action in ACTIONS}
        source = "human_decisions.quotas"
    else:
        expected = default_quotas(reconciliation)
        source = "generator_self_check"
    observed = {action: sum(1 for group in final_groups if group.gold_action == action)
                for action in ACTIONS}
    for action in ACTIONS:
        if observed[action] != expected[action]:
            problems.append(
                f"quota mismatch for {action}: expected {expected[action]} ({source}), "
                f"observed {observed[action]}; declare quotas with quota_rationale in the "
                "decisions file if the change is intentional")
    if problems:
        raise SealRefusal(problems)
    return FinalSet(
        groups=final_groups,
        quotas_expected=expected,
        quotas_observed=observed,
        quota_source=source,
        excluded=excluded,
        decisions_applied=applied,
        decided_by=str(decisions_doc.get("decided_by")),
        decided_at=str(decisions_doc.get("decided_at")),
    )
