# Holdout v4: protocol, fixed before any request exists

Written 2026-09-27, before a single item of the holdout batch has been
authored. Everything here is a commitment: what will be run, what will be
counted, what will be reported, and what each outcome will be taken to mean.
Anything decided after seeing an output is not part of this document and will
be labelled as such in the paper.

## 1. Why the batch exists

The sealed benchmark `frozen_test_v3` was reused: the pipeline was repaired
after failures on it were seen, so nothing in it is held out. Section 4.4 of
the paper discloses this and the conclusion calls the work a controlled case
study. This batch is the smallest experiment that tests whether the paper's
mechanism survives contact with intents the system has never been exposed to.

## 2. What is frozen, and when

`benchmarks/evaluation_lock_v4_holdout.json`, issued 2026-09-27, records the
SHA-256 of the 98 files the evaluation depends on. Verified after issue: all 98
match. No file covered by that lock may change between now and the end of this
experiment. If one has to, the experiment restarts with a new lock and this
document is superseded rather than edited.

The lock also records a gap it uncovered: the pipeline repair of 2026-09-21
preceded the campaign of 2026-09-21 and 2026-09-22, and no earlier lock covered
those bytes. This lock is the first manifest of the repaired pipeline.

## 3. Authoring and adjudication

Two authors write 18 semantic groups each, giving 36 groups and 72 requests.
The prompts are `docs/prompts/holdout_v4/holdout_v4_generator_{A,B}.txt`,
rendered mechanically from the released Frozen Test v3 generator prompt by
`scripts/render_holdout_prompts.py`, which lists every substitution it makes.
Only the batch size, the quotas, the compositional floor and the identifier
prefix differ from the prompt that produced the sealed benchmark.

Independence rules, all of which bind:

* each author is a session of a frontier model that has not seen this
  repository, its failure taxonomy, its ledgers, or any previous benchmark of
  this project, and receives nothing but its rendered prompt;
* the two authors are different model families;
* the adjudicator of a batch is the model that did not write it, and receives
  the blind copy plus `holdout_v4_reviewer_batch_{A,B}.txt`;
* no session involved in editing this system --- which includes the assistant
  that wrote this document --- authors or adjudicates any item. An item written
  by a session that has read the scope policy would reproduce, at maximum
  strength, the exposure the paper already discloses for Batch B.

Flagged groups go to the human operator, whose per-group rationale is recorded
before sealing, as in the earlier round.

## 4. Size, and what it buys

From `results/frozen_test_v3/holdout_sizing/`, the per-group standard deviation
of the paired difference in action accuracy is 0.22 to 0.26 depending on the
contrast. At 36 groups:

| question | what 36 groups give |
| --- | --- |
| frontier ablation, effect +0.0671 | power 0.44 --- a coin flip, and not what this batch is for |
| 14B ablation, effect +0.0208 | power 0.07 --- out of reach at any feasible size (1202 groups) |
| gate recall on requests that name the capability | a count, not an estimate |
| gate recall on requests that compose it | a count; 0 of 18 would bound the rate at 0.17 (95%) |
| matched-item attribution | a count: which items the gate decides, and what each arm does with them |

The batch is therefore sized and aimed at the mechanism, which is counted, not
at the interval, which is estimated. We will report the interval anyway,
because suppressing it because it is wide is how an interval becomes a claim.

## 5. What will be run

The three enforcing arms and the two ablations of the frontier and 14B agents,
three repeats each, under the locked pipeline: `rule_based`, `phi4` and
`qwen2.5` enforcing, `phi4` and `gpt-5.5` with the gate off and advisory. Local
arms decode greedily at temperature 0; the frontier arm samples at temperature
1 because the provider accepts nothing else, exactly as in the paper.

Analysis is `scripts/analyze_frozen_test_results.py` with the same bootstrap
parameters, 10,000 resamples over paraphrase groups, seed 0, and
`scripts/sensitivity_gold_labels.py` if the adjudication leaves contested
labels.

## 6. What counts as replication, decided now

* **Mechanism replicates** if, on the holdout's unsupported requests, the scope
  gate's recall on requests that name the capability exceeds its recall on
  requests that compose it without naming it, and the ungated frontier agent's
  recall on the composed requests exceeds the gate's. Direction, not
  magnitude: the effect is a property of a regex against phrasing, and the
  holdout has too few items to pin a rate.
* **Over-blocking replicates** if the gate short-circuits at least one
  gold-`EXECUTE` request and the ungated arm answers it correctly.
* **The ablation is consistent** if the paired difference's point estimate is
  positive. Its interval will probably contain zero at this size; that is
  expected and is not evidence against the effect.
* **A negative result** is any of the above failing, and will be reported in
  the paper beside the frozen-test-v3 numbers, in the same table, with the same
  prominence. There will be no second holdout batch to replace a first one we
  did not like. If we later run a larger batch, this one is still reported.

## 7. Reporting

The holdout is reported next to `frozen_test_v3`, never in place of it, and the
paper will say plainly that the original benchmark remains the source of every
number that predates this document. The batch, its prompts, its adjudications,
its human decisions, its lock and its ledgers ship in the artefact under
`holdout_v4/`.

## 8. What this does not fix

A single 36-group batch does not make the paper's ablation generalisable, and
this document does not claim it will. It tests whether the mechanism holds on
intents the system has not seen. The limitation the reviews keep naming --- no
post-freeze batch large enough to confirm the effect --- is narrowed by this
experiment, not closed by it.
