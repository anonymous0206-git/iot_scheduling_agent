# GPT ablation final

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | gpt55_gated | gpt55_no_gate |
|---|---:|---:|
| Action accuracy | 122 (0.847) | 130 (0.903) |
| EXECUTE correct | 35/44 | 43/44 |
| CLARIFY correct | 12/12 | 12/12 |
| REJECT correct | 5/16 | 5/16 |
| UNSUPPORTED correct | 70/72 | 70/72 |
| Task completion (gold-aware) | 122 (0.847) | 130 (0.903) |
| Field exact match on EXECUTE | 0.799 | 0.951 |
| False acceptance | 3 (0.021) | 2 (0.014) |
| Valid schedule on gold EXECUTE | 35/44 | 43/44 |
| Paraphrase-consistent groups | 67/72 | 69/72 |
| Semantic / schedule / infra failures | 22 / 0 / 0 | 14 / 0 / 0 |
| Retries / calls / tokens | 14 / 127 / 170363 | 14 / 145 / 191030 |
| Mean wall seconds | 3.74 | 3.97 |

## Paired action-accuracy differences

| Comparison | Mean difference | 95% CI | Pairs |
|---|---:|---|---:|
| gpt55_no_gate minus gpt55_gated | +0.0556 | [+0.0139, +0.0972] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| gpt55_gated | 59/72 | 63/72 |
| gpt55_no_gate | 64/72 | 66/72 |
