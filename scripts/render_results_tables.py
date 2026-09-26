#!/usr/bin/env python3
"""Render the paper's results tables from an analysis summary, never by hand.

A number typed into a paper is a number that can drift from the artefact that
produced it. Every figure in the results section comes from
``scripts/analyze_frozen_test_results.py``'s ``summary.json``, so this script
turns that file into the LaTeX the paper includes. Re-running the analysis and
re-running this script is the only way the tables change.

Output is a fragment, not a document: one ``tabular`` per table, wrapped in a
``table`` float with a caption and label, ready for ``\\input``.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

ACTIONS = ("EXECUTE", "CLARIFY", "REJECT", "UNSUPPORTED")


def escape(text: str) -> str:
    """Escape the characters that matter in the short labels we emit."""
    for character, replacement in (("\\", r"\textbackslash{}"), ("_", r"\_"),
                                   ("&", r"\&"), ("%", r"\%"), ("#", r"\#"),
                                   ("$", r"\$")):
        text = text.replace(character, replacement)
    return text


def _spread(entry: Mapping[str, Any], leaf: str, fmt: str) -> str:
    """A range suffix when the arm was repeated and the repeats disagreed.

    An arm run once prints what it scored. An arm run three times prints the
    mean and the span of its repeats, because a reader comparing two arms has
    to be able to see when the gap between them is smaller than the gap
    between one arm and itself.
    """
    low, high = entry.get(f"{leaf}_min"), entry.get(f"{leaf}_max")
    if low is None or high is None or low == high:
        return ""
    return f" [{format(low, fmt)}--{format(high, fmt)}]"


def _fraction(part: Any, whole: Any) -> str:
    return f"{part}/{whole}"


def _mean_only(entry: Mapping[str, Any], leaf: str) -> str:
    """The mean alone, to one decimal when the repeats disagreed.

    Used for the per-action breakdown, where a range on every row would double
    the table's width; the range for the total is on the row above.
    """
    values = entry.get(f"{leaf}_repeats")
    if not values or len(set(values)) == 1:
        return str(entry[leaf])
    return f"{sum(values) / len(values):.1f}"


def _mean_count(entry: Mapping[str, Any], leaf: str) -> str:
    """A repeated arm's count, written so it cannot be read as an exact one.

    With repeats the printed integer is a rounded mean, and a reader has no way
    to tell that from a count. Where the repeats disagree we print the mean to
    one decimal and the range; where they agree the integer is exact and is
    printed plainly.
    """
    values = entry.get(f"{leaf}_repeats")
    if not values or len(set(values)) == 1:
        return str(entry[leaf])
    mean = sum(values) / len(values)
    return f"{mean:.1f} [{min(values)}--{max(values)}]"


def metric_rows(arms: Mapping[str, Mapping[str, Any]]) -> list[tuple[str, list[str]]]:
    """The rows of the main table, in the order the paper reads them."""
    rows: list[tuple[str, list[str]]] = []
    rows.append(("Action accuracy", [
        _mean_count(a["action_accuracy"], "correct") for a in arms.values()]))
    for action in ACTIONS:
        rows.append((f"\\quad \\textsc{{{action.lower()}}}", [
            _mean_only(a["per_gold_action"][action], "correct") + "/"
            + str(a["per_gold_action"][action]["items"])
            for a in arms.values()]))
    # Task completion is reported in the JSON but not here: on this benchmark it
    # equals action accuracy for every arm, so a row would repeat one above it.
    # The text says so once instead.
    rows.append(("Field exact match", [
        f"{float(a['field_exact_match']['rate']):.3f}"
        + _spread(a["field_exact_match"], "rate", ".3f") for a in arms.values()]))
    # The conjunction the interface is judged on: right action, every gold field
    # including the three the runner binds, and a certified schedule. Action
    # accuracy and field exact match can both be high while this is not.
    if all("joint_intent_success" in a for a in arms.values()):
        rows.append(("Joint intent success", [
            _fraction(_mean_only(a["joint_intent_success"], "completed"),
                      a["joint_intent_success"]["items"]) for a in arms.values()]))
    rows.append(("False acceptance", [
        _mean_count(a["false_acceptance"], "count") for a in arms.values()]))
    rows.append(("Paraphrase consistency", [
        _fraction(a["paraphrase_consistency"]["consistent_groups"],
                  a["paraphrase_consistency"]["groups"]) for a in arms.values()]))
    rows.append(("Model calls", [
        str(a["overhead"]["model_calls"]) for a in arms.values()]))
    rows.append(("Mean seconds", [
        f"{float(a['overhead']['mean_wall_seconds']):.2f}" for a in arms.values()]))
    return rows


GATE_MODE = {"llm_agent": "enforcing", "rule_based": "enforcing",
             "llm_agent_no_scope_gate": "off",
             "llm_agent_advisory_scope_gate": "advisory"}


def arm_configuration(arms: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    """The model and the gate mode of each arm, read from its own ledgers.

    Every record carries the system name the orchestrator ran under and the
    model it called, and the analyser folds them into `systems`. Taking the
    configuration from there rather than from a hand-written table is what
    stops the two from disagreeing after a re-run: an arm that was served by a
    different model would change this row as well as the numbers under it.
    """
    models: list[str] = []
    gates: list[str] = []
    for name, arm in arms.items():
        systems = arm.get("systems") or []
        seen_model = {str(entry[1]) for entry in systems if len(entry) > 1}
        seen_gate = {GATE_MODE.get(str(entry[0]), str(entry[0])) for entry in systems}
        # More than one value means the arm's repeats did not run the same
        # configuration, which no single row can honestly report. An analysis
        # that records none (an older summary) leaves the cell blank rather
        # than inventing one.
        if len(seen_model) > 1 or len(seen_gate) > 1:
            raise SystemExit(f"arm {name!r} mixes configurations: {systems}")
        model = seen_model.pop() if seen_model else "deterministic"
        gate = seen_gate.pop() if seen_gate else "---"
        # The rule baseline calls nothing; an em dash says so more plainly than
        # the word "deterministic" repeated under a column already named Rule.
        models.append("---" if model == "deterministic" else model)
        gates.append(r"\textbf{" + gate + "}" if gate != "enforcing" else gate)
    return {"model": models, "gate": gates}


# A pinned snapshot id is the widest cell in the table and it appears three
# times, which is what held the font at \footnotesize with eight arms. The row
# shows the family and the caption carries the snapshot, so nothing is lost and
# the table reads a size larger.
SNAPSHOT = re.compile(r"-\d{4}-\d{2}-\d{2}$")


def abbreviate_models(models: Sequence[str]) -> tuple[list[str], str]:
    """Short names for the row, and the sentence that restores the full ones."""
    shown: list[str] = []
    pinned: dict[str, str] = {}
    for model in models:
        short = SNAPSHOT.sub("", model)
        if short != model:
            pinned[short] = model
        shown.append("---" if model == "---" else escape(short))
    if not pinned:
        return shown, ""
    # The caption does not restore the snapshot: Section 4.4 prints every model
    # id in full, and a table* caption line costs two lines of body text.
    return shown, ""


def render_main(arms: Mapping[str, Mapping[str, Any]], labels: Mapping[str, str],
                caption: str, label: str) -> str:
    names = list(arms)
    header = " & ".join(escape(labels.get(name, name)) for name in names)
    # A six-arm table overflows the text block at \small; the font and the column
    # padding are set here rather than patched in the paper, so a regenerated
    # table never reintroduces the overfull box.
    # The arm configuration used to be a separate table. It is two rows here
    # instead, read from the same summary as the numbers, so the configuration
    # and the results cannot drift apart and the page budget carries one float
    # rather than two.
    config = arm_configuration(arms)
    shown_models, snapshot_note = abbreviate_models(config["model"])
    lines = [r"\begin{table*}[t]", f"\\caption{{{caption}{snapshot_note}}}",
             f"\\label{{{label}}}",
             r"\small", r"\setlength{\tabcolsep}{5pt}",
             # 8pt type in rows 5 per cent tighter reads better than 7pt type
             # in loose ones, and the pair costs one line rather than ten.
             r"\renewcommand{\arraystretch}{0.95}",
             r"\begin{tabular}{@{}l" + "r" * len(names) + r"@{}}",
             r"\toprule", f"Arm & {header} \\\\",
             f"\\quad model & " + " & ".join(shown_models) + r" \\",
             f"\\quad scope gate & " + " & ".join(config["gate"]) + r" \\",
             r"\midrule"]
    for title, cells in metric_rows(arms):
        lines.append(f"{title} & " + " & ".join(cells) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""])
    return "\n".join(lines)


def render_comparisons(comparisons: Mapping[str, Mapping[str, Any]],
                       labels: Mapping[str, str], caption: str, label: str) -> str:
    if not comparisons:
        return ""
    # Every number in this table is also stated in the prose of the main-results
    # subsection, so the submission cites the table and prints it only in the
    # unabridged version, where the page budget does not charge for a repeat.
    lines = [r"\iffull", r"\begin{table}[tb]", f"\\caption{{{caption}}}",
             f"\\label{{{label}}}",
             r"\small", r"\begin{tabular}{@{}lrl@{}}", r"\toprule",
             r"Comparison & Difference & 95\% CI \\", r"\midrule"]
    for name, values in comparisons.items():
        pretty = name
        for key, shown in labels.items():
            pretty = pretty.replace(key, shown)
        low, high = values["ci95"]
        excludes_zero = low > 0 or high < 0
        cell = f"[{low:+.4f}, {high:+.4f}]"
        if excludes_zero:
            cell = r"\textbf{" + cell + "}"
        lines.append(f"{escape(pretty)} & {values['mean_difference']:+.4f} & {cell} \\\\")
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}", r"\fi", ""])
    return "\n".join(lines)


def comparison_caption(comparisons: Mapping[str, Mapping[str, Any]]) -> str:
    """Describe the bootstrap the analyser actually ran, not the one we expect.

    The unit and the sample count are properties of `summary.json`. Writing
    them into a fixed string here is how a caption comes to describe a
    resampling the numbers below it did not come from.
    """
    if not comparisons:
        return ""
    first = next(iter(comparisons.values()))
    samples = first.get("bootstrap_samples")
    units = first.get("resample_units")
    unit = first.get("resample_unit", "request")
    noun = {"paraphrase_group": "paraphrase groups", "request": "requests"}.get(unit, unit)
    count = f"{samples:,}".replace(",", "{,}") if isinstance(samples, int) else "bootstrap"
    # The reason for clustering belongs in the statistics subsection, not in
    # every caption that reports a clustered interval.
    return (f"Paired differences in action accuracy, {count} bootstrap resamples "
            f"over the {units} {noun}. Intervals excluding zero are in bold.")


def parse_labels(values: Sequence[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in values:
        key, _, shown = item.partition("=")
        if not key.strip() or not shown.strip():
            raise argparse.ArgumentTypeError(f"expected ARM=Label, got {item!r}")
        labels[key.strip()] = shown.strip()
    return labels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", required=True, help="summary.json from the analyser")
    parser.add_argument("--out", required=True, help="LaTeX fragment to write")
    parser.add_argument("--label", action="append", default=[], metavar="ARM=Label",
                        help="display name for an arm (repeatable); also fixes the order")
    parser.add_argument("--caption", default="Results on the sealed benchmark.")
    parser.add_argument("--comparison-caption",
                        help="override the caption; by default it is written from the "
                             "summary's own resampling unit and sample count, so it "
                             "cannot describe a bootstrap the analyser did not run")
    parser.add_argument("--tag", default="results",
                        help="suffix for the \\label of each table")
    args = parser.parse_args()

    report = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    try:
        labels = parse_labels(args.label)
    except argparse.ArgumentTypeError as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1
    available = report["arms"]
    order = [name for name in labels if name in available] or list(available)
    missing = sorted(set(labels) - set(available))
    if missing:
        print(json.dumps({"status": "refused", "problems": [
            f"the summary has no arm named: {missing}"]}, indent=2))
        return 1
    arms = {name: available[name] for name in order}

    comparisons = report.get("paired_comparisons") or {}
    caption = args.comparison_caption or comparison_caption(comparisons)
    fragment = render_main(arms, labels, args.caption, f"tab:{args.tag}")
    fragment += "\n" + render_comparisons(comparisons, labels, caption, f"tab:{args.tag}-ci")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("% Generated by scripts/render_results_tables.py. Do not edit.\n"
                   f"% Source: {args.summary}\n" + fragment, encoding="utf-8")
    print(json.dumps({"status": "rendered", "out": str(out), "arms": order,
                      "comparisons": len(report.get("paired_comparisons") or {})}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
