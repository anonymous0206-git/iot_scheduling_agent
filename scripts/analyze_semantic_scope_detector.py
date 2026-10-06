#!/usr/bin/env python3
"""Compare the shipped regex scope gate with a semantic detector, detector to detector.

Figure 3 splits the 72 gold-``UNSUPPORTED`` requests by whether they name the
capability they ask for, and shows that the regex gate's recall follows the
phrasing while the ungated agent's does not. The question this answers is
whether that is a property of *that regex* or of gating on surface form: the
semantic detector of ``run_semantic_scope_detector.py`` is aimed at the same
closed taxonomy and asked the same question, and its recall is reported on the
same two groups.

Over-blocking is the other half, and it is the half a better detector need not
improve. The gate's seven over-blocks are gold-``EXECUTE`` requests that mention
an out-of-scope concept while asking for something supported. A detector that
reads meaning can over-block them for a better reason than a keyword match, so
the count is reported beside the recall rather than assumed to fall.

No model is invoked here, and no action is scored: both detectors' verdicts are
already in the ledgers, next to each other per request.

    scripts/analyze_semantic_scope_detector.py \
        --ledger-dir results/frozen_test_v3/semantic_scope \
        --harness benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl \
        --phrasing paper/aamas2027/figure_data/fig2_phrasing.json \
        --out results/frozen_test_v3/semantic_scope
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

NAMES = "names the capability"
COMPOSES = "composes it from ordinary words"


def _under_root(path: Path) -> str:
    """Repository-relative where possible; a test may read from a temp tree."""
    return (path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT)
            else str(path))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def mean_range(values: list[float]) -> dict[str, Any]:
    return {"mean": round(statistics.fmean(values), 4) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "per_seed": values}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger-dir", required=True)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--phrasing", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    def resolve(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else ROOT / path

    ledger_dir = resolve(args.ledger_dir)
    ledgers = sorted(ledger_dir.glob("semantic_scope_seed*.jsonl"))
    if not ledgers:
        print(json.dumps({"status": "refused", "problems": [
            f"no semantic_scope_seed*.jsonl in {args.ledger_dir}"]}, indent=2))
        return 1

    harness = {item["request_id"]: item for item in load_jsonl(resolve(args.harness))}
    phrasing = json.loads(resolve(args.phrasing).read_text(encoding="utf-8"))
    groups = {key: set(ids) for key, ids in phrasing["request_ids"].items()}
    if set(groups) != {NAMES, COMPOSES}:
        print(json.dumps({"status": "refused", "problems": [
            f"unexpected phrasing groups: {sorted(groups)}"]}, indent=2))
        return 1

    unsupported = {rid for rid, item in harness.items()
                   if item["gold_action"] == "UNSUPPORTED"}
    executable = {rid for rid, item in harness.items()
                  if item["gold_action"] == "EXECUTE"}
    other_in_scope = {rid for rid, item in harness.items()
                      if item["gold_action"] in ("REJECT", "CLARIFY")}
    for key, ids in groups.items():
        stray = sorted(ids - unsupported)
        if stray:
            print(json.dumps({"status": "refused", "problems": [
                f"phrasing group {key!r} names requests that are not "
                f"gold-UNSUPPORTED: {stray}"]}, indent=2))
            return 1

    per_seed: list[dict[str, Any]] = []
    disagreements: dict[str, dict[str, Any]] = {}
    regex_flagged: set[str] | None = None
    for path in ledgers:
        records = load_jsonl(path)
        missing = [r["request_id"] for r in records if "semantic_in_scope" not in r]
        flagged_semantic = {r["request_id"] for r in records
                            if r.get("semantic_in_scope") is False}
        flagged_regex = {r["request_id"] for r in records if r["regex_in_scope"] is False}
        # The regex is deterministic: a drift between seeds would mean the
        # ledgers were not produced from the same texts.
        if regex_flagged is None:
            regex_flagged = flagged_regex
        elif flagged_regex != regex_flagged:
            print(json.dumps({"status": "refused", "problems": [
                "the regex verdict differs between ledgers, which it cannot do "
                "on the same requests"]}, indent=2))
            return 1
        for record in records:
            if record.get("semantic_in_scope") is None:
                continue
            rid = record["request_id"]
            semantic_out = record["semantic_in_scope"] is False
            regex_out = record["regex_in_scope"] is False
            if semantic_out != regex_out:
                entry = disagreements.setdefault(rid, {
                    "gold_action": record["gold_action"],
                    "category": record.get("category"),
                    "group": (NAMES if rid in groups[NAMES]
                              else COMPOSES if rid in groups[COMPOSES] else None),
                    "regex": "out of scope" if regex_out else "in scope",
                    "semantic_out_of_scope_in_seeds": [],
                    "evidence": record.get("semantic_evidence"),
                })
                if semantic_out:
                    entry["semantic_out_of_scope_in_seeds"].append(record["seed"])
                else:
                    entry.setdefault("semantic_in_scope_in_seeds", []).append(record["seed"])
        per_seed.append({
            "seed": records[0]["seed"] if records else None,
            "ledger": path.name,
            "unanswered_requests": missing,
            "recall_names": len(flagged_semantic & groups[NAMES]),
            "recall_composes": len(flagged_semantic & groups[COMPOSES]),
            "recall_unsupported": len(flagged_semantic & unsupported),
            "over_blocked_execute": len(flagged_semantic & executable),
            "flagged_reject_or_clarify": len(flagged_semantic & other_in_scope),
            "flagged_total": len(flagged_semantic),
        })

    assert regex_flagged is not None
    regex_row = {
        "recall_names": len(regex_flagged & groups[NAMES]),
        "recall_composes": len(regex_flagged & groups[COMPOSES]),
        "recall_unsupported": len(regex_flagged & unsupported),
        "over_blocked_execute": len(regex_flagged & executable),
        "flagged_reject_or_clarify": len(regex_flagged & other_in_scope),
        "flagged_total": len(regex_flagged),
    }
    agent = phrasing["series"]
    summary = {
        "analysis_format": "agentic_anex.semantic_scope_comparison.v1",
        "no_language_model_invoked": True,
        "question": "whether the gate's dependence on the capability's vocabulary "
                    "is a property of the shipped regex or of gating on surface "
                    "form; measured detector to detector, with no pipeline arm",
        "ledgers": [_under_root(path) for path in ledgers],
        "detector_version": load_jsonl(ledgers[0])[0]["detector_version"],
        "repeats": len(ledgers),
        "groups": {NAMES: len(groups[NAMES]), COMPOSES: len(groups[COMPOSES])},
        "denominators": {"gold_unsupported": len(unsupported),
                         "gold_execute": len(executable),
                         "gold_reject_or_clarify": len(other_in_scope)},
        "regex_gate": regex_row,
        "semantic_detector": {
            key: mean_range([float(row[key]) for row in per_seed])
            for key in ("recall_names", "recall_composes", "recall_unsupported",
                        "over_blocked_execute", "flagged_reject_or_clarify",
                        "flagged_total")
        },
        "semantic_detector_per_seed": per_seed,
        "ungated_frontier_agent_from_figure_3": {
            "recall_names": agent[NAMES]["caught by the ungated agent"],
            "recall_composes": agent[COMPOSES]["caught by the ungated agent"],
        },
        "requests_the_two_detectors_decide_differently": dict(sorted(disagreements.items())),
    }

    out_dir = resolve(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    sem = summary["semantic_detector"]
    lines = [
        "# Regex scope gate against a semantic detector",
        "",
        f"Detector: {summary['detector_version']}, {summary['repeats']} repeats. "
        "No pipeline arm; both verdicts come from the same ledgers.",
        "",
        "| Detector | names the capability (of "
        f"{summary['groups'][NAMES]}) | composes it (of {summary['groups'][COMPOSES]}) "
        f"| over-blocked gold-EXECUTE (of {summary['denominators']['gold_execute']}) |",
        "| --- | --- | --- | --- |",
        f"| regex gate (shipped) | {regex_row['recall_names']} | "
        f"{regex_row['recall_composes']} | {regex_row['over_blocked_execute']} |",
        f"| semantic detector | {sem['recall_names']['mean']} | "
        f"{sem['recall_composes']['mean']} | {sem['over_blocked_execute']['mean']} |",
        f"| ungated frontier agent (Figure 3) | "
        f"{summary['ungated_frontier_agent_from_figure_3']['recall_names']} | "
        f"{summary['ungated_frontier_agent_from_figure_3']['recall_composes']} | n/a |",
        "",
        f"Requests the two detectors decide differently: "
        f"{len(summary['requests_the_two_detectors_decide_differently'])}.",
    ]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": "analysed",
        "out": _under_root(out_dir),
        "regex_gate": regex_row,
        "semantic_detector": {k: v["mean"] for k, v in sem.items()},
        "ungated_agent": summary["ungated_frontier_agent_from_figure_3"],
        "disagreements": len(summary["requests_the_two_detectors_decide_differently"]),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
