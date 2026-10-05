#!/usr/bin/env python3
"""Render the post-freeze holdout table as LaTeX, from the analysis artefacts.

The holdout's numbers reached the paper as a paragraph of differences, which the
v8 review found hard to read and which left false acceptance out --- the column
that separates losing a correct refusal from actually executing a request the
system cannot serve. This writes the table instead, from the same summary.json
files the paragraph quotes, so the table cannot drift from the analysis.

Arms are rows and metrics are columns. The transpose reads more like Table 1 but
has to be a full-width float, and a full-width float can only be placed at the
top of a page, which on a full page displaces more text than the shape saves.

The ablation row is the paired contrast against that model family's enforcing
arm, which is the comparison the protocol fixed in advance; the enforcing arms
and the rule baseline have no such contrast and print a dash. No model, ANEX,
policy or validator is invoked.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

#: arm -> (display name, summary holding its ablation contrast, baseline arm)
LAYOUT = (
    ("rule_based", "Rule", None, None),
    ("phi4_gated", "Phi4", None, None),
    ("phi4_no_gate", "Phi4-ng", "phi4", "phi4_gated"),
    ("phi4_advisory", "Phi4-adv", "phi4", "phi4_gated"),
    ("qwen25_gated", "Qwen", None, None),
    ("gpt55_gated", "GPT", None, None),
    ("gpt55_no_gate", "GPT-ng", "gpt", "gpt55_gated"),
    ("gpt55_advisory", "GPT-adv", "gpt", "gpt55_gated"),
)


def _mean_count(entry: Mapping[str, Any], leaf: str) -> str:
    """A repeated arm's count, written so it cannot be read as an exact one.

    With repeats the stored integer is a rounded mean while the rate beside it is
    the mean of the per-run rates, so printing `58 (0.801)` invites the reader to
    divide and find 0.806. Where the repeats disagree we print the mean to one
    decimal; where they agree the integer is exact. The range is left to the
    artefact, because a range in every cell makes the table wider than a column.
    """
    values = entry.get(f"{leaf}_repeats")
    if not values or len(set(values)) == 1:
        return str(entry[leaf])
    return f"{sum(values) / len(values):.1f}"


def _contrast(summary: Mapping[str, Any], arm: str, baseline: str) -> str:
    entry = (summary.get("paired_comparisons") or {}).get(f"{arm} minus {baseline}")
    if not entry:
        return "---"
    return f"${entry['mean_difference']:+.4f}$"


def _interval(summary: Mapping[str, Any], arm: str, baseline: str) -> str:
    entry = (summary.get("paired_comparisons") or {}).get(f"{arm} minus {baseline}")
    if not entry:
        return "---"
    low, high = entry["ci95"]
    return f"[${low:+.3f}$, ${high:+.3f}$]"


def render(main: Mapping[str, Any], ablations: Mapping[str, Mapping[str, Any]]) -> str:
    arms = main["arms"]
    present = [row for row in LAYOUT if row[0] in arms]

    def accuracy(name):
        a = arms[name]["action_accuracy"]
        return f"{_mean_count(a, 'correct')} ({a['rate']:.3f})"

    def false_acceptance(name):
        f = arms[name]["false_acceptance"]
        return f"{_mean_count(f, 'count')} ({f['rate']:.3f})"

    def joint(name):
        j = arms[name]["joint_intent_success"]
        return f"{_mean_count(j, 'completed')}/{j['items']}"

    def both(name, family, baseline):
        if not family or family not in ablations:
            return "---"
        return (f"{_contrast(ablations[family], name, baseline)} "
                f"{_interval(ablations[family], name, baseline)}")

    return "\n".join([
        r"\begin{table}[tb]",
        r"\caption{The post-freeze holdout: 72 requests in 36 groups "
        r"(Section~\ref{sec:holdout}). A model arm is the mean of three "
        r"repeats, to one decimal where they disagree; rates and contrasts use "
        r"the unrounded means. \emph{Ablation} is the paired difference in "
        r"action accuracy from that model's enforcing arm, over this batch's 36 "
        r"groups, against the prespecified criterion that it be positive. From "
        r"\texttt{analysis\_holdout\_all/\allowbreak summary.json}.}",
        r"\label{tab:holdout}",
        r"\small",
        r"\setlength{\tabcolsep}{4pt}",
        r"\renewcommand{\arraystretch}{0.95}",
        r"\begin{tabular}{@{}lrrrl@{}}",
        r"\toprule",
        r"Arm & Action acc. & False acc. & Joint & Ablation vs.\ enforcing \\",
        r"\midrule",
        *[f"{label} & {accuracy(name)} & {false_acceptance(name)} & "
          f"{joint(name)} & {both(name, family, baseline)} \\\\"
          for name, label, family, baseline in present],
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", required=True, help="analysis_holdout_all summary.json")
    parser.add_argument("--ablation", action="append", default=[], metavar="FAMILY=PATH",
                        help="summary.json carrying a family's paired contrasts (repeatable)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    ablations = {}
    for pair in args.ablation:
        family, _, path = pair.partition("=")
        if not path:
            print(json.dumps({"status": "refused", "problems": [
                f"--ablation wants FAMILY=PATH, got {pair!r}"]}, indent=2))
            return 1
        ablations[family] = json.loads(Path(path).read_text(encoding="utf-8"))

    report = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("% Generated by scripts/render_holdout_table.py. Do not edit.\n"
                   f"% Source: {args.summary}\n" + render(report, ablations),
                   encoding="utf-8")
    print(json.dumps({"status": "rendered", "out": str(out),
                      "arms": [r[0] for r in LAYOUT if r[0] in report["arms"]],
                      "families": sorted(ablations)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
