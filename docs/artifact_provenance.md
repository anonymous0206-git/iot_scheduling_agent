# Artifact provenance: the lock chain, and why it does not match this tree

Run the lock verifier against any lock in this repository and it reports files
that changed:

```bash
python scripts/verify_evaluation_lock.py --lock benchmarks/evaluation_lock_v3.json
```

That is the expected answer, and this document is why. A lock records the bytes
that produced one set of results. It is never edited, because a manifest brought
into line with the tree whenever the tree moves records nothing. So every lock
older than the current pipeline disagrees with the current pipeline, and a reader
who is not told which disagreements are expected cannot tell them from tampering.

The record has two halves:

* **the locks**, in `benchmarks/`, each the state of the pipeline at one moment,
  unedited;
* **the release manifest**, `benchmarks/release_manifest_v5.json`, which pins
  every file this release ships and states every divergence from every lock ---
  the two hashes, the reason, the dated revision, and the lock that pins the
  current bytes where one does.

One command checks all of it:

```bash
python scripts/verify_release_manifest.py     # valid: true
```

It fails on a bad hash, on a lock that has been edited since the manifest
recorded it, on a file that diverges from a lock with no reason on record, and on
a declaration that is no longer true. The manifest is generated, not written, by
`scripts/build_release_manifest.py`, which refuses to write it if the
declarations and the tree disagree in either direction --- so the explanation
cannot drift away from the bytes it explains.
`tests/test_release_manifest.py` is that property under test, including the one
thing a lock must never do: move to agree with the tree.

## The chain

| Lock | Issued | What it froze |
| --- | --- | --- |
| `evaluation_lock_v1.json` | 2026-08-31 | the first evaluation |
| `policy_v2_development_lock.json` | 2026-09-01 | the scope policy, before the independent frozen-test-v2 |
| `evaluation_lock_v2.json` | 2026-09-09 | frozen-test-v2, sealed and opened |
| `frozen_test_v3_authoring_lock.json` | 2026-09-14 | the pipeline, contract, catalogue and prompts, before any v3 request existed |
| `evaluation_lock_v3.json` | 2026-09-14 | frozen-test-v3 sealed; evaluation may begin |
| `evaluation_lock_v3_1.json` | 2026-09-16 | the pipeline as repaired |
| `evaluation_lock_v4_holdout.json` | 2026-09-27 | the repaired pipeline, before any holdout request existed |
| `release_manifest_v5.json` | this release | every file shipped, and every divergence above |

The manifest continues the chain without editing it. `evaluation_lock_v4_holdout.json`
remains the last lock, and the results in the paper remain the results of the
pipeline it records.

## Every divergence, and why

Fourteen released files differ from a hash some earlier lock published. There are
four reasons, and `divergences_from_the_lock_chain` in the manifest gives the per
file detail.

**1. The frozen-test-v3 sealing pipeline** --- `src/frozen_test_v2/seal.py`,
`contract.py`, `cli.py`, `decisions.py`, `reconcile.py`, `schemas.py` and
`docs/frozen_test_v2_pipeline.md` differ from `evaluation_lock_v2.json`, which
predates v3. The v3 authoring lock and every lock after it pin the current bytes,
which is why the sealed v3 files verify.

**2. The pipeline repair of Section 5.3 and the scope-mode parameter of Sections
5.2 and 5.3** --- `src/agentic_anex/orchestration.py` and `experiments.py`, changed
on 2026-09-21, and `scripts/run_scope_gate_ablation.py` with them. The repair
makes a strict structured-output mode's nulls mean "not stated" for the four
fields that carry a contract default, which is what made the `CLARIFY` capability
measurable at all. The parameter makes stage 1's authority --- enforcing, advisory,
off --- a setting rather than three pipelines. The detector itself is unchanged.
`evaluation_lock_v4_holdout.json` pins the current bytes and its
`pipeline_revision` block carries the before-and-after hash of each file.

**3. Runners and analysis, which cannot reach a recorded run** ---
`scripts/run_frozen_test_v3_seed_campaign.py` changed on 2026-09-22 while the
campaign ran, and `scripts/analyze_frozen_test_results.py` on 2026-09-26 and
again on 2026-09-29. The ledgers are append-only and each records the arm, the
seed and the model digest it ran under; the analysis reads ledgers and writes
summaries.

The 2026-09-29 change is the one worth stating plainly, because it post-dates
every number in the paper. `holdout_v4` inherited `frozen_test_v3`'s `ft3-rNNNN`
numbering from `sealed_id_prefix`, so all 72 identifiers collide while naming
different requests, and pairing the holdout's ledgers with the frozen harness
used to report a plausible accuracy instead of an error. The analysis now refuses
that pairing. No analysis in the paper used it --- each pairs one harness with
ledgers produced from that harness --- and re-running both campaigns' analyses with
the check in place reproduces the shipped summaries exactly:

```bash
# Table 1
python scripts/analyze_frozen_test_results.py \
  --harness benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl \
  --ledger ... --baseline rule_based --output-dir /tmp/recheck
diff <(jq -S . results/frozen_test_v3/analysis_v37/summary.json) \
     <(jq -S . /tmp/recheck/summary.json)        # differs only in "title"
```

The identifiers are left as they are. The prefix comes from `sealed_id_prefix` in
`src/frozen_test_v2/seal.py`, which is one of the 98 files
`evaluation_lock_v4_holdout.json` pins, and section 2 of `holdout_v4_protocol.md`
restarts the experiment on a change to a covered file. That lock covers no
`holdout_v4` path of its own --- it was issued before the batch existed --- so the
constraint runs through the sealing code rather than through the sealed files.

**4. Documentation, read by no code** --- `README.md` and
`docs/operator_guide.md`. The locks that cover them were issued on 2026-09-01 and
2026-09-14; the operator guide was revised on 2026-09-21 with the scope-mode
runners, and the README describes this release.

Three of the fourteen have no lock after them: `README.md`,
`docs/operator_guide.md` and `scripts/analyze_frozen_test_results.py`. The
manifest is what pins those, and `files_pinned_by_this_manifest_alone` names
them.

## What no lock covered, and now does

The locks pin inputs and code. Until this release nothing pinned the evidence:
the ledgers both tables are generated from, the analyses, and the whole
`holdout_v4` batch. `evaluation_lock_v4_holdout.json` was issued before any
holdout request existed --- correctly, that is the point of it --- so it pins the
pipeline and not the batch.

The release manifest closes that. It covers every file the release ships, among
them:

| Group | What it pins |
| --- | --- |
| `holdout_batch_v4` | both authored halves, both blind copies, the adjudications, the revision round, the human decisions, the sealed files and the harness |
| `holdout_results_v4` | the 22 ledgers, the 12 device records, the four analyses, and the sizing calculation |
| `sealed_benchmark_results_v3` | every frozen-test-v3 ledger, including the pre-repair ones, and every analysis directory |
| `sealed_benchmark_frozen_test_v3` | the sealed benchmark, its gold labels and its authoring provenance |
| `lock_chain` | all seven locks, each by its own hash |

## What the release still leaves out

Running `verify_evaluation_lock.py` against the newest lock reports four files
absent. They are the whole of it, and the manifest lists each one:

| Absent | Why |
| --- | --- |
| `agentic_anex_policy_v2_source.zip`, `agentic_anex_frozen_test_v2_source.zip` | source snapshots of the pre-v3 pipeline. They are what pins the bytes `evaluation_lock_v1` and `v2` recorded, and they are archives of a working copy, so they are withheld for anonymity and will be in the archival release. |
| `benchmarks/topologies/fixed_area100_r20/catalogue.json` | the index of 180 topologies whose files are 18 MB. The six the benchmark binds are here; `scripts/build_topology_catalogue.py` regenerates the rest from the seeds, and the tests skip this file by name rather than assuming it. |
| `benchmarks/frozen_test_v3/sealed/frozen_test_v2_lock_manifest.json` | carries the working copy's absolute path *and* has its hash published by a lock, so it is omitted rather than rewritten. See below. |

Everything else a lock covers is here. The earlier locks reach further back ---
`evaluation_lock_v2` covers the frozen-test-v2 benchmark, which this release
does not carry --- and `lock_covered_files_not_shipped` in the manifest names
those too, each with the hash the repository holds.

## One stale pointer, left stale on purpose

`docs/holdout_v4_protocol.md` says "Section 4.4 of the paper discloses this". That
was the disclosure subsection's number when the protocol was written, on
2026-09-27, before any holdout request existed. The submission later merged several
one-paragraph subsections and the disclosure became Section 4.2.

The protocol is a pre-registration. Its own section 2 says it is superseded rather
than edited, and editing a dated commitment so that a cross-reference into a
document written afterwards still resolves is the kind of quiet retrofit the lock
discipline exists to prevent. So the pointer stays as written and is recorded here
instead: read it as the paper's disclosure subsection, Section 4.2 in the current
build. Nothing the protocol commits to has changed.

## The anonymous archive

`scripts/build_supplementary.py` packages the release for double-blind review and
prints what it changed. Two kinds of member differ from this manifest, and
`README-anonymity.txt` inside the archive lists both by name:

* **redacted** --- an absolute path carrying a username, replaced by
  `<repository>`, and in the legacy scheduler sources a docstring naming its
  programmer and institution, replaced by a neutral line. No lock publishes a
  hash of these files, and no line of executed code is touched.
* **withheld** --- files that carry that path *and* whose SHA-256 a lock publishes.
  Editing them would produce a member that does not match its recorded hash,
  which is worse to hand a reviewer than an absent file, so they are omitted and
  will be included unaltered in the archival release.

The hashes in the manifest are the repository's own bytes. A reviewer verifying
the archive rather than the repository should expect exactly the members
`README-anonymity.txt` names not to match.
