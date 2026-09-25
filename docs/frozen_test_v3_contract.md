# Frozen Test v3 contract: interference range equals communication range

Decision (2026-09-11): the scientific scope assumes `dI = d`, so the request
field `interference_ratio` (alpha) is fixed at 1.0. Evidence: running the
archived legacy ANEX code on three topologies (30, 50, and 100 nodes) yields
the same schedule for alpha = 1 and alpha = 2, and that schedule carries
13 / 26 / 69 secondary collisions under `dI = 2d` (11 / 21 / 39 under
`dI = 1.5d`) while being valid under `dI = d`. The legacy implementation
computes `interfereIDs` from `comm_range * alpha` but never reads them; every
collision check uses the communication neighborhood. See
`docs/legacy_compatibility_audit.md` and the secondary analysis in
`results/frozen_test_v2/frozen_test_v2_report.md`.

## Contract profiles in the pipeline

`src/frozen_test_v2/contract.py` now carries two profiles:

| Profile | `interference_ratio` rule | Use |
|---|---|---|
| `frozen-test-v2` | any finite number >= 1.0 | reproduce the reconciliation, decisions, and seal of the sealed Frozen Test v2 |
| `frozen-test-v3` (default) | must equal 1.0; every other explicit value is invalid (REJECT) | Frozen Test v3 and later |

Everything else in the contract is unchanged. With the ratio fixed at 1.0,
`legacy_neighbor` and `interference_range` describe the same collision model;
both literals stay valid so that requests may still name either.

The profile threads through validation, reconciliation, decisions, and
sealing. The worksheet records it as `contract_version`; the lock manifest
records it as both `benchmark_version` and `contract_version`, and the opaque
request ids take the version as prefix (`ft2-rNNNN`, `ft3-rNNNN`). The
harness export copies `benchmark_version` from the sealed manifest.

CLI: every subcommand that reads the four input documents accepts
`--contract frozen-test-v2|frozen-test-v3`. Reprocessing the sealed v2 inputs
without `--contract frozen-test-v2` marks the nine groups that carry a ratio
above 1 as DEFECTIVE_ITEM, which is the v3 reading of those items, not an
error in the tool.

## What this changes for the sealed Frozen Test v2

Nothing in `benchmarks/frozen_test_v2/sealed/` changes. The pipeline sources
did change, so `benchmarks/evaluation_lock_v2.json` now reports mismatches
on the modified pipeline files and tests. The exact v2 pipeline is preserved
in `agentic_anex_frozen_test_v2_source.zip`
(SHA-256 recorded in `benchmarks/frozen_test_v2/pipeline_snapshot.json`), and
the same rules are available through `--contract frozen-test-v2`. Frozen
Test v3 must be sealed under a new evaluation lock that hashes the updated
pipeline.

## What still has to change outside the pipeline

- System boundary: the orchestrator or consistency checker should refuse any
  explicit `interference_ratio` other than 1.0 with an explicit error code
  instead of running ANEX and failing certification. This is a policy-side
  change and belongs in a new lock; it must not be applied to the v2 campaign.
- Generation prompt: `docs/prompts/frozen_test_v3_generator_prompt.txt` is
  the v3 template. Besides the ratio rule it adds three construction rules
  learned from the v2 adjudication: no meta-instructions that name the
  expected action, contradictions must arise naturally, and no narrated
  omissions. The topology section and the 9-groups-per-action quota are
  unchanged; both are open decisions for v3 (multi-topology catalogue and
  protocol stratification).
