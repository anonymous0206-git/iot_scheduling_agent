#!/usr/bin/env python3
"""How much of the paper's result rests on the gold labels a reader could contest.

The limitations name debatable gold labels, and both review rounds asked what
the numbers do if those labels go the other way. This answers it by re-scoring
the same ledgers under alternative labellings. No model, scheduler, validator or
policy is invoked: it reads the ledgers, changes `gold_action` on the contested
items in memory, and calls the same `analyse_arm`, `aggregate_repeats` and
`paired_difference` that produced the paper's tables, with the same bootstrap
parameters. A metric defined here would prove nothing about the metric in the
paper, so none is.

Which items are contested, and why each one is:

  channel conflict     Two paraphrase groups state one channel count in prose
                       and a different one in an adjacent run-settings block.
                       The gold says REJECT. The repaired agent asks which
                       count is intended. Asking is a defensible reading of a
                       request that contradicts itself, so the alternative
                       labelling is CLARIFY.

  range mismatch       Two paraphrase groups state a communication range that
                       contradicts the bound topology's catalogue value. The
                       gold says REJECT and the agent takes the topology's
                       value. We do not relabel these to EXECUTE --- that would
                       need gold fields authored after seeing the results, which
                       is exactly the move the protocol forbids --- so the
                       alternative is to drop them and report the denominator
                       that leaves.

The variants are therefore: the published gold; the channel groups read as
CLARIFY; the range groups dropped; both; and all four groups dropped, which is
the reading of a reviewer who trusts none of the contested labels. The first
alternative helps the frontier arms and hurts the 14B arms, which answer REJECT
on those items, so this is not a one-directional sensitivity.

Usage:

  python scripts/sensitivity_gold_labels.py \
      --analysis results/frozen_test_v3/analysis_v36/summary.json \
      --output-dir results/frozen_test_v3/sensitivity_labels
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_frozen_test_results import (  # noqa: E402
    aggregate_repeats,
    analyse_arm,
    load_jsonl,
    paired_difference,
)

ROOT = Path(__file__).resolve().parents[1]

# The contested groups are selected by the category the benchmark authors gave
# them, not by request id, so that a change to the benchmark cannot leave this
# script quietly scoring the wrong items. The ids are asserted afterwards.
CHANNEL_CATEGORIES = ("contradictory_channel_specification",
                      "prose_parameter_channel_conflict")
RANGE_CATEGORIES = ("communication_range_mismatch", "catalogue_range_mismatch")
EXPECTED_CHANNEL_IDS = ("ft3-r0004", "ft3-r0112", "ft3-r0113", "ft3-r0121")
EXPECTED_RANGE_IDS = ("ft3-r0033", "ft3-r0106", "ft3-r0130", "ft3-r0141")

# Second minus first, the pairs the paper reports.
COMPARISONS = (
    ("gpt55_gated", "gpt55_no_gate"),
    ("gpt55_gated", "gpt55_advisory"),
    ("gpt55_no_gate", "gpt55_advisory"),
    ("phi4_gated", "phi4_no_gate"),
    ("phi4_gated", "phi4_advisory"),
    ("phi4_no_gate", "phi4_advisory"),
)


class SensitivityError(ValueError):
    """The ledgers or the harness are not what this analysis assumes."""


def contested_ids(harness_items: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    def ids(categories: Sequence[str]) -> list[str]:
        return sorted(item["request_id"] for item in harness_items
                      if item.get("category") in categories)

    found = {"channel_conflict": ids(CHANNEL_CATEGORIES),
             "range_mismatch": ids(RANGE_CATEGORIES)}
    for key, expected in (("channel_conflict", EXPECTED_CHANNEL_IDS),
                          ("range_mismatch", EXPECTED_RANGE_IDS)):
        if tuple(found[key]) != expected:
            raise SensitivityError(
                f"{key}: expected {list(expected)} from the categories, found {found[key]}")
    gold = {item["request_id"]: item["gold_action"] for item in harness_items}
    off_label = sorted(rid for group in found.values() for rid in group
                       if gold[rid] != "REJECT")
    if off_label:
        raise SensitivityError(
            f"contested items are assumed to be gold REJECT; these are not: {off_label}")
    return found


def apply_variant(repeats: Sequence[Sequence[dict[str, Any]]],
                  relabel: Mapping[str, str],
                  drop: Sequence[str]) -> list[list[dict[str, Any]]]:
    """A copy of one arm's repeats with the contested labels changed.

    Both the ledger record and the analysis read `gold_action` off the record,
    so the relabelling happens there rather than in the harness.
    """
    dropped = set(drop)
    out: list[list[dict[str, Any]]] = []
    for records in repeats:
        kept = []
        for record in records:
            if record["request_id"] in dropped:
                continue
            copy = dict(record)
            if copy["request_id"] in relabel:
                copy["gold_action"] = relabel[copy["request_id"]]
            kept.append(copy)
        out.append(kept)
    return out


def arm_row(name: str, repeats: Sequence[Sequence[Mapping[str, Any]]],
            harness: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    merged = aggregate_repeats(name, [analyse_arm(name, records, harness)
                                      for records in repeats])
    accuracy = merged["action_accuracy"]
    false_acceptance = merged["false_acceptance"]
    return {
        "items": accuracy["items"],
        "action_accuracy": accuracy.get("rate_mean", accuracy["rate"]),
        "action_accuracy_repeats": accuracy.get("rate_repeats", [accuracy["rate"]]),
        "correct": accuracy.get("correct_mean", accuracy["correct"]),
        "false_acceptance": false_acceptance.get("count_mean", false_acceptance["count"]),
        "false_acceptance_repeats": false_acceptance.get(
            "count_repeats", [false_acceptance["count"]]),
        "gold_reject_correct": merged["per_gold_action"]["REJECT"]["correct"],
        "gold_reject_items": merged["per_gold_action"]["REJECT"]["items"],
    }


def run_variant(label: str, description: str, ledgers: Mapping[str, list[list[dict[str, Any]]]],
                harness: Mapping[str, Mapping[str, Any]], relabel: Mapping[str, str],
                drop: Sequence[str], samples: int, seed: int) -> dict[str, Any]:
    adjusted = {name: apply_variant(repeats, relabel, drop)
                for name, repeats in ledgers.items()}
    arms = {name: arm_row(name, repeats, harness) for name, repeats in adjusted.items()}
    comparisons: dict[str, Any] = {}
    for first, second in COMPARISONS:
        if first not in adjusted or second not in adjusted:
            continue
        result = paired_difference(adjusted[first], adjusted[second], samples, seed,
                                   cluster_by_group=True)
        if result:
            comparisons[f"{second} minus {first}"] = {
                "difference": result["mean_difference"],
                "ci95": result["ci95"],
                "pairs": result["pairs"],
                "resample_unit": result["resample_unit"],
                "units": result.get("resample_units"),
            }
    return {"label": label, "description": description,
            "relabelled": dict(relabel), "dropped": list(drop),
            "arms": arms, "paired_comparisons": comparisons}


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [f"# {report['title']}", "",
             "Re-scoring of the same ledgers under alternative labellings of the "
             "contested gold items. No model, scheduler or validator was invoked.", ""]
    variants = report["variants"]
    names = sorted(variants[0]["arms"])
    lines += ["## Action accuracy, mean over repeats", "",
              "| arm | " + " | ".join(v["label"] for v in variants) + " |",
              "| --- | " + " | ".join("---" for _ in variants) + " |"]
    for name in names:
        cells = [f"{v['arms'][name]['action_accuracy']:.4f}" for v in variants]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "## False acceptance, mean count over repeats", "",
              "| arm | " + " | ".join(v["label"] for v in variants) + " |",
              "| --- | " + " | ".join("---" for _ in variants) + " |"]
    for name in names:
        cells = [f"{v['arms'][name]['false_acceptance']:g}" for v in variants]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "## Paired differences, group-clustered bootstrap", ""]
    keys = sorted({key for v in variants for key in v["paired_comparisons"]})
    lines += ["| comparison | " + " | ".join(v["label"] for v in variants) + " |",
              "| --- | " + " | ".join("---" for _ in variants) + " |"]
    for key in keys:
        cells = []
        for v in variants:
            entry = v["paired_comparisons"].get(key)
            if not entry:
                cells.append("--")
                continue
            low, high = entry["ci95"]
            cells.append(f"{entry['difference']:+.4f} [{low:+.4f}, {high:+.4f}]")
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
    lines += ["", "## Variants", ""]
    for v in variants:
        lines.append(f"* **{v['label']}** --- {v['description']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--analysis", default="results/frozen_test_v3/analysis_v36/summary.json",
                        help="the analysis whose harness and ledger set this re-scores, so "
                             "the arms cannot drift from the ones the paper reports")
    parser.add_argument("--output-dir")
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    args = parser.parse_args()

    source = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
    harness_path = ROOT / source["harness"]["path"]
    harness_items = load_jsonl(harness_path)
    harness = {item["request_id"]: item for item in harness_items}
    try:
        contested = contested_ids(harness_items)
    except SensitivityError as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1

    ledgers = {name: [load_jsonl(ROOT / path) for path in paths]
               for name, paths in source["ledgers"].items()}

    channel = contested["channel_conflict"]
    ranges = contested["range_mismatch"]
    plans = [
        ("published", "the sealed gold labels, unchanged", {}, []),
        ("channel=CLARIFY",
         "the two channel-conflict groups read as CLARIFY instead of REJECT",
         {rid: "CLARIFY" for rid in channel}, []),
        ("range dropped",
         "the two range-mismatch groups removed from the denominator",
         {}, ranges),
        ("both",
         "channel conflicts read as CLARIFY and range mismatches dropped",
         {rid: "CLARIFY" for rid in channel}, ranges),
        ("all 4 groups dropped",
         "every contested item removed, the reading that trusts none of them",
         {}, channel + ranges),
    ]
    variants = [run_variant(label, description, ledgers, harness, relabel, drop,
                            args.bootstrap_samples, args.bootstrap_seed)
                for label, description, relabel, drop in plans]

    published = variants[0]
    spans = {}
    for name in published["arms"]:
        values = [v["arms"][name]["action_accuracy"] for v in variants]
        spans[name] = {"min": round(min(values), 4), "max": round(max(values), 4),
                       "span": round(max(values) - min(values), 4)}
    signs = {}
    for key in published["paired_comparisons"]:
        entries = [v["paired_comparisons"][key] for v in variants
                   if key in v["paired_comparisons"]]
        differences = [entry["difference"] for entry in entries]
        excludes_zero = [not (entry["ci95"][0] <= 0 <= entry["ci95"][1]) for entry in entries]
        signs[key] = {
            "difference_min": round(min(differences), 4),
            "difference_max": round(max(differences), 4),
            "sign_stable": len({d > 0 for d in differences}) == 1,
            "ci_excludes_zero": excludes_zero,
            "ci_verdict_stable": len(set(excludes_zero)) == 1,
        }

    report = {
        "analysis_format": "agentic_anex.gold_label_sensitivity.v1",
        "title": "Sensitivity of the Frozen Test v3 results to the contested gold labels",
        "source_analysis": str(args.analysis),
        "harness": {"path": str(source["harness"]["path"]), "items": len(harness_items)},
        "no_language_model_or_scheduler_invoked": True,
        "bootstrap": {"samples": args.bootstrap_samples, "seed": args.bootstrap_seed,
                      "resample_unit": "paraphrase_group"},
        "contested_items": {
            key: {"request_ids": ids,
                  "paraphrase_groups": sorted({harness[rid]["paraphrase_group_id"]
                                               for rid in ids}),
                  "categories": sorted({harness[rid]["category"] for rid in ids})}
            for key, ids in contested.items()},
        "variants": variants,
        "action_accuracy_span": spans,
        "paired_comparison_stability": signs,
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    markdown = render_markdown(report)
    if args.output_dir:
        directory = Path(args.output_dir)
        files = {"summary.json": text, "summary.md": markdown}
        existing = [name for name in files if (directory / name).exists()]
        if existing:
            print(json.dumps({"status": "refused", "problems": [
                f"refusing to overwrite {directory / name}" for name in existing]}, indent=2))
            return 1
        directory.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            with open(directory / name, "x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        print(json.dumps({"status": "analysed", "output_dir": str(directory),
                          "variants": [v["label"] for v in variants]}, indent=2))
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
