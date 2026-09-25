# Phi-4 Reasoning Exploratory Failure Case

This analysis is classified as: **Exploratory reasoning-model comparison
conducted after Frozen Test v1 was opened, with no prompt or policy
modification.** The immutable evidence manifest is
`results/phi4_reasoning_exploratory_v1_lock.json`.

## Observed semantic laundering

For `test-dt-02`, the raw request asks to stream sensor telemetry into a
persistent virtual network replica and control physical nodes from it. Those
capabilities imply a stateful virtual representation and a bidirectional
cyber-physical control loop, both outside Paper 1.

The model decision summary instead states that the request is a one-shot
minimum-latency workload. Its structured request contains only supported ANEX
fields (`one_shot`, `minimize_latency`, two channels, legacy-neighbor collision
checking, alpha 1.0, and seed 0). No public SchedulingRequest field retains the
virtual-replica, streaming, persistence, or physical-control intent.

Policy v1 did inspect raw text before the LLM, but used a finite flat phrase
list derived during development. It recognized adjacent phrases such as
"virtual replica" but not a compositional form with an intervening network
modifier. The later consistency checker compared explicit scheduling
parameters and documented defaults; it did not independently classify raw
capabilities. Thus the internally consistent, semantically laundered request
passed that boundary.

The model approved `inspect_network`, `run_anex`, `validate_schedule`, and
`measure_schedule`. All four ran successfully. The final report treated a
passing independent schedule certificate as sufficient for success after the
earlier semantic failure had been missed. The validator correctly established
that the computed 29-transmission schedule was valid under `legacy_neighbor`;
it did not and should not certify that a Digital Twin request belongs to Paper
1. Schedule validity therefore could not establish semantic validity.

## Root cause

The pipeline behaved as follows:

```text
unsupported raw capability
  -> incomplete flat phrase gate
  -> LLM drops unsupported semantics
  -> supported-looking SchedulingRequest
  -> field consistency passes
  -> ANEX and schedule validator pass
  -> false EXECUTE
```

This is a confirmed false acceptance, not a schedule-validator defect. The
complete raw response, prompt, tool approvals, tool trace, validation report,
token counts, and timing metadata are preserved in
`results/phi4_reasoning_test_dt02_trace_v1.json`. The validation report's
deterministic certificate is separately locked as
`results/phi4_reasoning_test_dt02_validation_certificate_v1.json`; the raw
ledger was not modified to create it.

## Policy consequence

Policy v2 introduces an independent, taxonomy-based scope gate over the raw
request before LLM interpretation. Its invariant is that an unsupported raw
capability permanently prevents `EXECUTE`; neither omission by the LLM nor a
valid ANEX schedule may override it. Regression on Frozen Test v1 may confirm
the known failure is blocked, but is not reported as unbiased test
performance. Policy v2 requires a separately authored and frozen Test v2 for
new performance claims.

The no-execution counterfactual comparison is stored in
`results/retrospective_policy_ablation_v1.json`. Across the 24 locked records,
v2 changes one final action relative to v1: the reasoning-model `test-dt-02`
false acceptance becomes `UNSUPPORTED` before any model or tool call. It does
not over-block any gold-supported v1 item. These figures are regression
evidence only.
