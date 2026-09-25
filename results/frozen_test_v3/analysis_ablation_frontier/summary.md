# Scope gate ablation across model strength

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | gpt55_gated | gpt55_no_gate | phi4_gated | phi4_no_gate |
|---|---:|---:|---:|---:|
| Action accuracy | 119 (0.826) | 127 (0.882) | 62 (0.431) | 65 (0.451) |
| EXECUTE correct | 34/44 | 40/44 | 22/44 | 29/44 |
| CLARIFY correct | 8/12 | 8/12 | 8/12 | 8/12 |
| REJECT correct | 11/16 | 10/16 | 10/16 | 10/16 |
| UNSUPPORTED correct | 66/72 | 69/72 | 22/72 | 18/72 |
| Task completion (gold-aware) | 119 (0.826) | 127 (0.882) | 62 (0.431) | 65 (0.451) |
| Field exact match on EXECUTE | 0.776 | 0.896 | 0.549 | 0.685 |
| False acceptance | 4 (0.028) | 3 (0.021) | 30 (0.208) | 33 (0.229) |
| Valid schedule on gold EXECUTE | 34/44 | 40/44 | 22/44 | 29/44 |
| Paraphrase-consistent groups | 67/72 | 67/72 | 44/72 | 45/72 |
| Semantic / schedule / infra failures | 25 / 0 / 0 | 17 / 0 / 0 | 82 / 0 / 0 | 79 / 0 / 0 |
| Retries / calls / tokens | 43 / 156 / 194098 | 52 / 183 / 218673 | 25 / 138 / 114949 | 25 / 156 / 129463 |
| Mean wall seconds | 8.69 | 9.31 | 2.10 | 1.58 |

## Paired action-accuracy differences

| Comparison | Mean difference | 95% CI | Pairs |
|---|---:|---|---:|
| gpt55_no_gate minus gpt55_gated | +0.0556 | [+0.0069, +0.1042] | 144 |
| phi4_gated minus gpt55_gated | -0.3958 | [-0.4792, -0.3125] | 144 |
| phi4_no_gate minus gpt55_gated | -0.3750 | [-0.4722, -0.2778] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| gpt55_gated | 54/72 | 65/72 |
| gpt55_no_gate | 61/72 | 66/72 |
| phi4_gated | 30/72 | 32/72 |
| phi4_no_gate | 32/72 | 33/72 |
