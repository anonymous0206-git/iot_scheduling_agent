#!/usr/bin/env python3
"""Offline analysis of Frozen Test ledgers against the evaluator-side harness.

Reads one or more append-only ledgers produced by an experiment runner and the
harness file that carries the gold labels, then reports the metrics the
evaluation protocol asks for: action accuracy, a confusion matrix, field exact
match, gold-aware task completion, false acceptance, schedule validity,
paraphrase consistency, per-batch and per-category breakdowns, overhead, and a
failure taxonomy that separates semantic, schedule, and infrastructure
failures.

It reads files only. No model, ANEX, policy, or validator is invoked, so the
numbers in a report can be regenerated from the ledgers at any time.

Definitions that need stating, because the protocol leaves room:

  field exact match   Over gold-EXECUTE items only, the fraction of the ten
                      contract fields whose value in the ledger's parsed
                      fields equals the gold value. Fields the system did not
                      report count as misses. Topology-owned fields the runner
                      binds rather than parses (working_period,
                      communication_range) are compared when present and
                      reported separately as `bound_fields_excluded`.
  task completion     Action correct, and for EXECUTE also a successful run
                      with a valid schedule; for CLARIFY also at least one
                      clarification field; for REJECT and UNSUPPORTED the
                      correct action is sufficient. Unlike the raw `success`
                      column of a ledger this is gold-aware, so an accepted
                      out-of-scope request never counts as completion.
  false acceptance    The system answered EXECUTE where the gold action is
                      not EXECUTE, or claimed completion without a valid
                      schedule.
  resample unit       The paired bootstrap resamples paraphrase groups by
                      default, not requests. A group is one intent written two
                      ways, so its two requests are not independent draws, and
                      resampling them separately reports an interval narrower
                      than the evidence supports. Both intervals are reported.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

ACTIONS: tuple[str, ...] = ("EXECUTE", "CLARIFY", "REJECT", "UNSUPPORTED")
CONTRACT_FIELDS: tuple[str, ...] = (
    "topology_id", "workload", "objective", "channels", "interference_ratio",
    "collision_model", "latency_target_slots", "seed", "working_period",
    "communication_range",
)
BOUND_FIELDS: tuple[str, ...] = ("topology_id", "working_period", "communication_range")
# A failure of the provider is not a failure of the agent. Leaving
# HTTP_PROVIDER_ERROR out of this set once cost us a campaign: a rate-limited
# run recorded 113 items as the model refusing, which reads as an unusually
# safe arm rather than as an outage. MODEL_UNAVAILABLE is the 404 case from the
# same transport layer and belongs here for the same reason.
INFRASTRUCTURE_CODES = {"PROVIDER_TIMEOUT", "INTERNAL_EXPERIMENT_EXCEPTION",
                        "HTTP_PROVIDER_ERROR", "MODEL_UNAVAILABLE"}


class AnalysisError(ValueError):
    """The ledgers and the harness cannot be analysed together."""


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AnalysisError(f"{path}:{number}: invalid JSON: {exc}") from exc
        records.append(value)
    return records


def _equal(left: Any, right: Any) -> bool:
    """Value equality that keeps booleans distinct from numbers."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    return left == right


def _certificate_valid(record: Mapping[str, Any]) -> bool:
    validation = record.get("validation") or {}
    return bool(validation.get("valid")) and not validation.get("violations")


def _is_infrastructure_failure(record: Mapping[str, Any]) -> bool:
    return (record.get("error_code") in INFRASTRUCTURE_CODES
            or str(record.get("failure_category") or "").startswith("internal_exception"))


def task_completed(record: Mapping[str, Any]) -> bool:
    gold = record["gold_action"]
    if record["action"] != gold:
        return False
    if gold == "EXECUTE":
        return bool(record.get("success")) and _certificate_valid(record)
    if gold == "CLARIFY":
        return bool(record.get("clarification_fields"))
    return True


def field_exact_match(records: Sequence[Mapping[str, Any]],
                      harness: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    matched = total = 0
    bound_matched = bound_total = 0
    per_field: dict[str, dict[str, int]] = {name: {"matched": 0, "total": 0}
                                            for name in CONTRACT_FIELDS}
    for record in records:
        item = harness[record["request_id"]]
        gold = item.get("gold_fields")
        if item["gold_action"] != "EXECUTE" or not isinstance(gold, Mapping):
            continue
        parsed = record.get("parsed_fields") or {}
        for name in CONTRACT_FIELDS:
            if name not in gold:
                continue
            ok = _equal(gold[name], parsed.get(name))
            per_field[name]["total"] += 1
            per_field[name]["matched"] += int(ok)
            if name in BOUND_FIELDS:
                bound_total += 1
                bound_matched += int(ok)
            else:
                total += 1
                matched += int(ok)
    return {
        "definition": "gold-EXECUTE items, contract fields the system parses",
        "matched": matched,
        "total": total,
        "rate": round(matched / total, 4) if total else 0.0,
        "bound_fields_excluded": {
            "fields": list(BOUND_FIELDS),
            "matched": bound_matched,
            "total": bound_total,
            "rate": round(bound_matched / bound_total, 4) if bound_total else 0.0,
            "note": "bound or echoed by the runner rather than parsed from the request",
        },
        "per_field": {name: {**counts,
                             "rate": round(counts["matched"] / counts["total"], 4)
                             if counts["total"] else 0.0}
                      for name, counts in per_field.items() if counts["total"]},
    }


def analyse_arm(name: str, records: Sequence[Mapping[str, Any]],
                harness: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    unknown = sorted({r["request_id"] for r in records} - set(harness))
    if unknown:
        raise AnalysisError(f"{name}: ledger has request ids absent from the harness: {unknown[:5]}")
    count = len(records)
    if not count:
        raise AnalysisError(f"{name}: ledger is empty")
    confusion: dict[str, Counter] = defaultdict(Counter)
    for record in records:
        confusion[record["gold_action"]][record["action"]] += 1
    correct = sum(r["action"] == r["gold_action"] for r in records)
    execute = [r for r in records if r["gold_action"] == "EXECUTE"]
    false_acceptance = [
        r["request_id"] for r in records
        if (r["action"] == "EXECUTE" and r["gold_action"] != "EXECUTE")
        or (r["action"] == "EXECUTE" and not _certificate_valid(r))
    ]
    groups: dict[str, list[str]] = defaultdict(list)
    for record in records:
        groups[record["paraphrase_group_id"]].append(record["action"])
    inconsistent = sorted(g for g, actions in groups.items() if len(set(actions)) > 1)
    per_batch: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "items": 0})
    per_category: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "items": 0})
    for record in records:
        item = harness[record["request_id"]]
        ok = int(record["action"] == record["gold_action"])
        batch = per_batch[str(item.get("batch_id"))]
        batch["correct"] += ok
        batch["items"] += 1
        category = per_category[str(item.get("category"))]
        category["correct"] += ok
        category["items"] += 1
    infrastructure = [r["request_id"] for r in records if _is_infrastructure_failure(r)]
    schedule_failures = [r["request_id"] for r in records
                         if r["gold_action"] == "EXECUTE" and r["action"] != "EXECUTE"
                         and r.get("error_code") == "VALIDATION_CERTIFICATE_FAILED"]
    semantic_failures = [r["request_id"] for r in records
                         if r["action"] != r["gold_action"]
                         and r["request_id"] not in infrastructure
                         and r["request_id"] not in schedule_failures]
    wall = [r.get("wall_time_seconds", 0.0) for r in records]
    return {
        "records": count,
        "systems": sorted({(r["system"], r["model"]) for r in records}),
        "action_accuracy": {"correct": correct, "items": count,
                            "rate": round(correct / count, 4)},
        "confusion_gold_by_predicted": {
            gold: {action: confusion[gold].get(action, 0) for action in ACTIONS}
            for gold in ACTIONS},
        "per_gold_action": {
            gold: {"correct": confusion[gold].get(gold, 0),
                   "items": sum(confusion[gold].values()),
                   "rate": round(confusion[gold].get(gold, 0) / sum(confusion[gold].values()), 4)
                   if sum(confusion[gold].values()) else 0.0}
            for gold in ACTIONS},
        "task_completion": {
            "completed": sum(task_completed(r) for r in records), "items": count,
            "rate": round(sum(task_completed(r) for r in records) / count, 4)},
        "field_exact_match": field_exact_match(records, harness),
        "false_acceptance": {"count": len(false_acceptance),
                             "rate": round(len(false_acceptance) / count, 4),
                             "request_ids": false_acceptance},
        "schedule_validity_on_gold_execute": {
            "valid": sum(_certificate_valid(r) for r in execute), "items": len(execute),
            "rate": round(sum(_certificate_valid(r) for r in execute) / len(execute), 4)
            if execute else 0.0},
        "paraphrase_consistency": {
            "consistent_groups": len(groups) - len(inconsistent), "groups": len(groups),
            "rate": round((len(groups) - len(inconsistent)) / len(groups), 4) if groups else 0.0,
            "inconsistent_groups": inconsistent},
        "per_batch": {batch: {**values,
                              "rate": round(values["correct"] / values["items"], 4)}
                      for batch, values in sorted(per_batch.items())},
        "categories_with_errors": {
            category: values for category, values in sorted(per_category.items())
            if values["correct"] < values["items"]},
        "failure_taxonomy": {
            "semantic": len(semantic_failures),
            "schedule": len(schedule_failures),
            "infrastructure": len(infrastructure),
            "schedule_request_ids": schedule_failures,
            "infrastructure_request_ids": infrastructure},
        "error_codes": dict(Counter(r.get("error_code") for r in records
                                    if r.get("error_code"))),
        "overhead": {
            "retries": sum(r.get("retries", 0) for r in records),
            "model_calls": sum(r.get("model_calls", 0) for r in records),
            "total_tokens": sum(r.get("total_tokens", 0) for r in records),
            "mean_wall_seconds": round(statistics.mean(wall), 3) if wall else 0.0,
            "total_wall_seconds": round(sum(wall), 1)},
        "wrong_items": [
            {"request_id": r["request_id"], "group": r["paraphrase_group_id"],
             "gold": r["gold_action"], "predicted": r["action"],
             "error_code": r.get("error_code")}
            for r in sorted(records, key=lambda x: x["request_id"])
            if r["action"] != r["gold_action"]],
    }


def _repeat_count(value: Sequence[Any]) -> int:
    return 1 if (value and isinstance(value[0], Mapping)) else len(value)


def _score_per_item(repeats: Sequence[Sequence[Mapping[str, Any]]]) -> dict[str, float]:
    """Per request, the fraction of this arm's repeats that got it right.

    With one repeat this is 0 or 1 and the estimator is the single-run one. With
    three, an item the arm gets right twice scores 2/3, so an item that flips
    between repeats contributes the partial evidence it actually is rather than
    whichever way one arbitrary run happened to fall.
    """
    # A flat list of records is one repeat; callers with a single run need not
    # wrap it.
    if repeats and isinstance(repeats[0], Mapping):
        repeats = [repeats]  # type: ignore[list-item]
    totals: dict[str, list[int]] = defaultdict(list)
    for records in repeats:
        for record in records:
            totals[record["request_id"]].append(
                int(record["action"] == record["gold_action"]))
    return {key: statistics.fmean(values) for key, values in totals.items()}


def paired_difference(first: Sequence[Sequence[Mapping[str, Any]]],
                      second: Sequence[Sequence[Mapping[str, Any]]],
                      samples: int, seed: int,
                      cluster_by_group: bool = False) -> dict[str, Any] | None:
    """Bootstrap the paired action-accuracy difference, second minus first.

    The resampling unit is the request by default and the paraphrase group when
    `cluster_by_group` is set. A group is one intent written two ways, so its
    two requests are not independent draws: resampling them separately treats
    one intent as two observations and reports an interval narrower than the
    evidence supports. Clustering draws groups with replacement and takes both
    wordings of every group drawn, which is the unit the benchmark was
    stratified on. Pairing across arms is by request either way.
    """
    import random
    left = _score_per_item(first)
    right = _score_per_item(second)
    shared = sorted(set(left) & set(right))
    if len(shared) < 2:
        return None
    diffs = {key: right[key] - left[key] for key in shared}
    rng = random.Random(seed)
    means = []
    if cluster_by_group:
        groups: dict[str, list[str]] = defaultdict(list)
        seen: set[str] = set()
        first_repeat = first[0] if first and not isinstance(first[0], Mapping) else first
        for record in first_repeat:
            request_id = record["request_id"]
            if request_id in diffs and request_id not in seen:
                seen.add(request_id)
                groups[str(record["paraphrase_group_id"])].append(request_id)
        keys = sorted(groups)
        if len(keys) < 2:
            return None
        clusters = [[diffs[request] for request in sorted(groups[key])] for key in keys]
        for _ in range(samples):
            drawn = [value for cluster in rng.choices(clusters, k=len(clusters))
                     for value in cluster]
            means.append(statistics.fmean(drawn))
        unit, units = "paraphrase_group", len(keys)
    else:
        values = [diffs[key] for key in shared]
        for _ in range(samples):
            means.append(statistics.fmean(rng.choices(values, k=len(values))))
        unit, units = "request", len(shared)
    means.sort()
    low = means[max(0, int(0.025 * samples) - 1)]
    high = means[min(samples - 1, int(0.975 * samples))]
    return {"pairs": len(shared),
            "repeats": [_repeat_count(first), _repeat_count(second)],
            "mean_difference": round(statistics.fmean(diffs.values()), 4),
            "ci95": [round(low, 4), round(high, 4)],
            "resample_unit": unit, "resample_units": units,
            "bootstrap_samples": samples, "bootstrap_seed": seed}


# Scalar metrics an arm reports once per repeat. Each is (path into the arm
# dict, whether it is an integer count), and each gets a mean and a range when
# the arm was run more than once.
REPEATED_METRICS: tuple[tuple[tuple[str, ...], bool], ...] = (
    (("action_accuracy", "correct"), True),
    (("action_accuracy", "rate"), False),
    (("task_completion", "completed"), True),
    (("task_completion", "rate"), False),
    (("field_exact_match", "rate"), False),
    (("false_acceptance", "count"), True),
    (("false_acceptance", "rate"), False),
    (("paraphrase_consistency", "consistent_groups"), True),
    (("overhead", "model_calls"), True),
    (("overhead", "mean_wall_seconds"), False),
)


def _dig(value: Mapping[str, Any], path: Sequence[str]) -> Any:
    for key in path:
        value = value[key]
    return value


def aggregate_repeats(name: str, repeats: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fold several runs of one arm into one entry carrying its spread.

    A single run cannot separate a real difference between arms from the
    provider's own nondeterminism, so an arm run more than once reports the
    mean of its repeats and the range they span. The first repeat supplies the
    structure --- per-item lists, confusion matrix, per-category counts --- so
    everything that was available for a single run is still available; the
    scalar metrics gain `repeats`, `mean`, `min` and `max`, and the mean
    replaces the point value the table prints.
    """
    if len(repeats) == 1:
        # Returned untouched, so a one-run campaign analyses byte-for-byte as
        # it did before repeats existed.
        return dict(repeats[0])
    merged = json.loads(json.dumps(repeats[0]))
    merged["repeat_count"] = len(repeats)
    for path, is_count in REPEATED_METRICS:
        values = [_dig(repeat, path) for repeat in repeats]
        target = _dig(merged, path[:-1])
        leaf = path[-1]
        mean = statistics.fmean(values)
        target[leaf] = round(mean) if is_count else round(mean, 4)
        target[f"{leaf}_repeats"] = values
        target[f"{leaf}_mean"] = round(mean, 4)
        target[f"{leaf}_min"] = min(values)
        target[f"{leaf}_max"] = max(values)
    # Per-gold-action counts are the table's other numeric row.
    for action in ACTIONS:
        values = [repeat["per_gold_action"][action]["correct"] for repeat in repeats]
        entry = merged["per_gold_action"][action]
        entry["correct"] = round(statistics.fmean(values))
        entry["correct_repeats"] = values
        entry["correct_min"], entry["correct_max"] = min(values), max(values)
    return merged


def _parse_ledger(spec: str) -> tuple[str, Path]:
    name, separator, path = spec.partition("=")
    if not separator or not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    return name.strip(), Path(path.strip())


def render_markdown(report: Mapping[str, Any]) -> str:
    arms = report["arms"]
    lines = [f"# {report['title']}", "",
             f"Harness: `{report['harness']['path']}` ({report['harness']['items']} items)", "",
             "| Metric | " + " | ".join(arms) + " |",
             "|---|" + "---:|" * len(arms)]

    def row(label, getter):
        lines.append(f"| {label} | " + " | ".join(str(getter(arms[a])) for a in arms) + " |")

    row("Action accuracy", lambda a: f"{a['action_accuracy']['correct']} ({a['action_accuracy']['rate']:.3f})")
    for action in ACTIONS:
        row(f"{action} correct", lambda a, x=action: f"{a['per_gold_action'][x]['correct']}/{a['per_gold_action'][x]['items']}")
    row("Task completion (gold-aware)", lambda a: f"{a['task_completion']['completed']} ({a['task_completion']['rate']:.3f})")
    row("Field exact match on EXECUTE", lambda a: f"{a['field_exact_match']['rate']:.3f}")
    row("False acceptance", lambda a: f"{a['false_acceptance']['count']} ({a['false_acceptance']['rate']:.3f})")
    row("Valid schedule on gold EXECUTE", lambda a: f"{a['schedule_validity_on_gold_execute']['valid']}/{a['schedule_validity_on_gold_execute']['items']}")
    row("Paraphrase-consistent groups", lambda a: f"{a['paraphrase_consistency']['consistent_groups']}/{a['paraphrase_consistency']['groups']}")
    row("Semantic / schedule / infra failures", lambda a: "{semantic} / {schedule} / {infrastructure}".format(**a["failure_taxonomy"]))
    row("Retries / calls / tokens", lambda a: f"{a['overhead']['retries']} / {a['overhead']['model_calls']} / {a['overhead']['total_tokens']}")
    row("Mean wall seconds", lambda a: f"{a['overhead']['mean_wall_seconds']:.2f}")
    lines.append("")
    if report.get("paired_comparisons"):
        first = next(iter(report["paired_comparisons"].values()))
        unit = first.get("resample_unit", "request")
        other = "request" if unit == "paraphrase_group" else "paraphrase_group"
        lines.extend([f"## Paired action-accuracy differences, resampling by {unit}", "",
                      f"| Comparison | Mean difference | 95% CI | 95% CI by {other} | Pairs |",
                      "|---|---:|---|---|---:|"])
        for comparison, values in report["paired_comparisons"].items():
            spare = values.get(f"ci95_by_{other}")
            spare_cell = f"[{spare[0]:+.4f}, {spare[1]:+.4f}]" if spare else "-"
            lines.append(f"| {comparison} | {values['mean_difference']:+.4f} | "
                         f"[{values['ci95'][0]:+.4f}, {values['ci95'][1]:+.4f}] | "
                         f"{spare_cell} | {values['pairs']} |")
        lines.append("")
    lines.extend(["## Per batch", "", "| Arm | " + " | ".join(
        sorted({b for a in arms.values() for b in a["per_batch"]})) + " |",
        "|---|" + "---:|" * len({b for a in arms.values() for b in a["per_batch"]})])
    batches = sorted({b for a in arms.values() for b in a["per_batch"]})
    for name, arm in arms.items():
        cells = [f"{arm['per_batch'][b]['correct']}/{arm['per_batch'][b]['items']}"
                 if b in arm["per_batch"] else "-" for b in batches]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--harness", required=True, help="evaluator-side harness JSONL")
    parser.add_argument("--ledger", action="append", required=True, type=_parse_ledger,
                        metavar="NAME=PATH", help="ledger to analyse (repeatable)")
    parser.add_argument("--baseline", help="arm name used as the baseline in paired comparisons")
    parser.add_argument("--output-dir", help="write summary.json and summary.md here (write-once)")
    parser.add_argument("--title", default="Frozen Test results")
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    parser.add_argument("--resample-unit", choices=("paraphrase_group", "request"),
                        default="paraphrase_group",
                        help="unit the paired bootstrap resamples; the interval for the "
                             "other unit is reported alongside it as ci95_by_request or "
                             "ci95_by_paraphrase_group")
    args = parser.parse_args()

    harness_items = load_jsonl(args.harness)
    harness = {item["request_id"]: item for item in harness_items}
    # Repeating --ledger with the same NAME declares repeats of one arm rather
    # than two arms, so a three-seed campaign is analysed by naming each arm
    # three times.
    grouped: dict[str, list[Path]] = defaultdict(list)
    for name, path in args.ledger:
        grouped[name].append(path)
    try:
        arms = {name: aggregate_repeats(
                    name, [analyse_arm(name, load_jsonl(path), harness) for path in paths])
                for name, paths in grouped.items()}
    except AnalysisError as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1
    # The paired bootstrap needs one outcome per item. With repeats, an item
    # scores the fraction of repeats the arm got it right, which keeps the
    # pairing and lets an item that flips between repeats count as the partial
    # evidence it is instead of as a coin flip the interval cannot see.
    ledgers = {name: [load_jsonl(path) for path in paths]
               for name, paths in grouped.items()}
    comparisons: dict[str, Any] = {}
    baseline = args.baseline or next(iter(arms))
    if baseline in ledgers:
        for name, repeats in ledgers.items():
            if name == baseline:
                continue
            clustered = args.resample_unit == "paraphrase_group"
            result = paired_difference(ledgers[baseline], repeats,
                                       args.bootstrap_samples, args.bootstrap_seed,
                                       cluster_by_group=clustered)
            alternate = paired_difference(ledgers[baseline], repeats,
                                          args.bootstrap_samples, args.bootstrap_seed,
                                          cluster_by_group=not clustered)
            if result:
                if alternate:
                    result[f"ci95_by_{alternate['resample_unit']}"] = alternate["ci95"]
                comparisons[f"{name} minus {baseline}"] = result
    report = {
        "analysis_format": "agentic_anex.frozen_test_analysis.v1",
        "title": args.title,
        "harness": {"path": str(args.harness), "items": len(harness_items),
                    "per_gold_action": dict(Counter(i["gold_action"] for i in harness_items))},
        "ledgers": {name: [str(path) for path in paths] for name, paths in grouped.items()},
        "repeats_per_arm": {name: len(paths) for name, paths in grouped.items()},
        "no_language_model_or_scheduler_invoked": True,
        "arms": arms,
        "paired_comparisons": comparisons,
    }
    if args.output_dir:
        directory = Path(args.output_dir)
        paths = {"summary.json": json.dumps(report, indent=2, sort_keys=True) + "\n",
                 "summary.md": render_markdown(report)}
        existing = [name for name in paths if (directory / name).exists()]
        if existing:
            print(json.dumps({"status": "refused", "problems": [
                f"refusing to overwrite {directory / name}" for name in existing]}, indent=2))
            return 1
        directory.mkdir(parents=True, exist_ok=True)
        for name, text in paths.items():
            with open(directory / name, "x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        print(json.dumps({"status": "analysed", "output_dir": str(directory),
                          "arms": sorted(arms)}, indent=2))
    else:
        print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
