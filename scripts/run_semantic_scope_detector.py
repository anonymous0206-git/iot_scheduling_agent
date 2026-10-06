#!/usr/bin/env python3
"""Run a semantic scope detector over the sealed requests, as a detector only.

Section 5.2 measures one scope gate: case-insensitive regular expressions. Its
recall turns out to be a property of the phrasing --- 11 of the 26 unsupported
requests that name the capability, none of the 46 that compose it from ordinary
words --- and the obvious objection is that this says more about that regex than
about scope gating. This script answers the detector half of that objection
without building a pipeline arm: it asks a language model the same question the
regex is asking, over the same 144 requests, and records only its verdict.

Nothing downstream runs. There is no scheduler call, no agent, no ledger of
actions, and so no new arm and no change to `orchestration.py`: this measures a
detector against a detector, which is what the phrasing claim is about. A
pipeline arm would also have to be sealed under a new lock and reported beside
the existing ones, and it would answer a different question --- what the gate is
worth --- which Sections 5.2 and 5.3 already answer for the detector we shipped.

The question put to the model is built from `_RULES` in `scope_policy.py`, so the
two detectors are aimed at the same closed taxonomy by construction and the
prompt cannot drift from the regex's target. The model is also told the rule the
gold labels encode and the regex cannot express: a request that *mentions* an
out-of-scope concept while asking for something supported is in scope. Without
that the comparison would hand the model a harder question than the regex is
asked, and the seven hard negatives would be counted against it unfairly.

    OPENAI_API_KEY=... scripts/run_semantic_scope_detector.py \
        --harness benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl \
        --out results/frozen_test_v3/semantic_scope/ \
        --model gpt-5.5-2026-04-23 --temperature 1 --seeds 11 12 13
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentic_anex.llm_clients.base import LLMClientError  # noqa: E402
from agentic_anex.llm_clients.factory import ProviderConfig, create_llm_client  # noqa: E402
from agentic_anex.scope_policy import (  # noqa: E402
    CHECKED_TAXONOMY, SCOPE_POLICY_VERSION, _RULES, evaluate_scope_policy,
)

DETECTOR_VERSION = "paper1-semantic-scope-detector.v1"

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "in_scope": {
            "type": "boolean",
            "description": "true when the request asks only for capabilities the "
                           "system has; false when it asks for one of the listed "
                           "out-of-scope capabilities.",
        },
        "categories": {
            "type": "array",
            "items": {"type": "string", "enum": list(CHECKED_TAXONOMY)},
            "description": "The out-of-scope categories the request asks for. "
                           "Empty when in_scope is true.",
        },
        "evidence": {
            "type": "string",
            "description": "The words in the request that decided it, quoted.",
        },
    },
    "required": ["in_scope", "categories", "evidence"],
    "additionalProperties": False,
}


def taxonomy_block() -> str:
    """The seven categories, worded as the regex rules word them.

    Read off `_RULES` rather than retyped, so a change to the policy cannot
    leave the two detectors aimed at different things.
    """
    lines = []
    for category in CHECKED_TAXONOMY:
        messages = []
        for rule in _RULES:
            if rule.category == category and rule.message not in messages:
                messages.append(rule.message)
        lines.append(f"- {category}: " + " ".join(messages))
    return "\n".join(lines)


def prompt_for(user_text: str) -> str:
    return (
        f"DETECTOR_VERSION={DETECTOR_VERSION}\n"
        f"TAXONOMY_OF={SCOPE_POLICY_VERSION}\n\n"
        "You are a scope detector for a one-shot data-aggregation scheduler for "
        "multi-hop wireless networks. The system computes a single collision-free "
        "aggregation schedule that minimises elapsed latency on a fixed, static "
        "topology bound from a catalogue, and reports it. That is all it does.\n\n"
        "These capabilities are outside it:\n"
        f"{taxonomy_block()}\n\n"
        "Decide whether the request below asks the system to do something in one "
        "of those categories.\n\n"
        "Two rules bound the decision:\n"
        "- It is what the request ASKS FOR that matters. A request that merely "
        "mentions, names or rules out an out-of-scope concept while asking for a "
        "supported one-shot schedule is IN SCOPE.\n"
        "- A request can ask for an out-of-scope capability without naming it, in "
        "ordinary words. Judge the meaning, not the vocabulary.\n\n"
        "Say nothing about whether the request's parameters are legal, whether a "
        "topology is named, or whether anything is ambiguous. Those are other "
        "stages' decisions. Only scope.\n\n"
        f"REQUEST:\n{user_text}\n"
    )


def _under_root(path: Path) -> str:
    """Repository-relative where possible; a smoke run may write to /tmp."""
    return (path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT)
            else str(path))


def load_harness(path: Path) -> list[dict[str, Any]]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    if not items:
        raise SystemExit(f"{path}: no requests")
    return items


def run_seed(client, items, seed: int, out_path: Path) -> dict[str, Any]:
    calls = failures = 0
    tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    started = time.monotonic()
    with out_path.open("w", encoding="utf-8") as ledger:
        for index, item in enumerate(items, 1):
            text = str(item["user_text"])
            record: dict[str, Any] = {
                "ledger_format": "agentic_anex.semantic_scope.v1",
                "detector_version": DETECTOR_VERSION,
                "seed": seed,
                "request_id": item["request_id"],
                "paraphrase_group_id": item.get("paraphrase_group_id"),
                "gold_action": item["gold_action"],
                "category": item.get("category"),
            }
            # The regex verdict on the same text, recorded beside the model's so
            # the comparison needs no second pass and cannot be mispaired.
            regex = evaluate_scope_policy(text)
            record["regex_in_scope"] = regex.supported
            record["regex_categories"] = sorted({v.category for v in regex.violations})
            try:
                response = client.generate_structured(
                    prompt=prompt_for(text), response_schema=RESPONSE_SCHEMA)
            except LLMClientError as exc:
                failures += 1
                record["error_code"] = exc.code
                record["error"] = str(exc)
            else:
                calls += 1
                structured = dict(response.structured_output)
                record["semantic_in_scope"] = bool(structured.get("in_scope"))
                record["semantic_categories"] = sorted(structured.get("categories") or ())
                record["semantic_evidence"] = structured.get("evidence")
                meta = dict(response.model_metadata)
                record["model_metadata"] = meta
                for name in tokens:
                    if isinstance(meta.get(name), (int, float)):
                        tokens[name] += meta[name]
            ledger.write(json.dumps(record, sort_keys=True) + "\n")
            if index % 24 == 0:
                print(f"  seed {seed}: {index}/{len(items)}", file=sys.stderr, flush=True)
    return {"seed": seed, "ledger": out_path.name, "calls": calls,
            "client_failures": failures,
            "wall_seconds": round(time.monotonic() - started, 1), **tokens}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--out", required=True, help="directory for the ledgers")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", default="gpt-5.5-2026-04-23")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    # The frontier model rejects anything but 1 at the transport layer, which is
    # why its arms sample where the local arms do not (Section 4.6).
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--seeds", type=int, nargs="+", default=[11, 12, 13])
    parser.add_argument("--limit", type=int, default=None,
                        help="run only the first N requests, for a smoke test")
    args = parser.parse_args()

    harness = Path(args.harness)
    if not harness.is_absolute():
        harness = ROOT / harness
    items = load_harness(harness)
    if args.limit:
        items = items[: args.limit]

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    for seed in args.seeds:
        config = ProviderConfig(
            provider=args.provider, model=args.model, base_url=args.base_url,
            api_key_env=args.api_key_env, temperature=args.temperature,
            timeout_seconds=args.timeout_seconds, max_retries=0, seed=seed)
        client = create_llm_client(config)
        ledger = out_dir / f"semantic_scope_seed{seed}.jsonl"
        runs.append(run_seed(client, items, seed, ledger))

    report = {
        "status": "run",
        "detector_version": DETECTOR_VERSION,
        "taxonomy_of": SCOPE_POLICY_VERSION,
        "model": args.model,
        "temperature": args.temperature,
        "harness": _under_root(harness),
        "requests": len(items),
        "output_dir": _under_root(out_dir),
        "runs": runs,
        "totals": {
            name: sum(run[name] for run in runs)
            for name in ("calls", "client_failures", "prompt_tokens",
                         "completion_tokens", "total_tokens", "wall_seconds")
        },
    }
    (out_dir / "run_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not report["totals"]["client_failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
