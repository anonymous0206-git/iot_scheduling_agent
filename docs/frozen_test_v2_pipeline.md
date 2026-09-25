# Frozen Test v2 reconciliation and sealing pipeline

The `frozen_test_v2` package (under `src/`) turns the two independently
generated benchmark batches and their blind cross-reviews into a sealed
Frozen Test v2. It is a separate top-level package that never imports
`agentic_anex`: no step calls Phi4, ANEX, scope policy v2, or the schedule
validator. All checks are static restatements of the sealed benchmark
contract (`frozen_test_v2/contract.py`).

## Inputs

| Input | Produced by | Notes |
|---|---|---|
| `benchmark_model_A.json` | generator A | 36 semantic groups, two paraphrases each |
| `benchmark_model_B.json` | generator B | same schema, distinct group ids |
| `Model-B blind review of Batch A.json` | reviewer B | `reviewed_batch` must equal batch A's `batch_id` |
| `Model-A blind review of Batch B.json` | reviewer A | `reviewed_batch` must equal batch B's `batch_id` |

A file that carries prose before the JSON object is not valid JSON. The
default loader fails; `--tolerate-leading-prose` extracts the object and
records a `leading_prose` source defect in the worksheet and the lock
manifest. Content after the object is always refused. Nothing is repaired
silently.

## Commands

```bash
uv run python -m frozen_test_v2 validate \
  --batch-a benchmark_model_A.json --review-of-a "Model-B blind review of Batch A.json" \
  --batch-b benchmark_model_B.json --review-of-b "Model-A blind review of Batch B.json" \
  --tolerate-leading-prose
```

```bash
uv run python -m frozen_test_v2 reconcile \
  --batch-a benchmark_model_A.json --review-of-a "Model-B blind review of Batch A.json" \
  --batch-b benchmark_model_B.json --review-of-b "Model-A blind review of Batch B.json" \
  --tolerate-leading-prose --out benchmarks/frozen_test_v2/reconciliation
```

`reconcile` writes `reconciliation_worksheet.json`, a readable
`reconciliation_worksheet.md`, and `human_decisions_template.json`, which
lists every group that needs a decision with all decision fields left empty.

```bash
uv run python -m frozen_test_v2 seal \
  --batch-a benchmark_model_A.json --review-of-a "Model-B blind review of Batch A.json" \
  --batch-b benchmark_model_B.json --review-of-b "Model-A blind review of Batch B.json" \
  --tolerate-leading-prose \
  --decisions benchmarks/frozen_test_v2/human_decisions.json \
  --model-metadata benchmarks/frozen_test_v2/model_metadata.json \
  --prompt generator_prompt=docs/prompts/frozen_test_v2_generator.txt \
  --prompt reviewer_prompt=docs/prompts/frozen_test_v2_reviewer.txt \
  --topology-file legacy30_seed7=network_30_seed7.json \
  --policy-version paper1-scope-policy.v2 \
  --source-commit <commit-or-archive-id> \
  --source-archive agentic_anex_policy_v2_source.zip \
  --out benchmarks/frozen_test_v2/sealed
```

`check-decisions` applies a decisions file in memory and prints exactly what
`seal` would refuse on, without needing the prompt, topology, metadata, or
source-commit inputs and without writing anything:

```bash
uv run python -m frozen_test_v2 check-decisions \
  --batch-a benchmark_model_A.json --review-of-a "Model-B blind review of Batch A.json" \
  --batch-b benchmark_model_B.json --review-of-b "Model-A blind review of Batch B.json" \
  --tolerate-leading-prose --decisions benchmarks/frozen_test_v2/human_decisions.json
```

```bash
uv run python -m frozen_test_v2 verify --sealed-dir benchmarks/frozen_test_v2/sealed
```

Every command prints one JSON object and exits 0 on success or 1 when the
inputs are invalid or sealing is refused.

## Classification

Generator groups and reviewer records are joined by `semantic_group_id`.
Each group receives exactly one class; the first matching rule wins.

| Order | Class | Rule |
|---:|---|---|
| 1 | `DEFECTIVE_ITEM` | structural defect in the generator item (wrong paraphrase count, empty or duplicated text, invalid enum, incomplete or contract-violating EXECUTE gold, REJECT gold whose invalid values the contract does not confirm), missing or malformed reviewer record, or reviewer `item_quality` = `exclude` |
| 2 | `ACTION_DISAGREEMENT` | proposed and adjudicated actions differ |
| 3 | `PARAPHRASE_MISMATCH` | reviewer set `paraphrase_equivalent` to `false` |
| 4 | `FIELD_DISAGREEMENT` | gold fields differ for the agreed action (all ten contract fields for EXECUTE; overlapping explicit values plus the invalid-field name set for REJECT; no structured comparison for CLARIFY or UNSUPPORTED) |
| 5 | `DEFECTIVE_ITEM` | reviewer `item_quality` = `revise` |
| 6 | `FULL_AGREEMENT` | everything above passed |

Numeric representation differences (`18` versus `18.0`) are not
disagreements; booleans are never equal to integers. Duplicate request text
across batches marks both groups defective. Every class other than
`FULL_AGREEMENT` requires a recorded human decision, and the worksheet never
proposes one.

## Human decisions

Fill `human_decisions_template.json` and save it as the decisions file:

```json
{
  "decisions_version": "frozen-test-v2-decisions/1",
  "decided_by": "name",
  "decided_at": "2026-09-09T10:00:00Z",
  "quotas": {"EXECUTE": 18, "CLARIFY": 18, "REJECT": 18, "UNSUPPORTED": 17},
  "quota_rationale": "one UNSUPPORTED group excluded as defective",
  "decisions": [
    {
      "semantic_group_id": "v2-b-021",
      "resolution": "keep_with_edits",
      "final_action": "REJECT",
      "final_fields": {"topology_id": "legacy30_seed7", "channels": 2.5, "seed": 8},
      "final_invalid_fields": {"channels": {"observed": 2.5, "reason": "channels must be an integer"}},
      "paraphrase_equivalent": true,
      "paraphrase_overrides": {"v2-b-021-p2": "rewritten second paraphrase"},
      "rationale": "why this decision was taken"
    },
    {"semantic_group_id": "v2-a-027", "resolution": "exclude", "rationale": "contrived wording"}
  ]
}
```

Rules enforced at seal time:

- every group not in `FULL_AGREEMENT` must have a decision, otherwise sealing
  is refused with the list of unresolved groups;
- a kept group must assert `paraphrase_equivalent: true`, and any text edit
  requires `keep_with_edits` with `paraphrase_overrides`;
- EXECUTE gold must be a complete configuration that satisfies the contract;
  REJECT gold must enumerate `final_invalid_fields` that the contract
  confirms; CLARIFY and UNSUPPORTED carry no invalid fields;
- per-action quotas default to the sum of the generators' declared
  `self_check` counts (18 per action for the two 36-group batches). Any
  deviation must be declared in `quotas` with a `quota_rationale`;
- decisions may also apply to `FULL_AGREEMENT` groups (for example to
  exclude one), and the `context` block copied from the template is ignored.

## Sealed outputs

| File | Content |
|---|---|
| `frozen_test_v2_requests.jsonl` | target-facing: only `request_id` (opaque `ft2-rNNNN`) and `request_text`, in a seeded shuffled order |
| `frozen_test_v2_gold.jsonl` | gold-only: sealed id, source ids, gold action and fields, invalid fields, category, difficulty, reconciliation class, decision source, and the SHA-256 of the request text it labels |
| `frozen_test_v2_reconciliation_worksheet.json` | the reconciliation used for sealing |
| `frozen_test_v2_human_decisions.json` | canonical copy of the applied decisions |
| `frozen_test_v2_lock_manifest.json` | lock manifest (below) plus a `.sha256` sidecar |

Leakage checks run before anything is written and again in `verify`: only the
two allowed keys, opaque ids, no source request or group identifiers in the
text, no action label tokens, no gold schema field names, unique texts, an
order that differs from the generator order, bounded runs of one gold action,
and a text-hash binding between every request and exactly one gold record.

The lock manifest records SHA-256 hashes of every input and output, the
model metadata and roles (A generated batch A and reviewed batch B; B the
reverse), prompt hashes, a `topologies` map holding the hash and properties
of **every** catalogue topology, the policy version, the source commit (from
`--source-commit` or a git checkout given with `--project-root`), optional
source-archive hashes, the shuffle seed, quotas, counts, source defects, the
reconciliation summary, the human decision summary, and the UTC timestamp.
The pipeline refuses to write into a directory that already contains a sealed
benchmark; there is no overwrite flag.

Sealing resolves a file for every topology in the catalogue and refuses if
any is missing, unreadable, inconsistent with its catalogue entry, or (when
the entry declares a `sha256`) changed since the catalogue was built.
`--topology-file` is repeatable and takes `TOPOLOGY_ID=PATH`; a topology not
named there must carry a `path` in its catalogue entry, resolved against
`--catalogue-dir` (the working directory by default). A bare
`--topology-file PATH` is accepted when the catalogue holds a single topology
or `--topology-id` names it. The manifest sealed for Frozen Test v2 predates
this and carries a single `topology` object instead of the `topologies` map.

## Tests

```bash
uv run python -m unittest discover -s tests -p "test_frozen_test_v2_*.py" -v
```

The tests use synthetic fixtures only (`tests/frozen_test_v2_fixtures.py`),
run fully offline, and include a static import check that the package never
imports `agentic_anex` or any network module.
