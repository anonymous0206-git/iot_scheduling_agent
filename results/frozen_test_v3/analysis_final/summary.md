# Frozen Test v3 under the repaired pipeline

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | rule_based | phi4_gated | phi4_no_gate | qwen25 | gpt55_gated | gpt55_no_gate |
|---|---:|---:|---:|---:|---:|---:|
| Action accuracy | 54 (0.375) | 64 (0.444) | 67 (0.465) | 55 (0.382) | 122 (0.847) | 130 (0.903) |
| EXECUTE correct | 36/44 | 22/44 | 29/44 | 28/44 | 35/44 | 43/44 |
| CLARIFY correct | 8/12 | 8/12 | 8/12 | 8/12 | 12/12 | 12/12 |
| REJECT correct | 0/16 | 10/16 | 10/16 | 8/16 | 5/16 | 5/16 |
| UNSUPPORTED correct | 10/72 | 24/72 | 20/72 | 11/72 | 70/72 | 70/72 |
| Task completion (gold-aware) | 54 (0.375) | 64 (0.444) | 67 (0.465) | 55 (0.382) | 122 (0.847) | 130 (0.903) |
| Field exact match on EXECUTE | 0.380 | 0.549 | 0.685 | 0.666 | 0.799 | 0.951 |
| False acceptance | 77 (0.535) | 30 (0.208) | 33 (0.229) | 54 (0.375) | 3 (0.021) | 2 (0.014) |
| Valid schedule on gold EXECUTE | 36/44 | 22/44 | 29/44 | 28/44 | 35/44 | 43/44 |
| Paraphrase-consistent groups | 71/72 | 45/72 | 46/72 | 60/72 | 67/72 | 69/72 |
| Semantic / schedule / infra failures | 90 / 0 / 0 | 80 / 0 / 0 | 77 / 0 / 0 | 89 / 0 / 0 | 22 / 0 / 0 | 14 / 0 / 0 |
| Retries / calls / tokens | 0 / 0 / 0 | 25 / 138 / 114853 | 25 / 156 / 129432 | 25 / 138 / 119634 | 14 / 127 / 170363 | 14 / 145 / 191030 |
| Mean wall seconds | 0.02 | 1.41 | 1.60 | 2.17 | 3.74 | 3.97 |

## Paired action-accuracy differences

| Comparison | Mean difference | 95% CI | Pairs |
|---|---:|---|---:|
| phi4_gated minus rule_based | +0.0694 | [-0.0208, +0.1597] | 144 |
| phi4_no_gate minus rule_based | +0.0903 | [+0.0000, +0.1806] | 144 |
| qwen25 minus rule_based | +0.0069 | [-0.0625, +0.0764] | 144 |
| gpt55_gated minus rule_based | +0.4722 | [+0.3819, +0.5625] | 144 |
| gpt55_no_gate minus rule_based | +0.5278 | [+0.4444, +0.6111] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| rule_based | 28/72 | 26/72 |
| phi4_gated | 30/72 | 34/72 |
| phi4_no_gate | 32/72 | 35/72 |
| qwen25 | 28/72 | 27/72 |
| gpt55_gated | 59/72 | 63/72 |
| gpt55_no_gate | 64/72 | 66/72 |
