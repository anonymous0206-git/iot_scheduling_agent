#!/usr/bin/env python3
"""Scope-gate arms: run the agent with the gate removed, or made advisory.

The evaluation protocol asks for an arm in which `paper1-scope-policy.v2` does
not run, so the gate's contribution can be measured rather than assumed. A
second question follows from the result: the enforcing gate short-circuits, so
its over-blocks are unrecoverable by construction, and a gate that annotates
instead should degrade more gracefully. This runner provides both arms.

    --scope-mode off        the gate is not consulted
    --scope-mode advisory   the same detector runs, and what it finds is
                            handed to the model as a non-binding notice

How the mode is applied: `Orchestrator` takes `scope_mode` as a parameter, so
all three configurations run the same pipeline and differ only in the gate's
authority. (This replaces an earlier version that monkeypatched
`evaluate_scope_policy` for the ungated arm; the ledger fields it produced are
unchanged, so ledgers from before and after are comparable.)

What differs between the arms, and nothing else does. In `off` the gate is
skipped and every record carries `policy_version` =
`paper1-scope-policy.v2-ABLATED`. In `advisory` the gate runs and records what
it matched, and on the requests it matched --- and only those --- the model's
prompt carries an extra ADVISORY SCOPE NOTICE block and is versioned
`paper1-requirements-v4-advisory`. On every other request the prompt is
byte-identical to the primary arm's.

Guard rails, because neither arm may become the default:

  * arms are recorded as `llm_agent_no_scope_gate` and
    `llm_agent_advisory_scope_gate`, never as `llm_agent`;
  * the runner refuses to start without `--confirm-ablation`;
  * the output ledger must be a fresh path, so a non-primary arm can never be
    appended into a primary ledger.

The consistency checker, the topology gate, ANEX, and the independent schedule
validator all keep running in every mode.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from agentic_anex.experiments import (
    SCOPE_MODE_SYSTEM_NAMES, ProviderAgentBenchmarkSystem, load_jsonl,
    run_experiment_matrix,
)
from agentic_anex.llm_clients import ProviderConfig
from agentic_anex.orchestration import ABLATED_POLICY_VERSION, ADVISORY_PROMPT_VERSION

ABLATION_SYSTEM_NAME = SCOPE_MODE_SYSTEM_NAMES["off"]
ADVISORY_SYSTEM_NAME = SCOPE_MODE_SYSTEM_NAMES["advisory"]
NON_PRIMARY_MODES = ("off", "advisory")
V3_RUNNER = Path(__file__).resolve().parent / "run_frozen_test_v3_experiments.py"


def load_v3_runner():
    spec = importlib.util.spec_from_file_location("run_frozen_test_v3_experiments", V3_RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--topology-catalogue", required=True)
    parser.add_argument("--catalogue-dir", default=None)
    parser.add_argument("--raw-output", required=True,
                        help="fresh ledger path; an existing file is refused")
    parser.add_argument("--provider", required=True,
                        choices=("ollama", "openai_compatible", "openai"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--seeds", default="0")
    parser.add_argument("--scope-mode", choices=NON_PRIMARY_MODES, default="off",
                        help="off: the gate is not consulted. advisory: the gate runs "
                             "and its finding is passed to the model as a non-binding "
                             "notice. The primary enforcing arm is not runnable here.")
    parser.add_argument("--confirm-ablation", action="store_true",
                        help="required; confirms that a non-primary arm is intended")
    args = parser.parse_args()

    if not args.confirm_ablation:
        print(json.dumps({"status": "refused", "problems": [
            "this runner changes the authority of the independent scope gate and must "
            "be confirmed with --confirm-ablation"]}, indent=2))
        return 1
    output = Path(args.raw_output)
    if output.exists():
        print(json.dumps({"status": "refused", "problems": [
            f"refusing to append an ablation into an existing ledger: {output}"]}, indent=2))
        return 1
    try:
        seeds = tuple(int(value.strip()) for value in args.seeds.split(",") if value.strip())
    except ValueError:
        parser.error("seeds must be comma-separated integers")
    if not seeds or len(seeds) != len(set(seeds)):
        parser.error("seeds must be nonempty and unique")

    runner = load_v3_runner()
    catalogue = json.loads(Path(args.topology_catalogue).read_text(encoding="utf-8"))
    items = load_jsonl(args.benchmark)
    missing = runner.check_coverage(items, catalogue)
    if missing:
        print(json.dumps({"status": "refused", "problems": [
            f"benchmark refers to topologies missing from the catalogue: {missing}"]}, indent=2))
        return 1

    system = ProviderAgentBenchmarkSystem(ProviderConfig(
        provider=args.provider, model=args.model, base_url=args.base_url,
        api_key_env=args.api_key_env, temperature=args.temperature,
        timeout_seconds=args.timeout_seconds, max_retries=args.max_retries),
        scope_mode=args.scope_mode)
    resolver = runner.catalogue_resolver(catalogue, catalogue_dir=args.catalogue_dir)
    try:
        summary = run_experiment_matrix(items, [system], seeds, output,
                                        topology_resolver=resolver)
    except runner.CatalogueError as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1
    off = args.scope_mode == "off"
    print(json.dumps({
        "status": "completed",
        "arm": system.system_name,
        "scope_mode": args.scope_mode,
        "scope_gate": "DISABLED" if off else "ADVISORY, NOT BINDING",
        "policy_version_recorded": ABLATED_POLICY_VERSION if off else None,
        "prompt_version_on_matched_requests": None if off else ADVISORY_PROMPT_VERSION,
        "raw_output": str(output),
        "warning": ("This arm has no independent scope gate and must never be reported "
                    "as the production system." if off else
                    "In this arm the scope gate cannot refuse a request on its own and "
                    "must never be reported as the production system."),
        **summary,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
