# Frozen Test v3 campaign under the repaired pipeline (lock v3.1)

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | rule_based | phi4_gated | phi4_no_gate | qwen25 | gpt55_gated | gpt55_no_gate |
|---|---:|---:|---:|---:|---:|---:|
| Action accuracy | 54 (0.375) | 61 (0.424) | 64 (0.444) | 55 (0.382) | 122 (0.847) | 130 (0.903) |
| EXECUTE correct | 36/44 | 21/44 | 28/44 | 28/44 | 35/44 | 43/44 |
| CLARIFY correct | 8/12 | 8/12 | 8/12 | 8/12 | 12/12 | 12/12 |
| REJECT correct | 0/16 | 10/16 | 10/16 | 8/16 | 5/16 | 5/16 |
| UNSUPPORTED correct | 10/72 | 22/72 | 18/72 | 11/72 | 70/72 | 70/72 |
| Task completion (gold-aware) | 54 (0.375) | 61 (0.424) | 64 (0.444) | 55 (0.382) | 122 (0.847) | 130 (0.903) |
| Field exact match on EXECUTE | 0.380 | 0.529 | 0.666 | 0.666 | 0.799 | 0.951 |
| False acceptance | 77 (0.535) | 29 (0.201) | 32 (0.222) | 54 (0.375) | 3 (0.021) | 2 (0.014) |
| Valid schedule on gold EXECUTE | 36/44 | 21/44 | 28/44 | 28/44 | 35/44 | 43/44 |
| Paraphrase-consistent groups | 71/72 | 45/72 | 46/72 | 62/72 | 67/72 | 69/72 |
| Semantic / schedule / infra failures | 90 / 0 / 0 | 83 / 0 / 0 | 80 / 0 / 0 | 89 / 0 / 0 | 22 / 0 / 0 | 14 / 0 / 0 |
| Retries / calls / tokens | 0 / 0 / 0 | 27 / 140 / 116478 | 27 / 158 / 130994 | 23 / 136 / 117834 | 14 / 127 / 170363 | 14 / 145 / 191030 |
| Mean wall seconds | 0.02 | 24.17 | 25.68 | 28.07 | 3.74 | 3.97 |

## Paired action-accuracy differences

| Comparison | Mean difference | 95% CI | Pairs |
|---|---:|---|---:|
| phi4_gated minus rule_based | +0.0486 | [-0.0417, +0.1389] | 144 |
| phi4_no_gate minus rule_based | +0.0694 | [-0.0208, +0.1597] | 144 |
| qwen25 minus rule_based | +0.0069 | [-0.0625, +0.0764] | 144 |
| gpt55_gated minus rule_based | +0.4722 | [+0.3819, +0.5625] | 144 |
| gpt55_no_gate minus rule_based | +0.5278 | [+0.4444, +0.6111] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| rule_based | 28/72 | 26/72 |
| phi4_gated | 30/72 | 31/72 |
| phi4_no_gate | 32/72 | 32/72 |
| qwen25 | 29/72 | 26/72 |
| gpt55_gated | 59/72 | 63/72 |
| gpt55_no_gate | 64/72 | 66/72 |
