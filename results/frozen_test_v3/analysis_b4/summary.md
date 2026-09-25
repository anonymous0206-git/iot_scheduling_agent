# B4 retry ablation

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | gpt55 | gpt55_noretry | phi4 | phi4_noretry |
|---|---:|---:|---:|---:|
| Action accuracy | 122 (0.847) | 115 (0.799) | 64 (0.444) | 62 (0.431) |
| EXECUTE correct | 35/44 | 28/44 | 22/44 | 22/44 |
| CLARIFY correct | 12/12 | 12/12 | 8/12 | 8/12 |
| REJECT correct | 5/16 | 6/16 | 10/16 | 10/16 |
| UNSUPPORTED correct | 70/72 | 69/72 | 24/72 | 22/72 |
| Task completion (gold-aware) | 122 (0.847) | 115 (0.799) | 64 (0.444) | 62 (0.431) |
| Field exact match on EXECUTE | 0.799 | 0.666 | 0.549 | 0.549 |
| False acceptance | 3 (0.021) | 2 (0.014) | 30 (0.208) | 30 (0.208) |
| Valid schedule on gold EXECUTE | 35/44 | 28/44 | 22/44 | 22/44 |
| Paraphrase-consistent groups | 67/72 | 65/72 | 45/72 | 44/72 |
| Semantic / schedule / infra failures | 22 / 0 / 0 | 29 / 0 / 0 | 80 / 0 / 0 | 82 / 0 / 0 |
| Retries / calls / tokens | 14 / 127 / 170363 | 0 / 113 / 145111 | 25 / 138 / 114853 | 0 / 113 / 92451 |
| Mean wall seconds | 3.74 | 4.19 | 1.41 | 2.41 |

## Paired action-accuracy differences

| Comparison | Mean difference | 95% CI | Pairs |
|---|---:|---|---:|
| gpt55_noretry minus gpt55 | -0.0486 | [-0.0972, -0.0069] | 144 |
| phi4 minus gpt55 | -0.4028 | [-0.4931, -0.3125] | 144 |
| phi4_noretry minus gpt55 | -0.4167 | [-0.5069, -0.3264] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| gpt55 | 59/72 | 63/72 |
| gpt55_noretry | 55/72 | 60/72 |
| phi4 | 30/72 | 34/72 |
| phi4_noretry | 30/72 | 32/72 |
