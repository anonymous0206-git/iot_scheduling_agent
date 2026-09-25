#!/usr/bin/env python3
"""B2: ask the model for the schedule itself, with no solver in the loop.

This is the baseline that decides whether the deterministic tool is necessary at
all. If a language model can produce a valid aggregation schedule directly, the
architecture of the paper is unnecessary machinery; if it cannot, the machinery
is justified by measurement rather than by assertion.

The baseline is given every advantage we can give it, because a straw man proves
nothing:

  * the full topology, serialised as node identifiers, neighbour lists and
    duty-cycle active slots --- exactly what the scheduler itself sees;
  * the constraints stated explicitly, in the same terms the validator checks;
  * schema-constrained decoding through the same strict-schema adapter the agent
    uses, so a malformed response is never the reason it fails;
  * the same retry budget the agent gets, with the validator's violations fed
    back as the diagnosis, which is more help than the agent's own retry
    receives.

Only gold-\\textsc{execute} items are run: they are the requests where a schedule
is the correct answer. The output of each attempt is checked by the same
independent validator the agent's schedules pass through, under the channel
count and collision model the request specifies.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from agentic_anex.llm_clients import ProviderConfig, create_llm_client
from agentic_anex.llm_clients.base import LLMClientError
from agentic_anex.llm_clients.http_transport import HTTPStatusError
from agentic_anex.schemas import ScheduleEntry, SchemaError
from agentic_anex.tools import ValidationMode, validate_schedule
from agentic_anex.topology_io import load_json_topology

SCHEDULE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schedule"],
    "properties": {
        "schedule": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["sender", "receiver", "timeslot", "channel",
                             "receiver_active_slot"],
                "properties": {
                    "sender": {"type": "integer"},
                    "receiver": {"type": "integer"},
                    "timeslot": {"type": "integer"},
                    "channel": {"type": "integer"},
                    "receiver_active_slot": {"type": "integer"},
                },
            },
        },
    },
}

CONSTRAINTS = """Every non-sink node must appear exactly once as a sender.
A sender's receiver must be one of that sender's neighbours.
The sink never transmits.
Following receivers from any sender must reach the sink; no cycles.
A node transmits only after every node that transmits to it has done so.
receiver_active_slot must be one of the receiver's active slots, and must equal
timeslot modulo the working period.
Two senders transmitting in the same timeslot and channel must not share a
receiver, and must not have a common neighbour that is receiving.
Channels are numbered 1 to {channels}.
Minimise the largest timeslot used."""


def serialise_topology(instance) -> str:
    lines = [f"sink={instance.sink_id} working_period={instance.working_period} "
             f"nodes={len(instance.nodes)}"]
    for node in instance.nodes:
        neighbours = ",".join(str(n) for n in node.neighbor_ids)
        slots = ",".join(str(s) for s in node.active_slots)
        lines.append(f"{node.id} nb=[{neighbours}] act=[{slots}]")
    return "\n".join(lines)


def build_prompt(user_text: str, instance, channels: int, collision_model: str,
                 violations: Sequence[Mapping[str, Any]] = ()) -> str:
    parts = [
        "You are scheduling one round of data aggregation. Return the schedule "
        "itself; no solver is available to you.",
        f"\nREQUEST\n{user_text}",
        f"\nNETWORK\n{serialise_topology(instance)}",
        f"\nCOLLISION MODEL: {collision_model}",
        f"\nCONSTRAINTS\n{CONSTRAINTS.format(channels=channels)}",
    ]
    if violations:
        rendered = "\n".join(f"- {json.dumps(v)}" for v in violations[:20])
        parts.append("\nYOUR PREVIOUS ATTEMPT WAS REJECTED BY THE VALIDATOR:\n"
                     f"{rendered}\nProduce a corrected schedule.")
    parts.append("\nReturn one JSON object with a single key, schedule.")
    return "\n".join(parts)


def to_entries(payload: Mapping[str, Any]) -> list[ScheduleEntry]:
    rows = payload.get("schedule")
    if not isinstance(rows, list):
        raise SchemaError("schedule must be a list", code="INVALID_SCHEDULE")
    return [ScheduleEntry(sender=int(r["sender"]), receiver=int(r["receiver"]),
                          timeslot=int(r["timeslot"]), channel=int(r["channel"]),
                          receiver_active_slot=int(r["receiver_active_slot"]))
            for r in rows]


RATE_LIMIT_WAITS = (5, 15, 45, 120, 300)


def generate_with_backoff(client, prompt: str, schema: Mapping[str, Any]):
    """Wait out a rate limit rather than recording it as a failed attempt."""
    waited = 0.0
    for wait in (*RATE_LIMIT_WAITS, None):
        try:
            return client.generate_structured(prompt=prompt, response_schema=schema), waited
        except HTTPStatusError as exc:
            if exc.status != 429 or wait is None:
                raise
            time.sleep(wait)
            waited += wait
    raise RuntimeError("unreachable")


def run_item(client, item, instance, max_retries: int) -> dict[str, Any]:
    gold = item.get("gold_fields") or {}
    channels = int(gold.get("channels", 1))
    collision_model = str(gold.get("collision_model", "legacy_neighbor"))
    mode = ValidationMode(collision_model, channels,
                          float(gold.get("interference_ratio", 1.0)))

    attempts: list[dict[str, Any]] = []
    violations: list[Mapping[str, Any]] = []
    started = time.monotonic()
    for attempt in range(max_retries + 1):
        prompt = build_prompt(item["user_text"], instance, channels,
                              collision_model, violations)
        record: dict[str, Any] = {"attempt": attempt}
        try:
            response, waited = generate_with_backoff(client, prompt, SCHEDULE_JSON_SCHEMA)
            if waited:
                record["rate_limit_seconds_waited"] = waited
        except HTTPStatusError as exc:
            record.update(stage="provider", error=f"HTTP {exc.status} after backoff",
                          code="RATE_LIMITED")
            attempts.append(record)
            continue
        except LLMClientError as exc:
            record.update(stage="provider", error=str(exc),
                          code=getattr(exc, "code", None))
            attempts.append(record)
            continue
        except Exception as exc:
            record.update(stage="transport", error=f"{type(exc).__name__}: {exc}")
            attempts.append(record)
            continue
        record["structured_output_mode"] = (
            response.model_metadata.get("structured_output_mode"))
        record["completion_tokens"] = response.model_metadata.get("completion_tokens")
        try:
            entries = to_entries(response.structured_output)
        except (SchemaError, KeyError, TypeError, ValueError) as exc:
            record.update(stage="parse", error=str(exc))
            attempts.append(record)
            continue
        record["transmissions"] = len(entries)
        report = validate_schedule(instance, entries, mode)
        violations = [v.to_dict() if hasattr(v, "to_dict") else dict(v)
                      for v in (report.violations or ())]
        record.update(stage="validated", valid=bool(report.valid),
                      violation_count=len(violations),
                      violation_codes=sorted({str(v.get("code")) for v in violations}))
        if report.valid:
            record["latency_slots"] = max(e.timeslot for e in entries) + 1 if entries else 0
        attempts.append(record)
        if report.valid:
            break

    final = attempts[-1] if attempts else {}
    return {
        "request_id": item["request_id"],
        "topology_id": item.get("topology_id"),
        "gold_action": item["gold_action"],
        "channels": channels,
        "collision_model": collision_model,
        "expected_transmissions": len(instance.nodes) - 1,
        "attempts": attempts,
        "valid": bool(final.get("valid")),
        "reached_validator": any(a.get("stage") == "validated" for a in attempts),
        "latency_slots": final.get("latency_slots"),
        "wall_time_seconds": round(time.monotonic() - started, 3),
        "system": "direct_generation", "model": client.model,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--topology-catalogue", required=True)
    parser.add_argument("--raw-output", required=True)
    parser.add_argument("--provider", required=True,
                        choices=("ollama", "openai", "openai_compatible"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--temperature", type=float, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0,
                        help="run only the first N items (0 runs all)")
    parser.add_argument("--resume", action="store_true",
                        help="append to an existing ledger, skipping items already in it")
    parser.add_argument("--only", metavar="FILE",
                        help="run only the request ids listed in this file, one per "
                             "line; lines beginning with # are ignored. The selection "
                             "must be made before the run and from the benchmark "
                             "rather than from results.")
    args = parser.parse_args()

    out = Path(args.raw_output)
    done: set[str] = set()
    if out.exists():
        if not args.resume:
            print(json.dumps({"status": "refused", "problems": [
                f"ledger exists; pass --resume to finish it: {out}"]}, indent=2))
            return 1
        existing = [json.loads(line) for line in
                    out.read_text(encoding="utf-8").splitlines() if line.strip()]
        # A record that never reached the validator is a provider refusal, not a
        # measurement; resuming must re-run it rather than skip it.
        done = {r["request_id"] for r in existing
                if any(a.get("stage") == "validated" for a in r.get("attempts", ()))}
        refused = [r["request_id"] for r in existing if r["request_id"] not in done]
        if refused:
            keep = [r for r in existing if r["request_id"] in done]
            out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in keep),
                           encoding="utf-8")
            print(f"resuming: {len(done)} measured items kept, "
                  f"{len(refused)} provider refusals dropped for re-run", flush=True)
        else:
            print(f"resuming: {len(done)} items already measured", flush=True)

    catalogue = json.loads(Path(args.topology_catalogue).read_text(encoding="utf-8"))
    items = [json.loads(line) for line in
             Path(args.harness).read_text(encoding="utf-8").splitlines() if line.strip()]
    execute = [i for i in items if i["gold_action"] == "EXECUTE" and i.get("topology_id")]
    if args.limit:
        execute = execute[:args.limit]
    if args.only:
        wanted = [line.strip() for line in
                  Path(args.only).read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")]
        known = {i["request_id"] for i in execute}
        unknown = sorted(set(wanted) - known)
        if unknown:
            print(json.dumps({"status": "refused", "problems": [
                f"selection names ids that are not gold-EXECUTE items: {unknown}"]},
                indent=2))
            return 1
        order = {rid: n for n, rid in enumerate(wanted)}
        execute = sorted((i for i in execute if i["request_id"] in order),
                         key=lambda i: order[i["request_id"]])
    execute = [i for i in execute if i["request_id"] not in done]
    if not execute:
        print(json.dumps({"status": "nothing_to_do",
                          "problems": ["every item is already in the ledger"]}, indent=2))
        return 0

    client = create_llm_client(ProviderConfig(
        provider=args.provider, model=args.model, base_url=args.base_url,
        api_key_env=args.api_key_env, temperature=args.temperature,
        timeout_seconds=args.timeout_seconds))

    cache: dict[str, Any] = {}
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("a" if done else "w", encoding="utf-8") as handle:
        for index, item in enumerate(execute, start=1):
            name = item["topology_id"]
            if name not in cache:
                cache[name] = load_json_topology(Path(catalogue[name]["path"]))
            record = run_item(client, item, cache[name], args.max_retries)
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            written += 1
            print(f"[{index}/{len(execute)}] {item['request_id']} "
                  f"valid={record['valid']} "
                  f"nodes={len(cache[name].nodes)}", flush=True)

    ledger = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    measured = [r for r in ledger
                if any(a.get("stage") == "validated" for a in r.get("attempts", ()))]
    valid = [r for r in measured if r["valid"]]
    print(json.dumps({
        "status": "completed",
        "items_written_this_run": written,
        "ledger_records": len(ledger),
        "ledger_measured": len(measured),
        "ledger_valid": len(valid),
        # The rate is over measured items, never over this run's writes: a run
        # that finishes a partial ledger would otherwise report a rate above one.
        "valid_rate_over_measured": round(len(valid) / len(measured), 4) if measured else 0.0,
        "raw_output": str(out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
