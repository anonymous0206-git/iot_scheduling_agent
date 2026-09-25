#!/usr/bin/env python3
"""Analyse the direct-generation baseline (B2) into a reportable artefact.

Three questions decide what the baseline says about the architecture.

  * Can the model produce a valid schedule at all, and does it need the
    validator in the loop to get there? Reported as validity on the first
    attempt and after validator feedback.
  * When it succeeds, is the schedule any good? Reported as the latency of each
    valid direct schedule against the latency the solver achieved on the same
    request, which is the number that decides whether the solver is replaceable.
  * When it fails, how badly? A schedule missing two constraints out of two
    hundred transmissions fails exactly as completely as one missing fifty, and
    nothing in the output distinguishes them --- which is the argument for an
    independent validator.

A request whose attempts never reached the validator is excluded from every rate
and counted separately. Those are provider refusals, not model failures, and
counting them would measure our infrastructure rather than the baseline.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def load(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in
            Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def reached_validator(record: dict[str, Any]) -> bool:
    return any(a.get("stage") == "validated" for a in record.get("attempts", ()))


def analyse(rows: list[dict[str, Any]], agent: dict[str, dict[str, Any]]) -> dict[str, Any]:
    usable = [r for r in rows if reached_validator(r)]
    excluded = [r["request_id"] for r in rows if not reached_validator(r)]

    valid = [r for r in usable if r["valid"]]
    first_try = [r for r in usable if r["attempts"] and r["attempts"][0].get("valid")]
    rescued = [r for r in valid if r not in first_try]

    codes: Counter = Counter()
    violation_counts: list[int] = []
    exact_transmissions = comparable = 0
    for record in usable:
        final = record["attempts"][-1]
        if final.get("transmissions") is not None:
            comparable += 1
            exact_transmissions += int(
                final["transmissions"] == record["expected_transmissions"])
        if record["valid"]:
            continue
        for code in final.get("violation_codes") or []:
            codes[code] += 1
        if final.get("violation_count") is not None:
            violation_counts.append(final["violation_count"])

    latency: list[dict[str, Any]] = []
    for record in sorted(valid, key=lambda r: r["request_id"]):
        metrics = (agent.get(record["request_id"]) or {}).get("schedule_metrics") or {}
        solver = metrics.get("latency_slots")
        direct = record.get("latency_slots")
        if solver and direct:
            latency.append({"request_id": record["request_id"],
                            "nodes": record["expected_transmissions"] + 1,
                            "direct_latency_slots": direct,
                            "solver_latency_slots": solver,
                            "penalty": round(direct / solver, 2)})

    by_size: dict[int, dict[str, int]] = {}
    for record in usable:
        size = record["expected_transmissions"] + 1
        entry = by_size.setdefault(size, {"items": 0, "valid": 0, "first_try": 0})
        entry["items"] += 1
        entry["valid"] += int(record["valid"])
        entry["first_try"] += int(bool(record["attempts"]
                                       and record["attempts"][0].get("valid")))

    penalties = [row["penalty"] for row in latency]
    attempts_made = sum(len(r["attempts"]) for r in usable)
    tokens = sum(a.get("completion_tokens") or 0 for r in usable for a in r["attempts"])
    wall = [r["wall_time_seconds"] for r in usable]

    return {
        "items_run": len(rows),
        "items_usable": len(usable),
        "excluded_provider_refusals": excluded,
        "validity": {
            "valid": len(valid), "items": len(usable),
            "rate": round(len(valid) / len(usable), 4) if usable else 0.0,
            "valid_on_first_attempt": len(first_try),
            "first_attempt_rate": round(len(first_try) / len(usable), 4) if usable else 0.0,
            "valid_only_after_validator_feedback": len(rescued),
        },
        "failures": {
            "violation_codes": dict(codes.most_common()),
            "violations_on_final_attempt": {
                "median": statistics.median(violation_counts) if violation_counts else None,
                "min": min(violation_counts) if violation_counts else None,
                "max": max(violation_counts) if violation_counts else None,
            },
            "produced_exactly_the_expected_transmission_count":
                f"{exact_transmissions}/{comparable}",
        },
        "latency_against_the_solver": {
            "compared": len(latency),
            "mean_penalty": round(statistics.fmean(penalties), 2) if penalties else None,
            "median_penalty": round(statistics.median(penalties), 2) if penalties else None,
            "worst_penalty": max(penalties) if penalties else None,
            "per_request": latency,
        },
        "by_network_size": {str(k): by_size[k] for k in sorted(by_size)},
        "cost": {
            "attempts": attempts_made,
            "completion_tokens": tokens,
            "mean_wall_seconds": round(statistics.fmean(wall), 1) if wall else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", required=True, help="the B2 ledger")
    parser.add_argument("--agent-ledger", required=True,
                        help="the agent ledger to compare latency against")
    parser.add_argument("--out", help="write the report here (write-once)")
    args = parser.parse_args()

    rows = load(args.ledger)
    agent = {r["request_id"]: r for r in load(args.agent_ledger)}
    report = {
        "analysis_format": "agentic_anex.direct_generation.v1",
        "ledger": str(args.ledger),
        "agent_ledger": str(args.agent_ledger),
        "no_language_model_invoked": True,
        **analyse(rows, agent),
    }
    if args.out:
        out = Path(args.out)
        if out.exists():
            print(json.dumps({"status": "refused", "problems": [
                f"refusing to overwrite: {out}"]}, indent=2))
            return 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items()
                      if k != "latency_against_the_solver"}, indent=2, sort_keys=True))
    latency = report["latency_against_the_solver"]
    print(json.dumps({k: v for k, v in latency.items() if k != "per_request"},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
