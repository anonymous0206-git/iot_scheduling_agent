# Frozen Test v3 run-to-run variance

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

Each column is one arm run several times under identical settings. At
temperature 0 the repeats differ only through provider nondeterminism, so the
spread below is a floor on run-to-run noise, not sampling diversity.

| Metric | phi4_policy_v2 | phi4_no_scope_gate | qwen25_policy_v2 |
|---|---:|---:|---:|
| repeat 1 | 64/144 (0.444) s0 | 65/144 (0.451) s0 | 55/144 (0.382) s0 |
| repeat 2 | 62/144 (0.431) s1 | 65/144 (0.451) s1 | 55/144 (0.382) s1 |
| repeat 3 | 62/144 (0.431) s2 | 65/144 (0.451) s2 | 55/144 (0.382) s2 |
| **mean accuracy** | 0.4352 | 0.4514 | 0.3819 |
| range (max - min) | +0.0138 | +0.0000 | +0.0000 |
| stdev | 0.0080 | 0.0000 | 0.0000 |
| majority-vote accuracy | 0.4306 | 0.4514 | 0.3819 |
| stable items | 142/144 (0.986) | 144/144 (1.000) | 140/144 (0.972) |

## Differences against the noise floor

A gap no larger than the widest within-arm range is not distinguishable from noise at this number of repeats.

| Comparison | Mean difference | Widest within-arm range | Verdict |
|---|---:|---:|---|
| phi4_no_scope_gate minus phi4_policy_v2 | +0.0162 | 0.0138 | exceeds the noise floor |
| qwen25_policy_v2 minus phi4_policy_v2 | -0.0533 | 0.0138 | exceeds the noise floor |
| qwen25_policy_v2 minus phi4_no_scope_gate | -0.0695 | 0.0000 | exceeds the noise floor |

## Unstable items

Items whose action changed between repeats of the same arm.

### phi4_policy_v2

| Request | Gold | Actions across repeats |
|---|---|---|
| `ft3-r0036` | UNSUPPORTED | UNSUPPORTED → REJECT → REJECT |
| `ft3-r0127` | UNSUPPORTED | UNSUPPORTED → REJECT → REJECT |

### qwen25_policy_v2

| Request | Gold | Actions across repeats |
|---|---|---|
| `ft3-r0001` | UNSUPPORTED | REJECT → EXECUTE → EXECUTE |
| `ft3-r0003` | UNSUPPORTED | REJECT → EXECUTE → EXECUTE |
| `ft3-r0090` | EXECUTE | EXECUTE → REJECT → REJECT |
| `ft3-r0138` | EXECUTE | REJECT → EXECUTE → EXECUTE |
