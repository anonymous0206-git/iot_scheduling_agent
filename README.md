# Artifact: a language agent for one-shot aggregation scheduling

Anonymous artifact for a double-blind submission. It holds the agent, the
sealed 144-request benchmark, every run ledger, and the analysis code, so that
each number in the paper can be re-derived rather than taken on trust.

Author-identifying content has been handled as `README-anonymity.txt` in the
supplementary archive describes; no line of executed code was altered.

## Start here

```bash
python -m pytest tests -q                    # 497 passed, 4 xfailed, 141 subtests
python scripts/verify_release_manifest.py    # valid: true
```

The first runs the deterministic core, the validator, the scope policy, the
sealing pipeline and the analysis scripts. It needs Python 3.10+ and NumPy, and
it calls no language model. In the anonymous archive it reports `497 passed, 2
skipped, 4 xfailed, 139 subtests`: the two skips are the 180-topology catalogue,
which is 18 MB and stays out of a 25 MB archive, and the tests name it rather
than assuming it.

The second checks the artefact against itself: every file this release ships
hashes to what `benchmarks/release_manifest_v5.json` records, no lock in the
chain has been edited since the manifest recorded it, and every divergence
between a lock and this tree is one the manifest declares with a reason. The
locks are historical records and are *not* brought into line with the tree, so
`verify_evaluation_lock.py` on an old lock reports changed files by design;
`docs/artifact_provenance.md` says which changes those are and why, file by
file.

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
arms the same way. `results/frozen_test_v3/analysis_v37/` is that command run
over all eight arms, and is what the paper's table is generated from.

## Where each number in the paper comes from

| In the paper | In this repository |
| --- | --- |
| Table 1, every arm and metric | `results/frozen_test_v3/analysis_v37/summary.json`, rendered by `scripts/render_results_tables.py` |
| Joint intent success, and the per-field and bound-field rates | the same `summary.json`, key `joint_intent_success` |
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
| Table 2, the post-freeze holdout | `results/holdout_v4/analysis_holdout_all/summary.json`, rendered by `scripts/render_holdout_table.py` |
| Section 5.2, the semantic detector against the regex gate | `results/frozen_test_v3/semantic_scope/summary.json`, from `scripts/run_semantic_scope_detector.py` and `analyze_semantic_scope_detector.py` |

## The post-freeze holdout batch

`frozen_test_v3` was reused after the pipeline was repaired, so nothing in it is
held out. `holdout_v4` is a second, smaller batch --- 36 semantic groups, 72
requests --- authored and sealed after that repair, to test whether the mechanism
survives intents the system has never seen. Its protocol was fixed before any
request existed: `docs/holdout_v4_protocol.md` states what would be run, what
would be counted, and, in section 6, what counts in advance as replication and
what counts as a negative result.

It is reported in Section 5.7 of the paper and in Table 2, beside the sealed
benchmark rather than in place of it.

| In the holdout | In this repository |
| --- | --- |
| The protocol, fixed before authoring | `docs/holdout_v4_protocol.md` |
| The batch, its adjudications and the human decisions | `benchmarks/holdout_v4/` |
| The pipeline it was authored against, frozen before any of its requests existed | `benchmarks/evaluation_lock_v4_holdout.json` |
| The batch and its results, pinned by hash | `benchmarks/release_manifest_v5.json`, groups `holdout_batch_v4` and `holdout_results_v4` |
| Every arm, frontier and 14B, against the rule baseline | `results/holdout_v4/analysis_holdout_all/` |
| The frontier arms alone, as first analysed | `results/holdout_v4/analysis_holdout/` |
| The frontier scope-gate ablation | `results/holdout_v4/analysis_holdout_ablation/` |
| The 14B scope-gate ablation | `results/holdout_v4/analysis_abl_phi4_holdout/` |
| The 22 ledgers | `results/holdout_v4/*.jsonl` |
| Serving device, for each of the twelve local runs | `results/holdout_v4/*.device.json` |
| How the batch was sized, and what 36 groups buy | `results/frozen_test_v3/holdout_sizing/` |

Of the three criteria section 6 fixed in advance, two hold and one does not. The
mechanism replicates: the gate's recall on unsupported requests is 14 of 20 where
the request names the capability and 0 of 16 where it composes it from ordinary
words, and the ungated frontier agent catches 15 of those 16. Over-blocking
replicates: the gate short-circuits 7 of 24 gold-`EXECUTE` requests, and the
ungated frontier arm answers all 7 correctly in all three repeats. The ablation
does not: the 14B point estimate is negative, which section 6 fixed in advance as
a negative result. Section 4 had already put that contrast out of reach at any
feasible batch size, so it is an underpowered comparison landing on the wrong
side of zero rather than evidence against the effect. Not pre-registered, and
reported because it is there: every 14B arm scores below the rule baseline on
action accuracy, while cutting false acceptance by about a third.

Separately, the harness numbers its requests `ft3-r0001` to `ft3-r0072` and still
carries `benchmark_version: frozen-test-v3`, so all 72 identifiers collide with
`frozen_test_v3`'s while naming different requests. The cause is that
`sealed_id_prefix` in `src/frozen_test_v2/seal.py` derives the prefix from the
version string, and this batch was sealed under the same contract profile, so it
inherited the same numbering space; the authored batches themselves are prefixed
`h4-`, and only `paraphrase_group_id` kept it. Each analysis pairs one harness
with ledgers produced from that harness, so no number above is affected, but
pairing these ledgers with the frozen harness reported a plausible accuracy
instead of an error, because every identifier resolved.

`scripts/analyze_frozen_test_results.py` now refuses that pairing, by checking
that the ledger and the harness agree on the fields naming the request rather
than the run. The check was added after this experiment closed: every number
reported here was produced by the version the lock records, and that one file's
hash in `evaluation_lock_v4_holdout.json` is superseded by this change. The
identifiers themselves are left alone. The prefix is derived from the contract
version by `sealed_id_prefix` in `src/frozen_test_v2/seal.py`, so renumbering means
changing that file --- one of the 98 `evaluation_lock_v4_holdout.json` pins --- and
under section 2 of the protocol a change to a covered file restarts the experiment.
The lock covers no `holdout_v4` path itself, having been issued before the batch
existed; it is the sealing code that is locked, not the sealed files.

The check changes no result, and that is checkable rather than asserted:
re-running either campaign's analysis with the current script reproduces the
shipped summary exactly, differing only in the `--title` string. Both tables in
the paper are generated from those summaries rather than typed:
`paper/aamas2027/render_table1.sh` and `render_holdout_table.sh` rebuild them,
and they carry the captions and arm labels, which are command-line arguments.

## The semantic detector of Section 5.2

Section 5.2 shows the shipped scope gate's recall following the phrasing: 11 of
the 26 unsupported requests that name the capability, none of the 46 that compose
it. The obvious objection is that this says more about that regex than about scope
gating, so we measured a second detector aimed at the same closed taxonomy and
asked the same question --- a detector against a detector, with no pipeline arm.

```bash
OPENAI_API_KEY=... python scripts/run_semantic_scope_detector.py \
  --harness benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl \
  --out results/frozen_test_v3/semantic_scope \
  --model gpt-5.5-2026-04-23 --temperature 1 --seeds 11 12 13

python scripts/analyze_semantic_scope_detector.py \
  --ledger-dir results/frozen_test_v3/semantic_scope \
  --harness benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl \
  --phrasing paper/aamas2027/figure_data/fig2_phrasing.json \
  --out results/frozen_test_v3/semantic_scope
```

The second command calls no model and reproduces the summary from the shipped
ledgers. Over three repeats the semantic detector refuses all 72 unsupported
requests, 46 of 46 where the capability is composed, and over-blocks a mean 0.67
of the 7 gold-`EXECUTE` requests the regex blocks --- all seven of which it reads
correctly in every repeat. Its own single over-block is `ft3-r0034`, a latency
target read as an unsupported objective, in two repeats of three.

`prompt.txt` in that directory is the question as rendered, with the response
schema and the exact model snapshot; the three ledgers carry one verdict per
request per repeat, the regex verdict on the same text beside it, and the token
and latency metadata of every call.

Two things make the comparison fair rather than flattering, and both are in the
runner: the question put to the model is generated from `_RULES` in
`scope_policy.py`, so the two detectors are aimed at the same taxonomy by
construction; and the model is told the rule the gold labels encode and the regex
cannot express, that a request mentioning an out-of-scope concept while asking for
a supported one is in scope. Without the second, the seven hard negatives would be
counted against it for a distinction it was never asked to make.

What it costs is a model call per request, on the one stage that exists to decide
before any model is called: 432 calls, 323,116 tokens and 18 minutes for the three
repeats, recorded in `run_report.json`.

## Provenance: the locks, the manifest, and what differs

Two kinds of manifest live in `benchmarks/`, and they answer different
questions.

A **lock** records the bytes that produced one set of results, and is never
edited --- a manifest brought into line with the tree whenever the tree moves
records nothing. There are seven, from `evaluation_lock_v1.json` on 2026-08-31
to `evaluation_lock_v4_holdout.json` on 2026-09-27, each superseding the one
before. Running the lock verifier against an old one reports changed files, by
design:

```bash
python scripts/verify_evaluation_lock.py --lock benchmarks/evaluation_lock_v3.json
```

The **release manifest**, `benchmarks/release_manifest_v5.json`, is the other
half of that record. It pins every file this release ships --- including the
`holdout_v4` batch and the ledgers both tables are generated from, which no lock
covered --- and states every divergence from every lock: the two hashes, the
dated revision, the reason, and the lock that pins the current bytes where one
does. Fourteen files diverge, for four reasons: the frozen-test-v3 sealing
pipeline, the Section 5.5 repair and the scope-mode parameter of Sections 5.2
and 5.3, runners and analysis that cannot reach a recorded run, and
documentation. Three of the fourteen are reached by no lock, and this manifest
is what pins them.

`docs/artifact_provenance.md` is that file by file, in prose. The manifest is
generated by `scripts/build_release_manifest.py`, which refuses to write it when
the declarations and the tree disagree in either direction, so the explanation
cannot drift from the bytes it explains. Nothing in the chain was rewritten to
make a hash agree; `verify_release_manifest.py` checks that too, by pinning each
lock by its own hash.

## Trying it by hand

`scripts/demo_agent.py` is an interactive prompt on the same pipeline the
experiments run: the same scope policy, the same topology-binding rule, the same
independent validator. Type a request, watch which stage decides it.

```bash
python scripts/demo_agent.py --provider mock                     # no model, dry run
python scripts/demo_agent.py --provider ollama --model phi4:14b  # a local model
OPENAI_API_KEY=... python scripts/demo_agent.py \
    --provider openai --model gpt-5.5-2026-04-23                 # the frontier arm
```

It prints, per request, the action, **which stage decided it**, what the scope
detector matched, the parsed contract fields, the schedule and whether the
independent validator accepted it. The stage is read from evidence --- whether
the model was called at all, and the error code --- rather than guessed from the
action, because an `UNSUPPORTED` answer from the gate and one from the model look
identical in the answer alone, and telling them apart is what Section 5.5 is
about.

`:mode off` and `:mode advisory` move the gate's authority mid-session, which
runs the ablation of Sections 5.2 and 5.3 by hand on whatever you just typed.
`:examples` lists requests that reach each outcome, including two the gate misses
because they describe an out-of-scope capability without naming it. `--visualize
DIR` writes an interactive HTML schedule for each successful run, and `--open`
opens each one as it is written (through `explorer.exe` under WSL, where
`xdg-open` reports success and opens nothing).

Every successful run also prints the schedule as a grid in the terminal, one row
per channel and one column per slot, each cell the number of transmissions that
channel carries in that slot. A cell above one is the scheduler reusing a slot
between senders that do not interfere, which is the property the independent
validator certifies rather than a conflict.

A request binds a topology only by naming its catalogue identifier exactly, as a
whole word (Section 4.1), so `:topologies` is worth reading first. The default
catalogue is the benchmark's seven, and those seven topology files are here.
`--catalogue benchmarks/topologies/fixed_area100_r20/catalogue.json` offers all
180, thirty seeds at each of six sizes, and that directory is 18 MB, so it is in
the repository and not in the anonymous archive; `scripts/build_topology_catalogue.py`
regenerates it from the seeds.

One practical note for a live demo: `phi4:14b` reliably misreads the two-digit
seed in an identifier like `topo50_seed10` as a request for `seed=10` and refuses
the request, while `topo50_seed0` and `legacy30_seed7` execute. The demo reports
that as the model's decision, which is what it is --- but if you want a schedule
on the screen rather than a 14B failure, name a `_seed0` topology or use the
frontier arm.

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
  writes one ledger per seed;
* `scripts/run_holdout_local_arms.sh` runs the holdout's twelve local runs ---
  `phi4:14b` in three gate modes and `qwen2.5:14b` enforcing, three seeds each
  --- and re-checks GPU residency before each one, because a CPU-served run
  answers every request correctly and reports every timing wrong.

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
paper/        the figure data behind Figures 2 and 3
```

## What is not here

No PDF of the paper, in either build: a supplement may carry experimental
detail and proofs, not an extended version of the submission. Also absent are
model weights, API keys, and the parts of the ANEX source tree the agent does
not import. `docs/development_notes.md` keeps the earlier
milestone notes; where they disagree with the paper, the paper is current.
