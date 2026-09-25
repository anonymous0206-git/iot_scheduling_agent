#!/usr/bin/env python3
"""Ledger tables that answer questions the summary metrics cannot.

`analyze_frozen_test_results.py` reports what each arm scored. Three reviewer
questions need the item behind the score instead:

  which stage decided this?   An arm's action accuracy does not say whether a
                              request was decided by a deterministic stage
                              before the model ran or by the model itself, so
                              an answer-only ledger reports a scaffolding
                              failure as a model failure.
  which items were accepted?  A false-acceptance count says two arms differ by
                              one; it does not say the two sets overlap in one
                              item and each holds one the other does not.
  what did the gate cost?     A gated/ungated accuracy difference is a net. It
                              hides how many items moved each way and whether
                              the gate or the model moved them.

This script reads ledgers and the harness and writes those three tables plus
the per-batch split. It opens no model, scheduler or validator, so its output
can be regenerated from the archived ledgers at any time.

Stage attribution reads the ledger rather than re-running the pipeline:

  scope_gate       the record carries a scope policy report that refused it
  parameter_check  no model call, and an INVALID_* error code
  topology_gate    no model call, and MISSING_TOPOLOGY
  baseline_filter  an arm with no model behind it refused it under its own
                   error code, which is not the shared scope gate. The arm is
                   identified by the ledger's `system`, not by the absence of
                   a scope report: the baseline runs the shared gate too, so
                   it carries a passing scope report on everything the gate
                   let through.
  model            the model was called
  none             the run completed without a deterministic termination

A record that fits none of these is reported under `unclassified` rather than
forced into a bucket: a silent misattribution is the failure this table exists
to prevent.

    audit_ledger_tables.py --harness H --ledger NAME=PATH [--pair GATED=UNGATED]
                           --output-dir results/frozen_test_v3/audit
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

ACTIONS: tuple[str, ...] = ("EXECUTE", "CLARIFY", "REJECT", "UNSUPPORTED")
STAGES: tuple[str, ...] = ("scope_gate", "parameter_check", "topology_gate",
                           "baseline_filter", "model", "none", "unclassified")
DETERMINISTIC_STAGES = ("scope_gate", "parameter_check", "topology_gate")
# Above this many items a false-acceptance set is summarised rather than listed.
_INLINE_LIMIT = 12


class AuditError(ValueError):
    """The ledgers and the harness cannot be audited together."""


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise AuditError(f"{path}:{number} is not JSON: {exc}") from exc
    if not records:
        raise AuditError(f"{path} holds no records")
    return records


MODEL_SYSTEMS = ("llm_agent",)


def terminating_stage(record: Mapping[str, Any]) -> str:
    """Name the stage that decided this request, or say it cannot be named."""
    scope = record.get("scope_policy") or {}
    if scope.get("supported") is False:
        return "scope_gate"
    code = record.get("error_code")
    called_model = (record.get("model_calls") or 0) > 0
    if not called_model:
        if isinstance(code, str) and code.startswith("INVALID_"):
            return "parameter_check"
        if code == "MISSING_TOPOLOGY":
            return "topology_gate"
        if code is not None:
            # An arm with no model behind it, refusing under its own rules. An
            # arm that has a model and did not call it, refusing under a code
            # no deterministic stage raises, is something we cannot name.
            system = str(record.get("system") or "")
            has_model = system.startswith(MODEL_SYSTEMS)
            return "unclassified" if has_model else "baseline_filter"
        return "none"
    return "model"


def _certified(record: Mapping[str, Any]) -> bool:
    validation = record.get("validation") or {}
    return bool(validation.get("valid")) and not validation.get("violations")


def stage_termination(name: str, records: Sequence[Mapping[str, Any]],
                      harness: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Per stage, how many requests it decided, split by gold action."""
    by_stage: dict[str, dict[str, Any]] = {
        stage: {"items": 0, "correct": 0, "by_gold_action": dict.fromkeys(ACTIONS, 0),
                "request_ids": []} for stage in STAGES}
    for record in records:
        item = harness[record["request_id"]]
        stage = by_stage[terminating_stage(record)]
        stage["items"] += 1
        stage["correct"] += int(record["action"] == item["gold_action"])
        stage["by_gold_action"][item["gold_action"]] += 1
        stage["request_ids"].append(record["request_id"])
    for stage in by_stage.values():
        stage["request_ids"].sort()
        stage["errors"] = stage["items"] - stage["correct"]
    decided = sum(by_stage[stage]["items"] for stage in DETERMINISTIC_STAGES)
    forced = sum(by_stage[stage]["errors"] for stage in DETERMINISTIC_STAGES)
    total_errors = sum(1 for r in records if r["action"] != harness[r["request_id"]]["gold_action"])
    return {
        "arm": name,
        "items": len(records),
        "decided_before_the_model": decided,
        "errors_total": total_errors,
        "errors_forced_by_a_deterministic_stage": forced,
        "errors_chosen_by_the_model": total_errors - forced,
        "by_stage": by_stage,
    }


def false_acceptance(name: str, records: Sequence[Mapping[str, Any]],
                     harness: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Every item the arm executed that it should not have, with its identity."""
    accepted = []
    for record in sorted(records, key=lambda r: r["request_id"]):
        item = harness[record["request_id"]]
        wrong_action = record["action"] == "EXECUTE" and item["gold_action"] != "EXECUTE"
        uncertified = record["action"] == "EXECUTE" and not _certified(record)
        if not (wrong_action or uncertified):
            continue
        accepted.append({
            "request_id": record["request_id"],
            "gold_action": item["gold_action"],
            "category": item.get("category"),
            "paraphrase_group_id": item.get("paraphrase_group_id"),
            "batch_id": item.get("batch_id"),
            "reason": "executed a request whose gold action is not EXECUTE" if wrong_action
                      else "executed without a validator certificate",
        })
    return {"arm": name, "count": len(accepted),
            "by_category": dict(Counter(a["category"] for a in accepted)),
            "items": accepted}


def per_batch(name: str, records: Sequence[Mapping[str, Any]],
              harness: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "items": 0})
    for record in records:
        item = harness[record["request_id"]]
        batch = counts[str(item.get("batch_id"))]
        batch["items"] += 1
        batch["correct"] += int(record["action"] == item["gold_action"])
    batches = {key: dict(value) for key, value in sorted(counts.items())}
    correct = [value["correct"] for value in batches.values()]
    return {"arm": name, "by_batch": batches,
            "widest_gap": max(correct) - min(correct) if correct else 0}


def gate_transition(gated_name: str, gated: Sequence[Mapping[str, Any]],
                    ungated_name: str, ungated: Sequence[Mapping[str, Any]],
                    harness: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Item by item, what removing the scope gate changed and what moved it.

    The net accuracy difference between the two arms is the sum of two
    quantities the net hides: items the gate was holding, and items the model
    answered differently once it saw them. `gated_answer_from` separates them,
    and it names the *source of the gated arm's answer* rather than the cause
    of the change, because the two read oppositely in the two directions:

      wrong_to_right, gate   the gate was holding this item wrong and removing
                             it recovered the item — a cost of the gate
      wrong_to_right, model  the gate let this item through in both arms and
                             the model simply answered differently
      right_to_wrong, gate   the gate was carrying this item correctly and the
                             model cannot — a benefit of the gate
      right_to_wrong, model  neither arm gated it; the model regressed

    Reading `gate` as blame in both directions inverts the meaning of half the
    table, so the summary counts the two directions separately.
    """
    left = {record["request_id"]: record for record in gated}
    right = {record["request_id"]: record for record in ungated}
    shared = sorted(set(left) & set(right))
    if not shared:
        raise AuditError(f"{gated_name} and {ungated_name} share no request")
    moves = []
    for request_id in shared:
        item = harness[request_id]
        before, after = left[request_id], right[request_id]
        was_right = before["action"] == item["gold_action"]
        now_right = after["action"] == item["gold_action"]
        if was_right == now_right:
            continue
        moves.append({
            "request_id": request_id,
            "gold_action": item["gold_action"],
            "category": item.get("category"),
            "gated_action": before["action"],
            "ungated_action": after["action"],
            "direction": "wrong_to_right" if now_right else "right_to_wrong",
            "gated_answer_from": "gate" if terminating_stage(before) == "scope_gate" else "model",
        })
    recovered = [m for m in moves if m["direction"] == "wrong_to_right"]
    regressed = [m for m in moves if m["direction"] == "right_to_wrong"]
    return {
        "gated": gated_name, "ungated": ungated_name, "pairs": len(shared),
        "wrong_to_right": len(recovered), "right_to_wrong": len(regressed),
        "net": len(recovered) - len(regressed),
        "recovered_from_a_gate_over_block":
            sum(1 for m in recovered if m["gated_answer_from"] == "gate"),
        "recovered_by_the_model_changing_its_answer":
            sum(1 for m in recovered if m["gated_answer_from"] == "model"),
        "correct_refusals_the_gate_was_carrying":
            sum(1 for m in regressed if m["gated_answer_from"] == "gate"),
        "regressions_the_model_owns":
            sum(1 for m in regressed if m["gated_answer_from"] == "model"),
        "moves": moves,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    arms = report["stage_termination"]
    lines = ["# Ledger audit tables", "",
             f"Harness: `{report['harness']['path']}` ({report['harness']['items']} items)",
             "", "## Which stage decided the request", "",
             "| Arm | " + " | ".join(STAGES) + " | decided pre-model | errors forced / total |",
             "|---|" + "---:|" * (len(STAGES) + 2)]
    for name, arm in arms.items():
        cells = [str(arm["by_stage"][stage]["items"]) for stage in STAGES]
        lines.append(f"| {name} | " + " | ".join(cells) +
                     f" | {arm['decided_before_the_model']} |"
                     f" {arm['errors_forced_by_a_deterministic_stage']}"
                     f" / {arm['errors_total']} |")
    lines.extend(["", "`decided pre-model` counts the three stages every gated arm shares;",
                  "an arm with no model behind it refuses under `baseline_filter`, which is a",
                  "different implementation and is not part of that count. That arm also",
                  "shows `topology_gate` 0 and asks for clarification from its own parser",
                  "instead, so its clarifications fall under `none`; the orchestrator's",
                  "topology gate is a stage of the agent pipeline, not of the baseline.",
                  "", "## False acceptance, by item", "",
                  "Item identities matter here because two arms can differ by one in count",
                  "while differing by more than one in membership. Sets longer than",
                  f"{_INLINE_LIMIT} items are in `false_acceptance.json` rather than inline.", ""])
    for name, arm in report["false_acceptance"].items():
        if arm["count"] > _INLINE_LIMIT:
            top = ", ".join(f"{category} ({count})" for category, count
                            in sorted(arm["by_category"].items(), key=lambda kv: (-kv[1], kv[0]))[:5])
            lines.append(f"* **{name}** — {arm['count']}, over "
                         f"{len(arm['by_category'])} categories; most frequent: {top}")
            continue
        listed = ", ".join(f"`{a['request_id']}` ({a['category']})" for a in arm["items"])
        lines.append(f"* **{name}** — {arm['count']}: {listed or 'none'}")
    lines.extend(["", "## Per batch", "",
                  "| Arm | " + " | ".join(sorted(
                      {b for a in report["per_batch"].values() for b in a["by_batch"]}))
                  + " | widest gap |"])
    batches = sorted({b for a in report["per_batch"].values() for b in a["by_batch"]})
    lines.append("|---|" + "---:|" * (len(batches) + 1))
    for name, arm in report["per_batch"].items():
        cells = [f"{arm['by_batch'][b]['correct']}/{arm['by_batch'][b]['items']}"
                 if b in arm["by_batch"] else "-" for b in batches]
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {arm['widest_gap']} |")
    if report.get("gate_transitions"):
        lines.extend(["", "## What removing the scope gate changed", "",
                      "Recovered over-blocks are a cost the gate was imposing; lost refusals",
                      "are work the gate was doing that the model cannot do for itself.",
                      "Both columns are keyed on where the *gated* arm's answer came from.", "",
                      "| Pair | recovered over-blocks | other recoveries | correct refusals lost"
                      " | model regressions | net |",
                      "|---|---:|---:|---:|---:|---:|"])
        for label, pair in report["gate_transitions"].items():
            lines.append(f"| {label} | {pair['recovered_from_a_gate_over_block']} | "
                         f"{pair['recovered_by_the_model_changing_its_answer']} | "
                         f"{pair['correct_refusals_the_gate_was_carrying']} | "
                         f"{pair['regressions_the_model_owns']} | {pair['net']:+d} |")
        for label, pair in report["gate_transitions"].items():
            lines.extend(["", f"### {label}", "",
                          "| Request | Gold | Gated | Ungated | Direction | Gated answer from |",
                          "|---|---|---|---|---|---|"])
            for move in pair["moves"]:
                lines.append(f"| `{move['request_id']}` | {move['gold_action']} | "
                             f"{move['gated_action']} | {move['ungated_action']} | "
                             f"{move['direction'].replace('_', ' ')} | "
                             f"{move['gated_answer_from']} |")
    lines.append("")
    return "\n".join(lines)


def _parse_named(spec: str) -> tuple[str, str]:
    name, separator, value = spec.partition("=")
    if not separator or not name.strip() or not value.strip():
        raise argparse.ArgumentTypeError("expected NAME=VALUE")
    return name.strip(), value.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--harness", required=True, help="evaluator-side harness JSONL")
    parser.add_argument("--ledger", action="append", required=True, type=_parse_named,
                        metavar="NAME=PATH", help="ledger to audit (repeatable)")
    parser.add_argument("--pair", action="append", default=[], type=_parse_named,
                        metavar="GATED=UNGATED",
                        help="two arm names to compare item by item (repeatable)")
    parser.add_argument("--output-dir", help="write the tables here (write-once)")
    args = parser.parse_args()

    try:
        harness_items = load_jsonl(args.harness)
        harness = {item["request_id"]: item for item in harness_items}
        ledgers = {name: load_jsonl(path) for name, path in args.ledger}
        for name, records in ledgers.items():
            unknown = sorted({r["request_id"] for r in records} - set(harness))
            if unknown:
                raise AuditError(f"{name} holds request ids absent from the harness: "
                                 f"{', '.join(unknown[:5])}")
        pairs = {}
        for gated, ungated in args.pair:
            if gated not in ledgers or ungated not in ledgers:
                raise AuditError(f"--pair {gated}={ungated} names an arm that was not given "
                                 f"as --ledger")
            pairs[f"{gated} minus {ungated}"] = gate_transition(
                gated, ledgers[gated], ungated, ledgers[ungated], harness)
    except AuditError as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1

    report = {
        "audit_format": "agentic_anex.ledger_audit.v1",
        "harness": {"path": str(args.harness), "items": len(harness_items)},
        "ledgers": {name: path for name, path in args.ledger},
        "no_language_model_or_scheduler_invoked": True,
        "stage_termination": {name: stage_termination(name, records, harness)
                              for name, records in ledgers.items()},
        "false_acceptance": {name: false_acceptance(name, records, harness)
                             for name, records in ledgers.items()},
        "per_batch": {name: per_batch(name, records, harness)
                      for name, records in ledgers.items()},
        "gate_transitions": pairs,
    }
    unclassified = {name: arm["by_stage"]["unclassified"]["request_ids"]
                    for name, arm in report["stage_termination"].items()
                    if arm["by_stage"]["unclassified"]["items"]}
    if unclassified:
        report["unclassified"] = unclassified

    if not args.output_dir:
        print(render_markdown(report))
        return 0
    directory = Path(args.output_dir)
    files = {
        "stage_termination.json": report["stage_termination"],
        "false_acceptance.json": report["false_acceptance"],
        "per_batch.json": report["per_batch"],
        "gate_transitions.json": report["gate_transitions"],
    }
    payloads = {name: json.dumps(body, indent=2, sort_keys=True) + "\n"
                for name, body in files.items()}
    payloads["audit.md"] = render_markdown(report)
    payloads["audit.json"] = json.dumps(report, indent=2, sort_keys=True) + "\n"
    existing = [name for name in payloads if (directory / name).exists()]
    if existing:
        print(json.dumps({"status": "refused", "problems": [
            f"refusing to overwrite {directory / name}" for name in existing]}, indent=2))
        return 1
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in payloads.items():
        with open(directory / name, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    print(json.dumps({"status": "audited", "output_dir": str(directory),
                      "arms": sorted(ledgers), "pairs": sorted(pairs),
                      "unclassified": unclassified}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
