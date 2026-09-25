#!/usr/bin/env python3
"""Turn repeated runs of an arm into error bars and a per-item stability count.

`scripts/analyze_frozen_test_results.py` analyses one ledger per arm and keys
records by `request_id`, so it cannot take several repeats of the same arm. This
script takes them: one arm, several ledgers, one per repeat.

It answers two questions the single-run campaign could not.

  * **How wide is the noise?** Action accuracy is reported per repeat, with the
    mean, the range, and the sample standard deviation. A difference between
    arms that is smaller than this spread is not evidence of anything.
  * **Which items are unstable?** An item is stable when every repeat returns
    the same action for it. Unstable items are listed with their per-repeat
    actions, because an item that flips between repeats cannot be used as
    evidence about a model's behaviour, and a benchmark with many of them needs
    repeats rather than a single run.

Majority action is also reported: the most common action across repeats, with a
repeat set that has no majority (every repeat different) counted as incorrect.
It shows what a cheap self-consistency wrapper would buy on this benchmark.

No language model, scheduler, or validator is invoked; this reads ledgers only.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


class VarianceError(ValueError):
    """The repeats supplied cannot be compared."""


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _parse_arm(value: str) -> tuple[str, tuple[str, ...]]:
    name, _, paths = value.partition("=")
    ledgers = tuple(part for part in paths.split(",") if part.strip())
    if not name.strip() or len(ledgers) < 2:
        raise argparse.ArgumentTypeError(
            "expected NAME=PATH,PATH[,PATH] with at least two repeats")
    return name.strip(), ledgers


def _actions(records: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    by_id: dict[str, str] = {}
    for record in records:
        request_id = record["request_id"]
        if request_id in by_id:
            raise VarianceError(
                f"ledger holds two records for {request_id}; one repeat per ledger, "
                "so a ledger must never contain several seeds")
        by_id[request_id] = record["action"]
    return by_id


def _seeds(records: Sequence[Mapping[str, Any]]) -> list[int]:
    return sorted({record["seed"] for record in records if "seed" in record})


def analyse_arm(name: str, ledgers: Sequence[str], harness: Mapping[str, Any]) -> dict[str, Any]:
    repeats = []
    for path in ledgers:
        records = load_jsonl(path)
        unknown = sorted({r["request_id"] for r in records} - set(harness))
        if unknown:
            raise VarianceError(f"{path} holds request ids absent from the harness: {unknown}")
        repeats.append({"ledger": str(path), "seeds": _seeds(records),
                        "actions": _actions(records)})

    covered = [set(repeat["actions"]) for repeat in repeats]
    if len({frozenset(ids) for ids in covered}) != 1:
        missing = sorted(set().union(*covered) - set.intersection(*covered))
        raise VarianceError(f"repeats of {name} do not cover the same items; "
                            f"differing ids: {missing[:10]}")
    request_ids = sorted(covered[0])

    per_repeat = []
    for repeat in repeats:
        correct = sum(1 for r in request_ids
                      if repeat["actions"][r] == harness[r]["gold_action"])
        per_repeat.append({"ledger": repeat["ledger"], "seeds": repeat["seeds"],
                           "correct": correct, "items": len(request_ids),
                           "accuracy": round(correct / len(request_ids), 4)})

    accuracies = [entry["accuracy"] for entry in per_repeat]
    stable, unstable = [], []
    majority_correct = 0
    for request_id in request_ids:
        observed = [repeat["actions"][request_id] for repeat in repeats]
        gold = harness[request_id]["gold_action"]
        if len(set(observed)) == 1:
            stable.append(request_id)
        else:
            unstable.append({"request_id": request_id, "gold_action": gold,
                             "actions": observed})
        counts = Counter(observed)
        top, top_count = counts.most_common(1)[0]
        if top_count > 1 or len(counts) == 1:
            majority_correct += int(top == gold)

    return {
        "repeats": len(repeats),
        "items": len(request_ids),
        "per_repeat": per_repeat,
        "accuracy_mean": round(statistics.fmean(accuracies), 4),
        "accuracy_min": round(min(accuracies), 4),
        "accuracy_max": round(max(accuracies), 4),
        "accuracy_range": round(max(accuracies) - min(accuracies), 4),
        "accuracy_stdev": round(statistics.stdev(accuracies), 4) if len(accuracies) > 1 else 0.0,
        "stable_items": len(stable),
        "stable_fraction": round(len(stable) / len(request_ids), 4),
        "unstable_items": unstable,
        "unstable_per_gold_action": dict(Counter(u["gold_action"] for u in unstable)),
        "majority_correct": majority_correct,
        "majority_accuracy": round(majority_correct / len(request_ids), 4),
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    arms: Mapping[str, Any] = report["arms"]
    lines = [f"# {report['title']}", "",
             f"Harness: `{report['harness']['path']}` ({report['harness']['items']} items)", "",
             "Each column is one arm run several times under identical settings. At",
             "temperature 0 the repeats differ only through provider nondeterminism, so the",
             "spread below is a floor on run-to-run noise, not sampling diversity.", ""]

    names = list(arms)
    widest = max(arm["repeats"] for arm in arms.values())
    header = ["Metric", *names]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|---|" + "---:|" * len(names))
    for index in range(widest):
        cells = []
        for arm in arms.values():
            if index < len(arm["per_repeat"]):
                entry = arm["per_repeat"][index]
                seeds = ",".join(str(s) for s in entry["seeds"]) or "?"
                cells.append(f"{entry['correct']}/{entry['items']} ({entry['accuracy']:.3f}) s{seeds}")
            else:
                cells.append("-")
        lines.append(f"| repeat {index + 1} | " + " | ".join(cells) + " |")
    for label, key, fmt in (("**mean accuracy**", "accuracy_mean", "{:.4f}"),
                            ("range (max - min)", "accuracy_range", "{:+.4f}"),
                            ("stdev", "accuracy_stdev", "{:.4f}"),
                            ("majority-vote accuracy", "majority_accuracy", "{:.4f}")):
        lines.append(f"| {label} | " + " | ".join(
            fmt.format(arm[key]) for arm in arms.values()) + " |")
    lines.append("| stable items | " + " | ".join(
        f"{arm['stable_items']}/{arm['items']} ({arm['stable_fraction']:.3f})"
        for arm in arms.values()) + " |")
    lines.append("")

    if report.get("arm_differences"):
        lines.extend(["## Differences against the noise floor", "",
                      "A gap no larger than the widest within-arm range is not "
                      "distinguishable from noise at this number of repeats.", "",
                      "| Comparison | Mean difference | Widest within-arm range | Verdict |",
                      "|---|---:|---:|---|"])
        for comparison, values in report["arm_differences"].items():
            lines.append(f"| {comparison} | {values['mean_difference']:+.4f} | "
                         f"{values['noise_floor']:.4f} | {values['verdict']} |")
        lines.append("")

    unstable_any = {name: arm["unstable_items"] for name, arm in arms.items()
                    if arm["unstable_items"]}
    if unstable_any:
        lines.extend(["## Unstable items", "",
                      "Items whose action changed between repeats of the same arm.", ""])
        for name, items in unstable_any.items():
            lines.append(f"### {name}")
            lines.append("")
            lines.append("| Request | Gold | Actions across repeats |")
            lines.append("|---|---|---|")
            for item in items:
                lines.append(f"| `{item['request_id']}` | {item['gold_action']} | "
                             + " → ".join(item["actions"]) + " |")
            lines.append("")
    return "\n".join(lines)


def compare(arms: Mapping[str, Any]) -> dict[str, Any]:
    """Compare arm means against the widest within-arm range."""
    names = list(arms)
    out: dict[str, Any] = {}
    for left in range(len(names)):
        for right in range(left + 1, len(names)):
            a, b = names[left], names[right]
            difference = arms[b]["accuracy_mean"] - arms[a]["accuracy_mean"]
            floor = max(arms[a]["accuracy_range"], arms[b]["accuracy_range"])
            out[f"{b} minus {a}"] = {
                "mean_difference": round(difference, 4),
                "noise_floor": round(floor, 4),
                "verdict": ("exceeds the noise floor" if abs(difference) > floor
                            else "within the noise floor"),
            }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--harness", required=True, help="evaluator-side harness JSONL")
    parser.add_argument("--arm", action="append", required=True, type=_parse_arm,
                        metavar="NAME=PATH,PATH", help="an arm and its repeats (repeatable)")
    parser.add_argument("--output-dir", help="write seed_variance.json and .md here (write-once)")
    parser.add_argument("--title", default="Frozen Test v3 run-to-run variance")
    args = parser.parse_args()

    harness = {item["request_id"]: item for item in load_jsonl(args.harness)}
    try:
        arms = {name: analyse_arm(name, ledgers, harness) for name, ledgers in args.arm}
    except (VarianceError, KeyError) as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1

    report = {
        "analysis_format": "agentic_anex.frozen_test_seed_variance.v1",
        "title": args.title,
        "harness": {"path": str(args.harness), "items": len(harness)},
        "decoding": {"temperature": 0,
                     "note": "greedy decoding; repeats measure provider nondeterminism"},
        "no_language_model_or_scheduler_invoked": True,
        "arms": arms,
        "arm_differences": compare(arms),
    }
    if args.output_dir:
        directory = Path(args.output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        payloads = {"seed_variance.json": json.dumps(report, indent=2, sort_keys=True) + "\n",
                    "seed_variance.md": render_markdown(report)}
        existing = sorted(name for name in payloads if (directory / name).exists())
        if existing:
            print(json.dumps({"status": "refused", "problems": [
                f"refusing to overwrite: {', '.join(existing)}"]}, indent=2))
            return 1
        for name, payload in payloads.items():
            (directory / name).write_text(payload, encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "arms"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
