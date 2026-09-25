# Frozen Test v3: gated baseline, three-seed GPU campaign, group-clustered intervals

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | rule_based | phi4_gated | phi4_no_gate | phi4_advisory | qwen25 | gpt55_gated | gpt55_no_gate |
|---|---:|---:|---:|---:|---:|---:|---:|
| Action accuracy | 55 (0.382) | 64 (0.444) | 67 (0.465) | 69 (0.479) | 54 (0.375) | 122 (0.847) | 130 (0.903) |
| EXECUTE correct | 34/44 | 22/44 | 29/44 | 29/44 | 27/44 | 35/44 | 43/44 |
| CLARIFY correct | 8/12 | 8/12 | 8/12 | 8/12 | 8/12 | 12/12 | 12/12 |
| REJECT correct | 0/16 | 10/16 | 10/16 | 10/16 | 8/16 | 5/16 | 5/16 |
| UNSUPPORTED correct | 13/72 | 24/72 | 20/72 | 22/72 | 11/72 | 70/72 | 70/72 |
| Task completion (gold-aware) | 55 (0.382) | 64 (0.444) | 67 (0.465) | 69 (0.479) | 54 (0.375) | 122 (0.847) | 130 (0.903) |
| Field exact match on EXECUTE | 0.351 | 0.549 | 0.685 | 0.685 | 0.646 | 0.799 | 0.951 |
| False acceptance | 74 (0.514) | 30 (0.208) | 33 (0.229) | 30 (0.208) | 54 (0.375) | 3 (0.021) | 2 (0.014) |
| Valid schedule on gold EXECUTE | 34/44 | 22/44 | 29/44 | 29/44 | 27/44 | 35/44 | 43/44 |
| Paraphrase-consistent groups | 70/72 | 45/72 | 46/72 | 46/72 | 61/72 | 67/72 | 69/72 |
| Semantic / schedule / infra failures | 89 / 0 / 0 | 80 / 0 / 0 | 77 / 0 / 0 | 75 / 0 / 0 | 90 / 0 / 0 | 22 / 0 / 0 | 14 / 0 / 0 |
| Retries / calls / tokens | 0 / 0 / 0 | 25 / 138 / 114853 | 25 / 156 / 129432 | 25 / 156 / 131279 | 25 / 138 / 119654 | 14 / 127 / 170363 | 14 / 145 / 191030 |
| Mean wall seconds | 0.02 | 1.41 | 1.58 | 1.58 | 1.61 | 3.74 | 3.97 |

## Paired action-accuracy differences, resampling by paraphrase_group

| Comparison | Mean difference | 95% CI | 95% CI by request | Pairs |
|---|---:|---|---|---:|
| phi4_gated minus rule_based | +0.0625 | [-0.0417, +0.1667] | [-0.0208, +0.1458] | 144 |
| phi4_no_gate minus rule_based | +0.0833 | [-0.0417, +0.2014] | [-0.0139, +0.1736] | 144 |
| phi4_advisory minus rule_based | +0.0972 | [-0.0208, +0.2153] | [+0.0000, +0.1875] | 144 |
| qwen25 minus rule_based | -0.0069 | [-0.0903, +0.0764] | [-0.0694, +0.0556] | 144 |
| gpt55_gated minus rule_based | +0.4653 | [+0.3472, +0.5833] | [+0.3819, +0.5486] | 144 |
| gpt55_no_gate minus rule_based | +0.5208 | [+0.4028, +0.6319] | [+0.4375, +0.6042] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| rule_based | 28/72 | 27/72 |
| phi4_gated | 30/72 | 34/72 |
| phi4_no_gate | 32/72 | 35/72 |
| phi4_advisory | 33/72 | 36/72 |
| qwen25 | 28/72 | 26/72 |
| gpt55_gated | 59/72 | 63/72 |
| gpt55_no_gate | 64/72 | 66/72 |
