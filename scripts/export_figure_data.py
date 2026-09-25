#!/usr/bin/env python3
"""Export the data series each figure needs, so no figure is drawn from prose.

A figure redrawn from a number quoted in the text is a figure that can disagree
with the artefact. This script writes one JSON file per figure, each carrying
the series to plot, the files it was computed from, and a statement of what the
figure is supposed to show. A plotting script, or a person drawing by hand,
reads only these files.

Three figures:

  fig1_pipeline   how many requests each deterministic stage terminated, and
                  how many reached the model, per arm.
  fig2_phrasing   the scope gate's recall and the ungated agent's recall on
                  unsupported requests, split by whether the request names the
                  out-of-scope capability or composes it from ordinary words.
  fig3_ablation   what removing the scope gate gains and loses, per gold
                  action, for the weakest and the strongest agent.

On the phrasing split in fig2: the classifier below is ours, not the gate's. It
asks whether a request contains the vocabulary of the capability it is asking
for --- "digital twin", "battery", "periodic", "throughput" and so on --- and is
written from the capability taxonomy, not from the gate's regular expressions.
The two are therefore independent tests of the same requests, which is what
makes the comparison meaningful: the gate's own patterns are proximity windows
intended to catch a capability expressed without its name, so a gate that fires
only where the vocabulary appears has not been let down by a lack of trying.
The limitation to state with the figure is that "contains the vocabulary" is a
coarse proxy for "names the capability", and the item lists are exported so the
split can be audited.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

ACTIONS = ("EXECUTE", "CLARIFY", "REJECT", "UNSUPPORTED")

# Vocabulary of each out-of-scope capability, written from the taxonomy.
CAPABILITY_VOCABULARY = {
    "digital_twin_or_emulation": (r"digital\s+twin", r"emulat", r"virtual\s+replica"),
    "dynamic_state_synchronization": (r"synchroni[sz]", r"mirror", r"telemetry",
                                      r"real[- ]?time"),
    "energy_aware_scheduling": (r"energy", r"battery", r"power", r"charge"),
    "residual_battery_evolution": (r"residual", r"depletion", r"battery\s+level"),
    "periodic_or_continuous_aggregation": (r"periodic", r"continuous", r"recurring",
                                           r"repeat", r"ongoing"),
    "topology_adaptation": (r"adapt", r"reconfigur", r"re-?rout", r"rejoin", r"departure"),
    "unsupported_optimization_objective": (r"throughput", r"fairness", r"lifetime",
                                           r"reliability", r"coverage", r"hop\s+count"),
}
VOCABULARY = tuple(re.compile(pattern, re.IGNORECASE)
                   for group in CAPABILITY_VOCABULARY.values() for pattern in group)


def load(path: str | Path) -> dict[str, dict[str, Any]]:
    return {record["request_id"]: record for record in
            (json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
             if line.strip())}


def names_its_capability(text: str) -> bool:
    """Does the request use the vocabulary of the capability it asks for?"""
    return any(pattern.search(text) for pattern in VOCABULARY)


def gate_blocked(record: Mapping[str, Any]) -> bool:
    return (record.get("scope_policy") or {}).get("supported") is False


def reached_the_model(record: Mapping[str, Any]) -> bool:
    """Was the model consulted at all?

    Error code alone cannot answer this: a code such as INVALID_CHANNEL_COUNT is
    raised both by the deterministic parameter check on the raw text and by the
    typed request the model returned. Whether a model call was made is exact.
    """
    return bool(record.get("model_calls")) or bool(record.get("llm_logs"))


def fig1_pipeline(harness, arms) -> dict[str, Any]:
    """Where requests stop, per arm."""
    series = {}
    for name, ledger in arms.items():
        stages = {"scope gate": 0, "explicit-parameter check": 0,
                  "topology gate": 0, "reached the model": 0}
        for rid, record in ledger.items():
            if reached_the_model(record):
                stages["reached the model"] += 1
            elif gate_blocked(record):
                stages["scope gate"] += 1
            elif record.get("error_code") == "MISSING_TOPOLOGY":
                stages["topology gate"] += 1
            else:
                stages["explicit-parameter check"] += 1
        series[name] = stages
    return {
        "shows": "how many of the 144 requests each deterministic stage terminated "
                 "before the model was consulted, and that the counts are identical "
                 "across every gated arm",
        "items": len(harness),
        "series": series,
    }


def fig2_phrasing(harness, gated, ungated_repeats) -> dict[str, Any]:
    """Recall on unsupported requests, split by whether the request names the
    capability it asks for.

    The gate is a fixed set of regular expressions over the raw text, so its
    recall is the same in every repeat and one ledger settles it. The agent
    decodes at temperature 1, so its bars are the mean over the arm's repeats
    rather than whichever run happened to be exported --- a single run put the
    total at 70 of 72 where the three-repeat mean is 70.7, and a figure and a
    table disagreeing by seven tenths of an item is a discrepancy a reader has
    to chase.
    """
    if isinstance(ungated_repeats, Mapping):
        ungated_repeats = [ungated_repeats]
    unsupported = sorted(r for r in harness if harness[r]["gold_action"] == "UNSUPPORTED")
    named = [r for r in unsupported if names_its_capability(harness[r]["user_text"])]
    composed = [r for r in unsupported if r not in set(named)]

    def caught_by_gate(ids):
        return sum(gate_blocked(gated[r]) for r in ids)

    def caught_by_model(ids):
        per_repeat = [sum(led[r]["action"] == "UNSUPPORTED" for r in ids if r in led)
                      for led in ungated_repeats]
        return round(statistics.fmean(per_repeat), 2) if per_repeat else 0

    return {
        "shows": "the scope gate needs the capability's vocabulary and the agent "
                 "does not: the gate's recall collapses on requests that express an "
                 "out-of-scope capability without naming it, while the ungated agent's "
                 "does not",
        "classifier": "vocabulary of the capability taxonomy, independent of the "
                      "gate's own proximity patterns",
        "gate_repeats": 1,
        "agent_repeats": len(ungated_repeats),
        "series": {
            "names the capability": {
                "items": len(named),
                "caught by the scope gate": caught_by_gate(named),
                "caught by the ungated agent": caught_by_model(named),
            },
            "composes it from ordinary words": {
                "items": len(composed),
                "caught by the scope gate": caught_by_gate(composed),
                "caught by the ungated agent": caught_by_model(composed),
            },
        },
        "request_ids": {"names the capability": named,
                        "composes it from ordinary words": composed},
    }


def fig3_ablation(harness, pairs) -> dict[str, Any]:
    series = {}
    for label, (gated, ungated) in pairs.items():
        per_action = {}
        for action in ACTIONS:
            ids = [r for r in harness if harness[r]["gold_action"] == action]
            before = sum(gated[r]["action"] == action for r in ids)
            after = sum(ungated[r]["action"] == action for r in ids)
            per_action[action] = {"items": len(ids), "with the gate": before,
                                  "without the gate": after, "change": after - before}
        total_before = sum(gated[r]["action"] == gated[r]["gold_action"] for r in gated)
        total_after = sum(ungated[r]["action"] == ungated[r]["gold_action"] for r in ungated)
        series[label] = {"per_gold_action": per_action,
                         "total": {"with the gate": total_before,
                                   "without the gate": total_after,
                                   "change": total_after - total_before}}
    return {
        "shows": "removing the scope gate is close to even for the weak agent and a "
                 "gain on every action for the strong one, which is the sign change "
                 "the paper reports",
        "series": series,
    }


def fig4_direct(direct: Mapping[str, Any]) -> dict[str, Any]:
    """Every certified direct-generation schedule against the solver's.

    The interesting quantity is the ratio, not the two spans: a reader cannot
    see from "637 slots" whether that is bad without knowing the solver needed
    29. The ratio is also why the figure is drawn on a log axis --- it spans
    from 1.4 to 789, and a linear axis would show one point and a floor.
    """
    per = direct["latency_against_the_solver"]["per_request"]
    return {
        "computed_from": {"analysis": direct.get("ledger")},
        "shows": "the span of every certified direct schedule against the "
                 "solver's on the same request, by network size",
        "validity": direct["validity"],
        "points": sorted(
            ({"request_id": r["request_id"], "nodes": r["nodes"],
              "solver_slots": r["solver_latency_slots"],
              "direct_slots": r["direct_latency_slots"],
              "penalty": r["penalty"]} for r in per),
            key=lambda r: (r["nodes"], r["penalty"])),
    }


def fig5_scaling(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """The deterministic core over the topology-channel sweep.

    This is the one claim in the paper supported by a thousand runs and shown
    by none of the figures, so the data it rests on is exported here whether
    or not the figure survives the page budget.
    """
    series: dict[str, list[dict[str, float]]] = {}
    total = 0
    for row in rows:
        channels = str(int(row["channels"]))
        total += int(row["topologies"])
        series.setdefault(channels, []).append({
            "nodes": int(row["node_count"]),
            "latency_mean": float(row["latency_mean"]),
            "latency_ci95": float(row["latency_ci95"]),
            "valid_rate": float(row["valid_rate"]),
        })
    for points in series.values():
        points.sort(key=lambda r: r["nodes"])
    return {
        "shows": "mean collection span against network size, one line per "
                 "channel count, over the whole sweep",
        "configurations": len(rows),
        "runs": total,
        "valid_rate_min": min(float(r["valid_rate"]) for r in rows),
        "series": series,
    }


def fig6_schedule(harness: Mapping[str, Any], ledger: Mapping[str, Any],
                  request_id: str, catalogue_path: str) -> dict[str, Any]:
    """One request end to end, including the schedule it produced.

    The ledger stores the schedule's statistics but not its entries, so the
    entries are recomputed here by running the deterministic stages on the
    typed request the model returned. That is sound precisely because those
    stages are deterministic: the recomputation is checked against the
    latency and transmission count the ledger recorded, and refuses to export
    if they differ.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from agentic_anex.models import AnexConfig
    from agentic_anex.tools import run_anex
    from agentic_anex.topology_io import load_json_topology

    record, item = ledger[request_id], harness[request_id]
    fields = record["parsed_fields"]
    catalogue = json.loads(Path(catalogue_path).read_text(encoding="utf-8"))
    entry = catalogue[record["topology_id"]]
    network = load_json_topology(Path(entry["path"]))
    result = run_anex(network, AnexConfig(
        working_period=network.working_period,
        channels=int(fields["channels"]),
        communication_range=network.communication_range,
        interference_ratio=float(fields["interference_ratio"]),
        seed=int(fields["seed"])))

    recorded = record["schedule_metrics"]
    if (result.latency_slots != recorded["latency_slots"]
            or len(result.schedule) != recorded["scheduled_transmissions"]):
        raise ValueError(
            f"recomputed schedule for {request_id} does not match the ledger: "
            f"{result.latency_slots} slots and {len(result.schedule)} "
            f"transmissions against {recorded['latency_slots']} and "
            f"{recorded['scheduled_transmissions']}")

    return {
        "request_id": request_id,
        "user_text": item["user_text"],
        "topology_id": record["topology_id"],
        "typed_request": {k: fields.get(k) for k in CONTRACT_ORDER
                          if k in fields},
        # The contract's documented defaults, so the figure can separate what
        # the model read out of the sentence from what the contract supplied.
        "contract_defaults": {"channels": 2, "interference_ratio": 1.0,
                              "collision_model": "legacy_neighbor", "seed": 0,
                              "latency_target_slots": None},
        "sink": network.sink_id,
        "nodes": [{"id": n.id, "x": n.x, "y": n.y} for n in network.nodes],
        "schedule": [{"sender": e.sender, "receiver": e.receiver,
                      "slot": e.timeslot, "channel": e.channel}
                     for e in result.schedule],
        "latency_slots": result.latency_slots,
        "certificate": {"valid": result.validation.valid,
                        "violations": len(result.validation.violations)},
        "cost": {"model_calls": record.get("model_calls"),
                 "wall_seconds": round(record.get("wall_time_seconds") or 0, 2)},
        "recomputed": "schedule entries recomputed from the ledger's typed "
                      "request; latency and transmission count verified "
                      "against the ledger",
    }


CONTRACT_ORDER = ("workload", "objective", "channels", "collision_model",
                  "interference_ratio", "latency_target_slots", "seed")


def fig6_trace(harness: Mapping[str, Any], ledger: Mapping[str, Any],
               request_id: str) -> dict[str, Any]:
    """One request carried end to end, taken from a ledger rather than written.

    The paper shows what the agent is asked and what the numbers say about it,
    and never once shows what it answers. This exports a single real run: the
    user's sentence, the typed request the model returned, and what the
    deterministic stages then produced. The item is chosen for what it
    exercises, not for flattering output --- it states a latency target the
    schedule misses, so the reporter has to say so.
    """
    record = ledger[request_id]
    item = harness[request_id]
    metrics = record.get("schedule_metrics") or {}
    parsed = {k: record["parsed_fields"].get(k) for k in CONTRACT_ORDER
              if k in record["parsed_fields"]}
    validation = record.get("validation") or {}
    return {
        "request_id": request_id,
        "user_text": item["user_text"],
        "topology_id": record.get("topology_id"),
        "typed_request": parsed,
        "result": {
            "transmissions": metrics.get("scheduled_transmissions"),
            "latency_slots": metrics.get("latency_slots"),
            "target_slots": parsed.get("latency_target_slots"),
            "target_met": (None if parsed.get("latency_target_slots") is None
                           else metrics.get("latency_slots")
                           <= parsed["latency_target_slots"]),
            "nodes": metrics.get("node_count"),
        },
        "certificate": {"valid": validation.get("valid"),
                        "violations": len(validation.get("violations") or ())},
        "cost": {"model_calls": record.get("model_calls"),
                 "wall_seconds": round(record.get("wall_time_seconds") or 0, 2)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--results-dir", required=True,
                        help="directory holding the final ledgers")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--phi4-gated", default="phi4_policy_v2_v31gpu.jsonl")
    parser.add_argument("--phi4-ungated", default="phi4_no_scope_gate_v31gpu.jsonl")
    parser.add_argument("--gpt-gated", default="gpt55_policy_v2_v31.jsonl")
    parser.add_argument("--gpt-ungated", default="gpt55_no_scope_gate_v31.jsonl")
    parser.add_argument("--gpt-ungated-repeats", nargs="*",
                        default=["gpt55_no_scope_gate_seed11.jsonl",
                                 "gpt55_no_scope_gate_seed12.jsonl",
                                 "gpt55_no_scope_gate_seed13.jsonl"],
                        help="the repeats Figure 2's agent bars average over; the "
                             "gate's bars come from one ledger because the gate is "
                             "deterministic")
    parser.add_argument("--qwen", default="qwen25_policy_v2_v31gpu.jsonl")
    parser.add_argument("--trace-ledger", default="gpt55_no_scope_gate_seed11.jsonl")
    parser.add_argument("--topology-catalogue",
                        default="benchmarks/topologies/"
                                "frozen_test_v3_llm_catalogue.json")
    parser.add_argument("--trace-request", default="ft3-r0029")
    parser.add_argument("--direct-analysis",
                        default="results/frozen_test_v3/analysis_b2/"
                                "direct_generation.json")
    parser.add_argument("--scaling-summary",
                        default="results/topology_scaling/fixed_area100_r20/"
                                "summary.csv")
    args = parser.parse_args()

    results = Path(args.results_dir)
    harness = load(args.harness)
    ledgers = {
        "phi4": load(results / args.phi4_gated),
        "phi4_no_gate": load(results / args.phi4_ungated),
        "qwen25": load(results / args.qwen),
        "gpt55": load(results / args.gpt_gated),
        "gpt55_no_gate": load(results / args.gpt_ungated),
    }
    gated_arms = {k: v for k, v in ledgers.items() if not k.endswith("no_gate")}

    figures = {
        "fig1_pipeline": fig1_pipeline(harness, gated_arms),
        "fig2_phrasing": fig2_phrasing(
            harness, ledgers["gpt55"],
            [load(results / name) for name in args.gpt_ungated_repeats]
            or [ledgers["gpt55_no_gate"]]),
        "fig3_ablation": fig3_ablation(harness, {
            "phi4:14b": (ledgers["phi4"], ledgers["phi4_no_gate"]),
            "gpt-5.5": (ledgers["gpt55"], ledgers["gpt55_no_gate"]),
        }),
    }
    trace_path = results / args.trace_ledger
    if trace_path.exists():
        trace_ledger = load(trace_path)
        if args.trace_request in trace_ledger:
            figures["fig6_trace"] = fig6_schedule(
                harness, trace_ledger, args.trace_request,
                args.topology_catalogue)
    direct_path = Path(args.direct_analysis)
    if direct_path.exists():
        figures["fig4_direct"] = fig4_direct(
            json.loads(direct_path.read_text(encoding="utf-8")))
    scaling_path = Path(args.scaling_summary)
    if scaling_path.exists():
        with open(scaling_path, encoding="utf-8", newline="") as handle:
            figures["fig5_scaling"] = fig5_scaling(list(csv.DictReader(handle)))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, payload in figures.items():
        payload["computed_from"] = {"harness": str(args.harness),
                                    "results_dir": str(results)}
        path = out / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        written.append(str(path))
    print(json.dumps({"status": "exported", "files": written,
                      "no_language_model_invoked": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
