#!/usr/bin/env python3
"""Repeat every Frozen Test v3 arm under additional seeds, one ledger per seed.

Seed 0 of each arm already exists. A single run per arm cannot separate a real
difference between arms from provider nondeterminism, and the seed-0 pair
(`phi4_policy_v2` and `phi4_no_scope_gate`) already showed 2 of 126 identically
prompted items flipping between runs. This driver produces the repeats needed to
put an interval on that noise.

One ledger per seed, deliberately: `scripts/analyze_frozen_test_results.py` keys
records by `request_id`, so a ledger holding several seeds would silently keep
only the last record for each request. Separate files keep every seed analysable
as its own arm.

The driver shells out to the two existing runners rather than reimplementing
them, so the sealed pipeline and the ablation keep their own guard rails:

  * `scripts/run_frozen_test_v3_experiments.py` for the gated arms;
  * `scripts/run_scope_gate_ablation.py --confirm-ablation --scope-mode off` for
    the ungated arm, and the same runner with `--scope-mode advisory` for the
    arm in which the gate annotates the request instead of refusing it.

Before each timed run the driver checks which device Ollama will serve the
model on, with `scripts/preflight_ollama_arm.py`, and refuses to start the run
if the model is not on the GPU. This is not hypothetical care: the server
decides at startup whether it can see the GPU, and when discovery fails it
reports no error --- it serves on CPU at roughly a sixteenth of the token
rate, leaving every answer correct and every timing wrong. The device report
for each run is written next to that run's ledger, so the ledger can be told
afterwards which device produced it.

Note on what a seed buys at temperature 0: the seed is passed to the provider,
but greedy decoding means the repeats measure run-to-run nondeterminism of the
server (batching, kv-cache, GPU reduction order), not sampling diversity. That
is the quantity the paper needs for its error bars; it is not a claim about the
model's output distribution.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = "benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl"
CATALOGUE = "benchmarks/topologies/frozen_test_v3_llm_catalogue.json"
RESULTS = "results/frozen_test_v3"

# (arm label, ledger stem, runner, model). `runner` names the script and, for
# the two non-primary scope modes, the mode it is run in.
# (arm label, ledger stem, runner, model, provider). The frontier arms decode
# at temperature 1 because the provider rejects anything else at the transport
# layer, so their repeats sample the model where the local repeats do not.
LOCAL_ARMS = (
    ("phi4_policy_v2", "phi4_policy_v2", "gated", "phi4:14b", "ollama"),
    ("phi4_no_scope_gate", "phi4_no_scope_gate", "off", "phi4:14b", "ollama"),
    ("phi4_advisory_scope_gate", "phi4_advisory_scope_gate", "advisory", "phi4:14b", "ollama"),
    ("qwen25_policy_v2", "qwen25_policy_v2", "gated", "qwen2.5:14b", "ollama"),
)
FRONTIER_MODEL = "gpt-5.5-2026-04-23"
FRONTIER_ARMS = (
    ("gpt55_policy_v2", "gpt55_policy_v2", "gated", FRONTIER_MODEL, "openai"),
    ("gpt55_no_scope_gate", "gpt55_no_scope_gate", "off", FRONTIER_MODEL, "openai"),
    ("gpt55_advisory_scope_gate", "gpt55_advisory_scope_gate", "advisory",
     FRONTIER_MODEL, "openai"),
)
ARM_SETS = {"local": LOCAL_ARMS, "frontier": FRONTIER_ARMS,
            "all": LOCAL_ARMS + FRONTIER_ARMS}
ARMS = LOCAL_ARMS  # default, kept for callers that import it
NON_PRIMARY_RUNNERS = ("off", "advisory")
# The device check asks an Ollama endpoint what it loaded; an API arm has no
# such thing, and its provenance is the preflight in preflight_openai_arm.py.
DEVICE_CHECKED_PROVIDERS = ("ollama",)


def ledger_for(stem: str, seed: int) -> Path:
    return ROOT / RESULTS / f"{stem}_seed{seed}.jsonl"


def build_command(runner: str, model: str, ledger: Path, seed: int,
                  timeout_seconds: float, max_retries: int,
                  base_url: str | None = None,
                  provider: str = "ollama") -> list[str]:
    # Temperature 0 is greedy for the local arms; the frontier provider rejects
    # any value but 1 at the transport layer, so asking for 0 there fails the
    # run rather than producing a comparable one.
    temperature = "0" if provider == "ollama" else "1"
    common = [
        sys.executable,
        str(ROOT / "scripts" / ("run_scope_gate_ablation.py"
                                if runner in NON_PRIMARY_RUNNERS
                                else "run_frozen_test_v3_experiments.py")),
        "--benchmark", str(ROOT / BENCHMARK),
        "--topology-catalogue", str(ROOT / CATALOGUE),
        "--catalogue-dir", str(ROOT),
        "--raw-output", str(ledger),
        "--provider", provider,
        "--model", model,
        "--temperature", temperature,
        "--max-retries", str(max_retries),
        "--timeout-seconds", str(timeout_seconds),
        "--seeds", str(seed),
    ]
    if base_url and provider == "ollama":
        common += ["--base-url", base_url]
    if runner in NON_PRIMARY_RUNNERS:
        return [*common, "--confirm-ablation", "--scope-mode", runner]
    return [*common, "--systems", "llm_agent"]


def plan(seeds: tuple[int, ...], timeout_seconds: float, max_retries: int,
         base_url: str | None = None, arms=None) -> list[dict[str, object]]:
    """The full run list, in execution order, without touching the provider."""
    runs: list[dict[str, object]] = []
    for seed in seeds:
        for label, stem, runner, model, provider in (arms or ARMS):
            ledger = ledger_for(stem, seed)
            runs.append({
                "arm": label, "seed": seed, "model": model, "runner": runner,
                "provider": provider, "ledger": str(ledger),
                "command": build_command(runner, model, ledger, seed,
                                         timeout_seconds, max_retries, base_url,
                                         provider),
            })
    return runs


def existing_ledgers(runs: list[dict[str, object]]) -> list[str]:
    return sorted({str(run["ledger"]) for run in runs
                   if Path(str(run["ledger"])).exists()})


# A run whose provider refused most calls is not a result. The runner exits 0
# in that case because each item was recorded, so the campaign has to look at
# what was recorded rather than at the exit code.
MAX_PROVIDER_ERROR_RATE = 0.10
PROVIDER_ERROR_CODES = ("HTTP_PROVIDER_ERROR", "PROVIDER_TIMEOUT", "MODEL_UNAVAILABLE")


def provider_error_rate(ledger: Path) -> tuple[float, int, int]:
    """Fraction of a ledger's items that failed in the provider, not the agent."""
    total = bad = 0
    try:
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            total += 1
            if json.loads(line).get("error_code") in PROVIDER_ERROR_CODES:
                bad += 1
    except (OSError, json.JSONDecodeError):
        return 0.0, 0, 0
    return (bad / total if total else 0.0), bad, total


def device_report_for(ledger: Path) -> Path:
    return ledger.with_suffix(".device.json")


def check_device(model: str, ledger: Path, allow_cpu: bool,
                 host: str | None = None) -> tuple[bool, dict]:
    """Ask which device will serve this run, and keep the answer beside it."""
    report_path = device_report_for(Path(ledger))
    command = [sys.executable, str(ROOT / "scripts" / "preflight_ollama_arm.py"),
               "--model", model, "--json-out", str(report_path)]
    if host:
        command += ["--host", host]
    if allow_cpu:
        command.append("--allow-cpu")
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        report = {"status": "refused", "problems": [completed.stderr[-500:] or "no output"]}
    return completed.returncode == 0, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", default="1,2",
                        help="seeds to add; seed 0 already exists for every arm")
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--manifest", default=f"{RESULTS}/seed_campaign.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the run plan and exit without calling the provider")
    parser.add_argument("--only", action="append", default=[], metavar="ARM=SEED",
                        help="run just these arm/seed pairs (repeatable). Used to "
                             "fill gaps left by a campaign that aborted partway, "
                             "without re-running the runs that succeeded.")
    parser.add_argument("--arms", choices=sorted(ARM_SETS), default="local",
                        help="which arm set to run: local (Ollama), frontier "
                             "(API), or all")
    parser.add_argument("--base-url", default=None,
                        help="Ollama endpoint for both the runs and the device check; "
                             "defaults to the client's own default")
    parser.add_argument("--allow-cpu", action="store_true",
                        help="run even when the model is not served on the GPU; the "
                             "device report still records it, so the resulting timings "
                             "stay identifiable as CPU timings")
    args = parser.parse_args()

    try:
        seeds = tuple(int(value.strip()) for value in args.seeds.split(",") if value.strip())
    except ValueError:
        parser.error("seeds must be comma-separated integers")
    if not seeds or len(seeds) != len(set(seeds)):
        parser.error("seeds must be nonempty and unique")

    runs = plan(seeds, args.timeout_seconds, args.max_retries, args.base_url,
                ARM_SETS[args.arms])
    if args.only:
        wanted = set()
        for spec in args.only:
            arm, _, seed = spec.partition("=")
            if not seed.isdigit():
                parser.error(f"--only expects ARM=SEED, got {spec!r}")
            wanted.add((arm, int(seed)))
        runs = [r for r in runs if (r["arm"], r["seed"]) in wanted]
        missing = wanted - {(r["arm"], r["seed"]) for r in runs}
        if missing:
            parser.error("--only names runs that are not in the plan: "
                         + ", ".join(f"{a}={s}" for a, s in sorted(missing)))
    if args.dry_run:
        print(json.dumps({"status": "planned", "runs": runs}, indent=2))
        return 0

    clash = existing_ledgers(runs)
    if clash:
        print(json.dumps({"status": "refused", "problems": [
            "refusing to write over ledgers that already exist: " + ", ".join(clash)]},
            indent=2))
        return 1

    started = time.time()
    records: list[dict[str, object]] = []
    for index, run in enumerate(runs, start=1):
        head = f"[{index}/{len(runs)}] {run['arm']} seed={run['seed']}"
        if str(run.get("provider", "ollama")) in DEVICE_CHECKED_PROVIDERS:
            ready, device = check_device(str(run["model"]), Path(str(run["ledger"])),
                                         args.allow_cpu, args.base_url)
        else:
            # An API arm has no local device to check; its provenance comes
            # from preflight_openai_arm.py instead.
            ready, device = True, {"serving_device": str(run.get("provider"))}
        if not ready:
            print(f"{head} REFUSED: {device.get('problems', ['device check failed'])[0]}",
                  flush=True)
            records.append({"arm": run["arm"], "seed": run["seed"], "model": run["model"],
                            "ledger": run["ledger"], "returncode": 1,
                            "elapsed_seconds": 0.0, "device": device,
                            "stdout_tail": "refused before starting: device check"})
            break
        print(f"{head} starting on {device.get('serving_device')}", flush=True)
        began = time.time()
        completed = subprocess.run(run["command"], cwd=ROOT, capture_output=True, text=True)
        elapsed = time.time() - began
        ok = completed.returncode == 0
        print(f"{head} {'ok' if ok else 'FAILED'} in {elapsed / 60:.1f} min", flush=True)
        if not ok:
            print(completed.stdout[-2000:], flush=True)
            print(completed.stderr[-2000:], file=sys.stderr, flush=True)
        rate, bad, total = provider_error_rate(Path(str(run["ledger"])))
        records.append({"arm": run["arm"], "seed": run["seed"], "model": run["model"],
                        "ledger": run["ledger"], "returncode": completed.returncode,
                        "elapsed_seconds": round(elapsed, 3), "device": device,
                        "provider_error_rate": round(rate, 4),
                        "provider_errors": bad, "items": total,
                        "stdout_tail": completed.stdout[-4000:]})
        if rate > MAX_PROVIDER_ERROR_RATE:
            print(f"{head} ABORTING CAMPAIGN: {bad} of {total} items failed in the "
                  f"provider ({rate:.0%}). The ledger records answers, so the run "
                  f"exited 0, but it measures the provider and not the agent.",
                  flush=True)
            records[-1]["returncode"] = records[-1]["returncode"] or 1
            break

    manifest = {
        "status": "completed" if all(r["returncode"] == 0 for r in records) else "partial",
        "seeds_added": list(seeds),
        "total_minutes": round((time.time() - started) / 60, 2),
        "decoding": {"temperature": 0, "note":
                     "greedy decoding; repeats measure provider nondeterminism, "
                     "not sampling diversity"},
        "serving_devices": sorted({str((r.get("device") or {}).get("serving_device"))
                                   for r in records}),
        "worst_provider_error_rate": max((r.get("provider_error_rate", 0.0)
                                          for r in records), default=0.0),
        "base_url": args.base_url,
        "runs": records,
    }
    Path(ROOT / args.manifest).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "runs"}, indent=2), flush=True)
    return 0 if manifest["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
