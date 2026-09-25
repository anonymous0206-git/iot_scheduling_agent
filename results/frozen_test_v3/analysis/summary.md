# Frozen Test v3 campaign

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | rule_based | phi4 | qwen25 |
|---|---:|---:|---:|
| Action accuracy | 54 (0.375) | 64 (0.444) | 55 (0.382) |
| EXECUTE correct | 36/44 | 22/44 | 28/44 |
| CLARIFY correct | 8/12 | 8/12 | 8/12 |
| REJECT correct | 0/16 | 10/16 | 8/16 |
| UNSUPPORTED correct | 10/72 | 24/72 | 11/72 |
| Task completion (gold-aware) | 54 (0.375) | 64 (0.444) | 55 (0.382) |
| Field exact match on EXECUTE | 0.477 | 0.549 | 0.666 |
| False acceptance | 77 (0.535) | 30 (0.208) | 52 (0.361) |
| Valid schedule on gold EXECUTE | 36/44 | 22/44 | 28/44 |
| Paraphrase-consistent groups | 71/72 | 45/72 | 60/72 |
| Semantic / schedule / infra failures | 90 / 0 / 0 | 80 / 0 / 0 | 87 / 0 / 2 |
| Retries / calls / tokens | 0 / 0 / 0 | 25 / 138 / 114853 | 31 / 144 / 117877 |
| Mean wall seconds | 0.02 | 1.44 | 8.52 |

## Paired action-accuracy differences

| Comparison | Mean difference | 95% CI | Pairs |
|---|---:|---|---:|
| phi4 minus rule_based | +0.0694 | [-0.0208, +0.1597] | 144 |
| qwen25 minus rule_based | +0.0069 | [-0.0625, +0.0764] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| rule_based | 28/72 | 26/72 |
| phi4 | 30/72 | 34/72 |
| qwen25 | 29/72 | 26/72 |
