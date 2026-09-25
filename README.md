# Artifact: a language agent for one-shot aggregation scheduling

Anonymous artifact for a double-blind submission. It holds the agent, the
sealed 144-request benchmark, every run ledger, and the analysis code, so that
each number in the paper can be re-derived rather than taken on trust.

Author-identifying content has been handled as `README-anonymity.txt` in the
supplementary archive describes; no line of executed code was altered.

## Start here

```bash
python -m pytest tests -q          # 443 passed, 4 xfailed, 115 subtests
```

That runs the deterministic core, the validator, the scope policy, the sealing
pipeline and the analysis scripts. It needs Python 3.10+ and NumPy, and it calls
no language model.

Re-derive the paper's headline table from the shipped ledgers, again with no
model in the loop:

```bash
python scripts/analyze_frozen_test_results.py \
  --harness benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl \
  --ledger gpt55_gated=results/frozen_test_v3/gpt55_policy_v2_seed11.jsonl \
  --ledger gpt55_gated=results/frozen_test_v3/gpt55_policy_v2_seed12.jsonl \
  --ledger gpt55_gated=results/frozen_test_v3/gpt55_policy_v2_seed13.jsonl \
  --baseline gpt55_gated --output-dir /tmp/check
```

Repeating `--ledger` with one name declares repeats of one arm; add the other
arms the same way. `results/frozen_test_v3/analysis_v36/` is that command run
over all eight arms, and is what the paper's table is generated from.

## Where each number in the paper comes from

| In the paper | In this repository |
| --- | --- |
| Table 1, every arm and metric | `results/frozen_test_v3/analysis_v36/summary.json`, rendered by `scripts/render_results_tables.py` |
| Scope-gate ablation, 14B and frontier | `results/frozen_test_v3/analysis_abl_phi4_final/`, `analysis_abl_gpt_final/` |
| Advisory gate, all four intervals | `analysis_advisory_phi4/`, `analysis_advisory_phi4_vs_off/`, `analysis_advisory_gpt/`, `analysis_advisory_gpt_vs_off/` |
| Sensitivity to the contested gold labels | `results/frozen_test_v3/sensitivity_labels/summary.md`, produced by `scripts/sensitivity_gold_labels.py` |
| 945 validator mutants, 0 survivors | `results/validator_mutation/mutation.json`, produced by `scripts/run_validator_mutation_test.py` |
| Direct generation, 11 of 23 valid, 789× | `results/frozen_test_v3/analysis_b2/direct_generation.json` over `b2_direct_generation.jsonl`; run by `scripts/run_direct_generation_baseline.py` |
| Deterministic core at 30–300 nodes | `results/topology_scaling/` |
| Figure 2, one request end to end | `paper/aamas2027/figure_data/fig6_trace.json` |
| Figure 3, recall split by phrasing | `paper/aamas2027/figure_data/fig2_phrasing.json` |
| The seven unsupported capabilities and their patterns | `src/agentic_anex/scope_policy.py` |
| The seven contract fields and their defaults | `DEFAULT_FIELDS` in `src/frozen_test_v2/contract.py` |
| The benchmark, its gold labels and its hashes | `benchmarks/frozen_test_v3/` and `benchmarks/evaluation_lock_v3*.json` |
| Who authored and adjudicated each batch | `benchmarks/frozen_test_v3/model_metadata.json`, `generation_provenance.json`, `frozen_test_v3_authoring_lock.json` |
| The pipeline repair, before and after | pre-repair `gpt55_policy_v2_seed1.jsonl` and `gpt55_no_scope_gate_seed1.jsonl`; post-repair `*_seed11`, `*_seed12`, `*_seed13` |
| Serving device per timed run | `results/frozen_test_v3/*.device.json` |
| The unabridged build, with the worked schedule | `paper/aamas2027/main-full.pdf` |

## Re-running the experiments themselves

The ledgers above are the record of runs that did call models, so the whole
analysis reproduces without one. To run the agent instead of reading its
ledgers:

* local arms need [Ollama](https://ollama.com) serving `phi4:14b` or
  `qwen2.5:14b`; `scripts/preflight_ollama_arm.py` checks the server, the model
  digest and the serving device before a timed run;
* the frontier arm needs an OpenAI API key in `OPENAI_API_KEY`;
  `scripts/preflight_openai_arm.py` checks the model and the strict-schema mode
  the run will negotiate;
* `scripts/run_frozen_test_v3_seed_campaign.py` runs one arm three times and
  writes one ledger per seed.

A re-run will not reproduce the ledgers item for item: the frontier model is
sampled at temperature 1 because the provider accepts nothing else, and the
paper reports the spread that causes.

## Layout

```
benchmarks/   the sealed benchmark, gold labels, locks, authoring provenance
docs/         the request contract, the protocol, the authoring prompts
results/      every ledger, the analyses, the mutation and scaling artefacts
scripts/      experiment runners, analysis, figure and table generation
source/       the published ANEX scheduler the agent wraps, unmodified
src/          the agent: policy, orchestration, validator, sealing pipeline
tests/        the suite the first command runs
paper/        figure data and the unabridged build
```

## What is not here

The submitted PDF, model weights, API keys, and the parts of the ANEX source
tree the agent does not import. `docs/development_notes.md` keeps the earlier
milestone notes; where they disagree with the paper, the paper is current.
