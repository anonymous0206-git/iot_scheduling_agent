#!/usr/bin/env python3
"""Mutation test for the independent validator.

The architecture's guarantee is conditional: no schedule reaches the user
unless a validator implemented separately from the scheduler accepts it,
*provided the validator is correct on the conditions it checks*. Writing the
validator as a second implementation is a design argument for that proviso,
not evidence for it. This script supplies the evidence, by breaking schedules
on purpose and checking that the validator says so.

The method. For each catalogue topology the deterministic scheduler produces a
schedule the validator certifies. Every mutation operator below takes that
certified schedule and returns a copy carrying exactly one injected defect,
aimed at one condition of Section 3:

    (i)    every non-sink node transmits exactly once
    (ii)   a transmission uses a communication link
    (iii)  the sink never transmits
    (iv)   no two transmissions sharing a slot and a channel collide
    (v)    a node transmits only after every node it receives from

plus the checks the validator makes beyond those five, which are reported
under `beyond` so the claim about (i)-(v) stays separable from them.

Two numbers per condition, because they answer different questions:

    rejected   the mutant did not pass. This is what the guarantee needs: a
               broken schedule must not reach the user.
    targeted   the mutant was rejected *with the code for the condition it
               attacks*. A mutant can be rejected for a side effect of the
               mutation instead, which still protects the user but does not
               show the intended check firing.

A mutant that is not rejected is a survivor and is listed in full. One
survivor falsifies the proviso, so this script exits non-zero if any mutant
survives: a mutation suite whose failures are advisory is not evidence.

    run_validator_mutation_test.py --catalogue benchmarks/topologies/...json
                                   --output-dir results/validator_mutation
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from agentic_anex.models import AnexConfig                       # noqa: E402
from agentic_anex.schemas import NetworkInstance, ScheduleEntry  # noqa: E402
from agentic_anex.tools import run_anex                          # noqa: E402
from agentic_anex.topology_io import load_json_topology          # noqa: E402
from agentic_anex.validator import validate_schedule             # noqa: E402

CONDITIONS: dict[str, str] = {
    "(i)": "every non-sink node transmits exactly once",
    "(ii)": "a transmission uses a communication link",
    "(iii)": "the sink never transmits",
    "(iv)": "no two transmissions sharing a slot and a channel collide",
    "(v)": "a node transmits only after every node it receives from",
    "beyond": "checks the validator makes beyond conditions (i)-(v)",
}


@dataclass(frozen=True)
class Mutant:
    """One certified schedule with exactly one injected defect."""
    operator: str
    condition: str
    expected_code: str
    witness: str
    schedule: tuple[ScheduleEntry, ...]


def _spread(count: int, limit: int) -> list[int]:
    """Evenly spaced indices, so the sample is reproducible without an RNG."""
    if count <= 0:
        return []
    if count <= limit:
        return list(range(count))
    step = count / limit
    return sorted({min(count - 1, int(index * step)) for index in range(limit)})


def _retimed(entry: ScheduleEntry, timeslot: int, working_period: int,
             channel: int | None = None) -> ScheduleEntry:
    """Move an entry to a slot, keeping the recorded active slot consistent.

    Without this the mutant would also trip ACTIVE_SLOT_FIELD_MISMATCH, and a
    mutant killed by bookkeeping it did not mean to break is weak evidence for
    the check it was aiming at.
    """
    return replace(entry, timeslot=timeslot,
                   receiver_active_slot=timeslot % working_period,
                   channel=entry.channel if channel is None else channel)


# --- operators -------------------------------------------------------------
# Each takes the certified schedule and yields mutants, at most `limit` each.

def drop_transmission(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                      channels: int, limit: int) -> Iterator[Mutant]:
    for index in _spread(len(schedule), limit):
        gone = schedule[index]
        yield Mutant("drop_transmission", "(i)", "MISSING_TRANSMISSION",
                     f"node {gone.sender} no longer transmits",
                     tuple(schedule[:index]) + tuple(schedule[index + 1:]))


def duplicate_transmission(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                           channels: int, limit: int) -> Iterator[Mutant]:
    for index in _spread(len(schedule), limit):
        entry = schedule[index]
        yield Mutant("duplicate_transmission", "(i)", "DUPLICATE_TRANSMISSION",
                     f"node {entry.sender} transmits twice",
                     tuple(schedule) + (entry,))


def non_neighbour_receiver(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                           channels: int, limit: int) -> Iterator[Mutant]:
    nodes = {node.id: node for node in network.nodes}
    for index in _spread(len(schedule), limit):
        entry = schedule[index]
        stranger = next((other for other in sorted(nodes)
                         if other != entry.sender
                         and other not in nodes[entry.sender].neighbor_ids), None)
        if stranger is None:
            continue
        mutated = list(schedule)
        mutated[index] = replace(entry, receiver=stranger)
        yield Mutant("non_neighbour_receiver", "(ii)", "NON_NEIGHBOR_LINK",
                     f"{entry.sender} transmits to non-neighbour {stranger}",
                     tuple(mutated))


def sink_transmits(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                   channels: int, limit: int) -> Iterator[Mutant]:
    nodes = {node.id: node for node in network.nodes}
    sink = network.sink_id
    for index in _spread(len(schedule), limit):
        entry = schedule[index]
        if entry.receiver == sink or sink not in nodes[entry.receiver].neighbor_ids:
            continue
        mutated = list(schedule)
        mutated[index] = replace(entry, sender=sink)
        yield Mutant("sink_transmits", "(iii)", "SINK_TRANSMISSION",
                     f"the sink transmits to {entry.receiver}", tuple(mutated))


def primary_collision(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                      channels: int, limit: int) -> Iterator[Mutant]:
    """Two senders reach one receiver in one slot."""
    siblings: dict[int, list[int]] = {}
    for index, entry in enumerate(schedule):
        siblings.setdefault(entry.receiver, []).append(index)
    pairs = [(group[0], group[1]) for group in siblings.values() if len(group) > 1]
    for first, second in pairs[:limit]:
        mutated = list(schedule)
        mutated[second] = _retimed(schedule[second], schedule[first].timeslot,
                                   network.working_period, schedule[first].channel)
        yield Mutant("primary_collision", "(iv)", "PRIMARY_COLLISION",
                     f"{schedule[first].sender} and {schedule[second].sender} both reach "
                     f"{schedule[first].receiver} at slot {schedule[first].timeslot}",
                     tuple(mutated))


def secondary_collision(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                        channels: int, limit: int) -> Iterator[Mutant]:
    """Two links that interfere are put on one slot and channel."""
    nodes = {node.id: node for node in network.nodes}
    produced = 0
    for first, entry in enumerate(schedule):
        for second, other in enumerate(schedule):
            if produced >= limit:
                return
            if first >= second or entry.receiver == other.receiver:
                continue
            interferes = (entry.sender in nodes[other.receiver].neighbor_ids
                          or other.sender in nodes[entry.receiver].neighbor_ids)
            if not interferes:
                continue
            mutated = list(schedule)
            mutated[second] = _retimed(other, entry.timeslot, network.working_period,
                                       entry.channel)
            produced += 1
            yield Mutant("secondary_collision", "(iv)", "SECONDARY_COLLISION",
                         f"{entry.sender}->{entry.receiver} and {other.sender}->"
                         f"{other.receiver} share slot {entry.timeslot} channel "
                         f"{entry.channel}", tuple(mutated))
            break


def half_duplex(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                channels: int, limit: int) -> Iterator[Mutant]:
    """A node receives in the slot it transmits in."""
    by_sender = {entry.sender: index for index, entry in enumerate(schedule)}
    produced = 0
    for index, entry in enumerate(schedule):
        if produced >= limit:
            return
        parent = by_sender.get(entry.receiver)
        if parent is None or schedule[parent].timeslot == entry.timeslot:
            continue
        mutated = list(schedule)
        mutated[index] = _retimed(entry, schedule[parent].timeslot, network.working_period)
        produced += 1
        yield Mutant("half_duplex", "(iv)", "HALF_DUPLEX_VIOLATION",
                     f"{entry.receiver} receives and transmits at slot "
                     f"{schedule[parent].timeslot}", tuple(mutated))


def precedence_inversion(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                         channels: int, limit: int) -> Iterator[Mutant]:
    """A child stops preceding its parent."""
    by_sender = {entry.sender: index for index, entry in enumerate(schedule)}
    produced = 0
    for index, entry in enumerate(schedule):
        if produced >= limit:
            return
        parent = by_sender.get(entry.receiver)
        if parent is None:
            continue
        parent_slot = schedule[parent].timeslot
        if entry.timeslot >= parent_slot:
            continue
        mutated = list(schedule)
        mutated[index] = _retimed(entry, parent_slot + 1, network.working_period)
        produced += 1
        yield Mutant("precedence_inversion", "(v)", "PRECEDENCE_VIOLATION",
                     f"child {entry.sender} now transmits after parent {entry.receiver}",
                     tuple(mutated))


def channel_out_of_range(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                         channels: int, limit: int) -> Iterator[Mutant]:
    for index in _spread(len(schedule), limit):
        mutated = list(schedule)
        mutated[index] = replace(schedule[index], channel=channels + 1)
        yield Mutant("channel_out_of_range", "beyond", "INVALID_CHANNEL",
                     f"channel {channels + 1} with {channels} available", tuple(mutated))


def unknown_receiver(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                     channels: int, limit: int) -> Iterator[Mutant]:
    absent = max(node.id for node in network.nodes) + 1
    for index in _spread(len(schedule), limit):
        mutated = list(schedule)
        mutated[index] = replace(schedule[index], receiver=absent)
        yield Mutant("unknown_receiver", "beyond", "UNKNOWN_RECEIVER",
                     f"receiver {absent} is not in the network", tuple(mutated))


def active_slot_field_mismatch(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                               channels: int, limit: int) -> Iterator[Mutant]:
    for index in _spread(len(schedule), limit):
        entry = schedule[index]
        mutated = list(schedule)
        mutated[index] = replace(entry, receiver_active_slot=(entry.receiver_active_slot + 1)
                                 % network.working_period)
        yield Mutant("active_slot_field_mismatch", "beyond", "ACTIVE_SLOT_FIELD_MISMATCH",
                     f"recorded active slot disagrees with slot {entry.timeslot}",
                     tuple(mutated))


def parent_cycle(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                 channels: int, limit: int) -> Iterator[Mutant]:
    """Two nodes forward to each other, so no path reaches the sink."""
    by_sender = {entry.sender: index for index, entry in enumerate(schedule)}
    produced = 0
    for index, entry in enumerate(schedule):
        if produced >= limit:
            return
        parent = by_sender.get(entry.receiver)
        if parent is None:
            continue
        mutated = list(schedule)
        mutated[parent] = replace(schedule[parent], receiver=entry.sender)
        produced += 1
        yield Mutant("parent_cycle", "beyond", "PARENT_CYCLE",
                     f"{entry.sender} and {entry.receiver} forward to each other",
                     tuple(mutated))


OPERATORS: tuple[Callable[..., Iterator[Mutant]], ...] = (
    drop_transmission, duplicate_transmission, non_neighbour_receiver, sink_transmits,
    primary_collision, secondary_collision, half_duplex, precedence_inversion,
    channel_out_of_range, unknown_receiver, active_slot_field_mismatch, parent_cycle,
)


def mutants_for(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                channels: int, limit: int) -> list[Mutant]:
    produced: list[Mutant] = []
    for operator in OPERATORS:
        produced.extend(operator(network, schedule, channels, limit))
    return produced


def kill_report(network: NetworkInstance, schedule: Sequence[ScheduleEntry],
                channels: int, mutants: Sequence[Mutant],
                collision_model: str = "legacy_neighbor") -> dict[str, Any]:
    """Run the validator on every mutant and say which survived."""
    baseline = validate_schedule(network, tuple(schedule), channels=channels,
                                 collision_model=collision_model)
    if not baseline.valid:
        raise ValueError("the unmutated schedule is already invalid: "
                         f"{[v.code for v in baseline.violations]}")
    results = []
    for mutant in mutants:
        report = validate_schedule(network, mutant.schedule, channels=channels,
                                   collision_model=collision_model)
        codes = {violation.code for violation in report.violations}
        results.append({
            "operator": mutant.operator, "condition": mutant.condition,
            "expected_code": mutant.expected_code, "witness": mutant.witness,
            "rejected": not report.valid,
            "caught_by_the_targeted_check": mutant.expected_code in codes,
            "codes": sorted(codes),
        })
    return {"mutants": len(results), "results": results}


def _tally(results: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in results:
        bucket = buckets.setdefault(str(item[key]), {"mutants": 0, "rejected": 0,
                                                     "targeted": 0, "survivors": []})
        bucket["mutants"] += 1
        bucket["rejected"] += int(item["rejected"])
        bucket["targeted"] += int(item["caught_by_the_targeted_check"])
        if not item["rejected"]:
            bucket["survivors"].append(item)
    for bucket in buckets.values():
        bucket["kill_rate"] = round(bucket["rejected"] / bucket["mutants"], 4)
        bucket["targeted_rate"] = round(bucket["targeted"] / bucket["mutants"], 4)
    return buckets


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = ["# Validator mutation test", "",
             f"{report['totals']['mutants']} mutants over "
             f"{len(report['topologies'])} topologies; "
             f"{report['totals']['rejected']} rejected, "
             f"{report['totals']['survivors']} survivors.", "",
             "Every mutant is one certified schedule with one injected defect. "
             "`rejected` is what", "the guarantee needs; `targeted` is the stronger "
             "reading, that the check aimed at", "fired rather than a side effect of "
             "the mutation.", "",
             "## By condition", "",
             "| Condition | Mutants | Rejected | Targeted | Statement |",
             "|---|---:|---:|---:|---|"]
    for name, bucket in report["by_condition"].items():
        lines.append(f"| {name} | {bucket['mutants']} | "
                     f"{bucket['rejected']} ({bucket['kill_rate']:.3f}) | "
                     f"{bucket['targeted']} ({bucket['targeted_rate']:.3f}) | "
                     f"{CONDITIONS.get(name, '')} |")
    lines.extend(["", "## By operator", "",
                  "| Operator | Condition | Expected code | Mutants | Rejected | Targeted |",
                  "|---|---|---|---:|---:|---:|"])
    for name, bucket in report["by_operator"].items():
        lines.append(f"| `{name}` | {bucket['condition']} | `{bucket['expected_code']}` | "
                     f"{bucket['mutants']} | {bucket['rejected']} | {bucket['targeted']} |")
    if report["totals"]["survivors"]:
        lines.extend(["", "## Survivors", "",
                      "| Operator | Witness | Codes raised |", "|---|---|---|"])
        for item in report["survivors"]:
            lines.append(f"| `{item['operator']}` | {item['witness']} | "
                         f"{', '.join(item['codes']) or 'none'} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalogue",
                        default=str(ROOT / "benchmarks" / "topologies"
                                    / "frozen_test_v3_llm_catalogue.json"))
    parser.add_argument("--channels", type=int, default=2)
    parser.add_argument("--per-operator", type=int, default=12,
                        help="mutants each operator produces per topology")
    parser.add_argument("--topology", action="append", default=[],
                        help="restrict to these catalogue ids (repeatable)")
    parser.add_argument("--output-dir", help="write mutation.json and mutation.md here")
    args = parser.parse_args()

    catalogue = json.loads(Path(args.catalogue).read_text(encoding="utf-8"))
    wanted = args.topology or sorted(catalogue)
    per_topology, results = {}, []
    for topology_id in wanted:
        if topology_id not in catalogue:
            print(json.dumps({"status": "refused", "problems": [
                f"{topology_id} is not in {args.catalogue}"]}, indent=2))
            return 1
        # Catalogue paths are written relative to the repository root, so the
        # sweep works from any working directory.
        network = load_json_topology(ROOT / catalogue[topology_id]["path"])
        config = AnexConfig(working_period=network.working_period, channels=args.channels,
                            communication_range=network.communication_range)
        schedule = run_anex(network, config).schedule
        mutants = mutants_for(network, schedule, args.channels, args.per_operator)
        try:
            outcome = kill_report(network, schedule, args.channels, mutants)
        except ValueError as exc:
            print(json.dumps({"status": "refused", "problems": [
                f"{topology_id}: {exc}"]}, indent=2))
            return 1
        for item in outcome["results"]:
            item["topology_id"] = topology_id
        per_topology[topology_id] = {
            "nodes": len(network.nodes), "entries": len(schedule),
            "mutants": outcome["mutants"],
            "rejected": sum(1 for r in outcome["results"] if r["rejected"]),
        }
        results.extend(outcome["results"])

    survivors = [item for item in results if not item["rejected"]]
    report = {
        "mutation_format": "agentic_anex.validator_mutation.v1",
        "catalogue": args.catalogue, "channels": args.channels,
        "mutants_per_operator_per_topology": args.per_operator,
        "conditions": CONDITIONS,
        "topologies": per_topology,
        "totals": {"mutants": len(results),
                   "rejected": sum(1 for r in results if r["rejected"]),
                   "targeted": sum(1 for r in results if r["caught_by_the_targeted_check"]),
                   "survivors": len(survivors)},
        "by_condition": _tally(results, "condition"),
        "by_operator": {name: {**bucket,
                               "condition": next(r["condition"] for r in results
                                                 if r["operator"] == name),
                               "expected_code": next(r["expected_code"] for r in results
                                                     if r["operator"] == name)}
                        for name, bucket in _tally(results, "operator").items()},
        "survivors": survivors,
    }

    if args.output_dir:
        directory = Path(args.output_dir)
        payloads = {"mutation.json": json.dumps(report, indent=2, sort_keys=True) + "\n",
                    "mutation.md": render_markdown(report)}
        existing = [name for name in payloads if (directory / name).exists()]
        if existing:
            print(json.dumps({"status": "refused", "problems": [
                f"refusing to overwrite {directory / name}" for name in existing]}, indent=2))
            return 1
        directory.mkdir(parents=True, exist_ok=True)
        for name, text in payloads.items():
            with open(directory / name, "x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        print(json.dumps({"status": "mutated", "output_dir": str(directory),
                          **report["totals"]}, indent=2))
    else:
        print(render_markdown(report))
    # A survivor falsifies the proviso the guarantee rests on.
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
