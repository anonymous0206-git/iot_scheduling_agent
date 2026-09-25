# Phi4 ablation final

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | phi4_gated | phi4_no_gate |
|---|---:|---:|
| Action accuracy | 64 (0.444) | 67 (0.465) |
| EXECUTE correct | 22/44 | 29/44 |
| CLARIFY correct | 8/12 | 8/12 |
| REJECT correct | 10/16 | 10/16 |
| UNSUPPORTED correct | 24/72 | 20/72 |
| Task completion (gold-aware) | 64 (0.444) | 67 (0.465) |
| Field exact match on EXECUTE | 0.549 | 0.685 |
| False acceptance | 30 (0.208) | 33 (0.229) |
| Valid schedule on gold EXECUTE | 22/44 | 29/44 |
| Paraphrase-consistent groups | 45/72 | 46/72 |
| Semantic / schedule / infra failures | 80 / 0 / 0 | 77 / 0 / 0 |
| Retries / calls / tokens | 25 / 138 / 114853 | 25 / 156 / 129432 |
| Mean wall seconds | 1.41 | 1.60 |

## Paired action-accuracy differences

| Comparison | Mean difference | 95% CI | Pairs |
|---|---:|---|---:|
| phi4_no_gate minus phi4_gated | +0.0208 | [-0.0208, +0.0694] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| phi4_gated | 30/72 | 34/72 |
| phi4_no_gate | 32/72 | 35/72 |
