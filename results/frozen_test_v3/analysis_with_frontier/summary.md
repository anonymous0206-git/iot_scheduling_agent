# Frozen Test v3 campaign with frontier arm

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | rule_based | phi4_gated | phi4_no_gate | qwen25 | gpt55 |
|---|---:|---:|---:|---:|---:|
| Action accuracy | 54 (0.375) | 62 (0.431) | 65 (0.451) | 55 (0.382) | 119 (0.826) |
| EXECUTE correct | 36/44 | 22/44 | 29/44 | 28/44 | 34/44 |
| CLARIFY correct | 8/12 | 8/12 | 8/12 | 8/12 | 8/12 |
| REJECT correct | 0/16 | 10/16 | 10/16 | 8/16 | 11/16 |
| UNSUPPORTED correct | 10/72 | 22/72 | 18/72 | 11/72 | 66/72 |
| Task completion (gold-aware) | 54 (0.375) | 62 (0.431) | 65 (0.451) | 55 (0.382) | 119 (0.826) |
| Field exact match on EXECUTE | 0.477 | 0.549 | 0.685 | 0.666 | 0.776 |
| False acceptance | 77 (0.535) | 30 (0.208) | 33 (0.229) | 54 (0.375) | 4 (0.028) |
| Valid schedule on gold EXECUTE | 36/44 | 22/44 | 29/44 | 28/44 | 34/44 |
| Paraphrase-consistent groups | 71/72 | 44/72 | 45/72 | 60/72 | 67/72 |
| Semantic / schedule / infra failures | 90 / 0 / 0 | 82 / 0 / 0 | 79 / 0 / 0 | 89 / 0 / 0 | 25 / 0 / 0 |
| Retries / calls / tokens | 0 / 0 / 0 | 25 / 138 / 114949 | 25 / 156 / 129463 | 25 / 138 / 119634 | 43 / 156 / 194098 |
| Mean wall seconds | 0.02 | 2.10 | 1.58 | 2.24 | 8.69 |

## Paired action-accuracy differences

| Comparison | Mean difference | 95% CI | Pairs |
|---|---:|---|---:|
| phi4_gated minus rule_based | +0.0556 | [-0.0347, +0.1389] | 144 |
| phi4_no_gate minus rule_based | +0.0764 | [-0.0139, +0.1597] | 144 |
| qwen25 minus rule_based | +0.0069 | [-0.0625, +0.0764] | 144 |
| gpt55 minus rule_based | +0.4514 | [+0.3611, +0.5417] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| rule_based | 28/72 | 26/72 |
| phi4_gated | 30/72 | 32/72 |
| phi4_no_gate | 32/72 | 33/72 |
| qwen25 | 28/72 | 27/72 |
| gpt55 | 54/72 | 65/72 |
