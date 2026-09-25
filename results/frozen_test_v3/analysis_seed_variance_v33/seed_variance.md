# Frozen Test v3 run-to-run variance, three-seed GPU campaign

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

Each column is one arm run several times under identical settings. At
temperature 0 the repeats differ only through provider nondeterminism, so the
spread below is a floor on run-to-run noise, not sampling diversity.

| Metric | phi4_policy_v2 | phi4_no_scope_gate | phi4_advisory | qwen25 |
|---|---:|---:|---:|---:|
| repeat 1 | 64/144 (0.444) s11 | 67/144 (0.465) s11 | 69/144 (0.479) s11 | 54/144 (0.375) s11 |
| repeat 2 | 64/144 (0.444) s12 | 67/144 (0.465) s12 | 69/144 (0.479) s12 | 54/144 (0.375) s12 |
| repeat 3 | 64/144 (0.444) s13 | 67/144 (0.465) s13 | 69/144 (0.479) s13 | 54/144 (0.375) s13 |
| **mean accuracy** | 0.4444 | 0.4653 | 0.4792 | 0.3750 |
| range (max - min) | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| stdev | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| majority-vote accuracy | 0.4444 | 0.4653 | 0.4792 | 0.3750 |
| stable items | 144/144 (1.000) | 144/144 (1.000) | 144/144 (1.000) | 144/144 (1.000) |

## Differences against the noise floor

A gap no larger than the widest within-arm range is not distinguishable from noise at this number of repeats.

| Comparison | Mean difference | Widest within-arm range | Verdict |
|---|---:|---:|---|
| phi4_no_scope_gate minus phi4_policy_v2 | +0.0209 | 0.0000 | exceeds the noise floor |
| phi4_advisory minus phi4_policy_v2 | +0.0348 | 0.0000 | exceeds the noise floor |
| qwen25 minus phi4_policy_v2 | -0.0694 | 0.0000 | exceeds the noise floor |
| phi4_advisory minus phi4_no_scope_gate | +0.0139 | 0.0000 | exceeds the noise floor |
| qwen25 minus phi4_no_scope_gate | -0.0903 | 0.0000 | exceeds the noise floor |
| qwen25 minus phi4_advisory | -0.1042 | 0.0000 | exceeds the noise floor |
