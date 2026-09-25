# Phi4 advisory against the ungated arm

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | phi4_no_gate | phi4_advisory |
|---|---:|---:|
| Action accuracy | 67 (0.465) | 69 (0.479) |
| EXECUTE correct | 29/44 | 29/44 |
| CLARIFY correct | 8/12 | 8/12 |
| REJECT correct | 10/16 | 10/16 |
| UNSUPPORTED correct | 20/72 | 22/72 |
| Task completion (gold-aware) | 67 (0.465) | 69 (0.479) |
| Field exact match on EXECUTE | 0.685 | 0.685 |
| False acceptance | 33 (0.229) | 30 (0.208) |
| Valid schedule on gold EXECUTE | 29/44 | 29/44 |
| Paraphrase-consistent groups | 46/72 | 46/72 |
| Semantic / schedule / infra failures | 77 / 0 / 0 | 75 / 0 / 0 |
| Retries / calls / tokens | 25 / 156 / 129432 | 25 / 156 / 131279 |
| Mean wall seconds | 1.58 | 1.58 |

## Paired action-accuracy differences, resampling by paraphrase_group

| Comparison | Mean difference | 95% CI | 95% CI by request | Pairs |
|---|---:|---|---|---:|
| phi4_advisory minus phi4_no_gate | +0.0139 | [+0.0000, +0.0347] | [+0.0000, +0.0347] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| phi4_no_gate | 32/72 | 35/72 |
| phi4_advisory | 33/72 | 36/72 |
