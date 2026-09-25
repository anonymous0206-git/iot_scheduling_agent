# Running the Frozen Test v2 evaluation

This guide starts where `docs/frozen_test_v2_pipeline.md` ends: the benchmark
is sealed in `benchmarks/frozen_test_v2/sealed/` and locked by
`benchmarks/evaluation_lock_v2.json`. All commands run in WSL from the
project root.

## 1. Verify the locks before touching any model

```bash
uv run python scripts/verify_evaluation_lock.py --lock benchmarks/evaluation_lock_v2.json
uv run python -m frozen_test_v2 verify --sealed-dir benchmarks/frozen_test_v2/sealed
```

Both must report `valid: true`. Re-run them after the campaign; any mismatch
invalidates comparability.

## 2. Export the evaluator-side harness file

`scripts/run_experiments.py` needs items with `user_text`, `topology_id`,
`paraphrase_group_id`, `gold_action`, `category`, and `complexity_level`. The
sealed requests file deliberately has none of the label fields, so the
evaluator joins it with the gold file:

```bash
uv run python scripts/export_frozen_test_v2_harness.py \
  --sealed-dir benchmarks/frozen_test_v2/sealed \
  --output benchmarks/frozen_test_v2/harness/frozen_test_v2_harness.jsonl
```

The script verifies the sealed directory, checks every request against its
gold text hash, writes the file once, and records source hashes in
`frozen_test_v2_harness.jsonl.manifest.json`. The output carries gold labels
and stays on the evaluator side; the system under test only ever sees the
text and the bound network.

Topology binding rule: a request gets `topology_id: "legacy30_seed7"` when
that id appears as a whole token in its text, and `null` otherwise. Requests
that name a topology outside the catalogue (`legacy30_seed8`,
`legacy50_seed3`) get no network, because no such network exists; the
orchestrator will answer those with a deterministic CLARIFY before any model
call while the sealed gold says REJECT. That is a property of the system
under test relative to the contract, so report it as a finding and do not
edit the gold. The export summary lists the affected request ids.

## 3. Run the systems

Rule-based baseline (no model):

```bash
uv run python scripts/run_experiments.py \
  --benchmark benchmarks/frozen_test_v2/harness/frozen_test_v2_harness.jsonl \
  --raw-output results/frozen_test_v2/rule_based.jsonl \
  --systems rule_based --seeds 0
```

Primary system, Phi4 with scope policy v2 (locked settings: seed 0,
temperature 0, at most two retries). Confirm the Ollama digest matches the
lock before starting (`ollama show phi4:14b`):

```bash
uv run python scripts/run_experiments.py \
  --benchmark benchmarks/frozen_test_v2/harness/frozen_test_v2_harness.jsonl \
  --raw-output results/frozen_test_v2/phi4_policy_v2.jsonl \
  --systems llm_agent --provider ollama --model phi4:14b \
  --temperature 0 --max-retries 2 --timeout-seconds 600 --seeds 0
```

Optional comparison model:

```bash
uv run python scripts/run_experiments.py \
  --benchmark benchmarks/frozen_test_v2/harness/frozen_test_v2_harness.jsonl \
  --raw-output results/frozen_test_v2/qwen25_policy_v2.jsonl \
  --systems llm_agent --provider ollama --model qwen2.5:14b \
  --temperature 0 --max-retries 2 --timeout-seconds 600 --seeds 0
```

The ledgers are append-only and resumable: rerunning the same command skips
completed keys and never overwrites a record. A provider timeout is stored as
a completed failure, so check that `ollama serve` is up before a long run.

Safety ablation (Phi4 without the independent scope gate): the runner exposes
only `rule_based` and `llm_agent`, and `llm_agent` always applies policy v2
inside the orchestrator. Running the ablation therefore needs an explicitly
named experiment configuration added to the runner first; it must never
become the default. `scripts/replay_locked_policy.py` can replay the v1 and
v2 gates over a finished ledger, but it cannot show what the model would have
done on requests the gate blocked, so it is not a substitute for that run.

## 4. Summarize and compare

```bash
uv run python scripts/summarize_experiments.py \
  --raw results/frozen_test_v2/phi4_policy_v2.jsonl \
  --output results/frozen_test_v2/phi4_policy_v2_summary.csv
```

```bash
uv run python scripts/compare_experiments.py \
  --raw results/frozen_test_v2/phi4_policy_v2.jsonl \
  --baseline rule_based:deterministic --candidate llm_agent:phi4:14b \
  --metric action_accuracy
```

`compare_experiments.py` pairs records by request, topology, and seed, so
both arms must be present in the ledger given to `--raw`; concatenate the
rule-based and model ledgers into one file for the comparison if they were
written separately. Repeat with `--metric success` for task completion.

## 5. After opening the results

Do not modify the prompt, the scope policy, the consistency checker, the
sealed files, the harness file, or the human decisions. Any follow-up change
belongs in a new lock and a new sealed directory.
