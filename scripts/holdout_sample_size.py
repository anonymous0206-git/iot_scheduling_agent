#!/usr/bin/env python3
"""How many semantic groups a holdout batch needs, from the spread this one has.

The paper's intervals are a paired bootstrap over paraphrase groups, so the
quantity that sets their width is the standard deviation of the per-group
paired difference. That is measurable on the benchmark we already have, and it
is the only honest basis for sizing a batch that does not exist yet: a quota
picked round is a quota picked to look tidy.

For each contrast this reports the observed per-group spread, the half-width it
produced at 72 groups, and the number of groups a target half-width would need.
Two cautions a reader should carry:

  * the estimate assumes the new batch's items are drawn like this one's ---
    same ten protocol categories, same quotas, two wordings per intent. A batch
    with a different composition has a different spread and this number does
    not transfer to it.
  * a half-width is not a promise. The new batch is one draw; its interval will
    be wider or narrower than the target by chance, and an effect that is
    smaller there than here will still be indistinguishable from zero.

The normal approximation is used for the projection (1.96 s / sqrt(n)), and its
agreement with the bootstrap at the size we have is reported alongside, so a
reader can see how much the approximation is worth before trusting it at other
sizes.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_frozen_test_results import load_jsonl, paired_difference  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# The contrasts the paper reports and would want to reproduce on a holdout.
CONTRASTS = (
    ("gpt55_gated", "gpt55_no_gate", "frontier: gate off minus enforcing"),
    ("phi4_gated", "phi4_no_gate", "14B: gate off minus enforcing"),
    ("phi4_gated", "phi4_advisory", "14B: advisory minus enforcing"),
    ("rule_based", "gpt55_no_gate", "frontier ungated minus the rule baseline"),
)
TARGET_HALF_WIDTHS = (0.10, 0.075, 0.05, 0.04, 0.03)


def group_differences(first: Sequence[Sequence[Mapping[str, Any]]],
                      second: Sequence[Sequence[Mapping[str, Any]]]) -> list[float]:
    """One number per paraphrase group: the arms' mean difference on its items.

    Per request an arm scores the fraction of its repeats that answered
    correctly, which is what the paper's estimator uses; the group's value is
    the mean over its wordings, because the group is the resampling unit.
    """
    def per_item(repeats: Sequence[Sequence[Mapping[str, Any]]]) -> dict[str, float]:
        totals: dict[str, list[int]] = defaultdict(list)
        for records in repeats:
            for record in records:
                totals[record["request_id"]].append(
                    int(record["action"] == record["gold_action"]))
        return {key: statistics.fmean(values) for key, values in totals.items()}

    left, right = per_item(first), per_item(second)
    groups: dict[str, list[float]] = defaultdict(list)
    for record in first[0]:
        request_id = record["request_id"]
        if request_id in left and request_id in right:
            groups[str(record["paraphrase_group_id"])].append(
                right[request_id] - left[request_id])
    return [statistics.fmean(values) for _, values in sorted(groups.items())]


def groups_for_power(spread: float, effect: float, power: float = 0.80,
                     alpha: float = 0.05) -> int | None:
    """Groups needed to reject zero at `power`, if the effect is what we saw.

    Width alone is the wrong target: an interval can be narrow and still sit on
    zero. This is the question the holdout actually asks --- would an effect
    this size be distinguishable from nothing on fresh intents --- and it is
    answered with the usual two-sample-free formula for a paired mean,
    ((z_alpha/2 + z_power) * sd / effect)^2. It inherits the assumption that
    the new batch has this batch's spread.
    """
    if effect == 0:
        return None
    z_alpha = 1.959964  # two-sided 0.05
    z_power = 0.841621  # 0.80
    return math.ceil(((z_alpha + z_power) * spread / abs(effect)) ** 2)


def power_at(spread: float, effect: float, groups: int) -> float:
    """The power this effect would have at a given number of groups."""
    if spread == 0:
        return 1.0
    z_alpha = 1.959964
    z = abs(effect) * math.sqrt(groups) / spread - z_alpha
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def needed_groups(spread: float, half_width: float) -> int:
    if half_width <= 0:
        raise ValueError("half width must be positive")
    return math.ceil((1.96 * spread / half_width) ** 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--analysis", default="results/frozen_test_v3/analysis_v37/summary.json")
    parser.add_argument("--output-dir")
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    args = parser.parse_args()

    source = json.loads((ROOT / args.analysis).read_text(encoding="utf-8"))
    ledgers = {name: [load_jsonl(ROOT / path) for path in paths]
               for name, paths in source["ledgers"].items()}

    rows = []
    for first, second, label in CONTRASTS:
        if first not in ledgers or second not in ledgers:
            continue
        differences = group_differences(ledgers[first], ledgers[second])
        spread = statistics.stdev(differences)
        observed = statistics.fmean(differences)
        groups = len(differences)
        normal_half = 1.96 * spread / math.sqrt(groups)
        boot = paired_difference(ledgers[first], ledgers[second],
                                 args.bootstrap_samples, args.bootstrap_seed,
                                 cluster_by_group=True)
        boot_half = (boot["ci95"][1] - boot["ci95"][0]) / 2 if boot else None
        rows.append({
            "contrast": f"{second} minus {first}",
            "label": label,
            "groups_observed": groups,
            "mean_difference": round(observed, 4),
            "per_group_sd": round(spread, 4),
            "half_width_normal": round(normal_half, 4),
            "half_width_bootstrap": round(boot_half, 4) if boot_half else None,
            "normal_over_bootstrap": round(normal_half / boot_half, 3) if boot_half else None,
            "groups_for_half_width": {f"{target:g}": needed_groups(spread, target)
                                      for target in TARGET_HALF_WIDTHS},
            "groups_for_80_percent_power_at_this_effect": groups_for_power(spread, observed),
            "power_at_72_groups": round(power_at(spread, observed, 72), 3),
            "power_at_36_groups": round(power_at(spread, observed, 36), 3),
        })

    report = {
        "analysis_format": "agentic_anex.holdout_sample_size.v1",
        "title": "Groups a holdout batch needs, projected from the observed per-group spread",
        "source_analysis": args.analysis,
        "method": ("per-group paired difference, standard deviation across groups, "
                   "half-width 1.96*sd/sqrt(n); the bootstrap half-width at the "
                   "observed size is reported beside it as a check on the "
                   "approximation"),
        "assumes": ("the holdout draws items the way this benchmark does: the same "
                    "ten protocol categories and quotas, two wordings per intent"),
        "no_language_model_or_scheduler_invoked": True,
        "contrasts": rows,
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    lines = [f"# {report['title']}", "", report["method"], "",
             "| contrast | observed diff | per-group SD | half-width now (n=72) | "
             + " | ".join(f"n for ±{t:g}" for t in TARGET_HALF_WIDTHS) + " |",
             "| --- | ---: | ---: | ---: | " + " | ".join("---:" for _ in TARGET_HALF_WIDTHS) + " |"]
    for row in rows:
        cells = " | ".join(str(row["groups_for_half_width"][f"{t:g}"]) for t in TARGET_HALF_WIDTHS)
        lines.append(f"| {row['label']} | {row['mean_difference']:+.4f} | "
                     f"{row['per_group_sd']:.4f} | ±{row['half_width_bootstrap']:.4f} | {cells} |")
    lines += ["", "## Power, which is the question the holdout asks", "",
              "| contrast | effect seen | power at 36 groups | power at 72 | "
              "groups for 80% power |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in rows:
        lines.append(f"| {row['label']} | {row['mean_difference']:+.4f} | "
                     f"{row['power_at_36_groups']:.2f} | {row['power_at_72_groups']:.2f} | "
                     f"{row['groups_for_80_percent_power_at_this_effect']} |")
    lines += ["", "Each n is paraphrase groups; a group is two requests, so double it "
                  "for the item count.", ""]
    markdown = "\n".join(lines)

    if args.output_dir:
        directory = ROOT / args.output_dir
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
        print(json.dumps({"status": "sized", "output_dir": str(directory)}, indent=2))
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
