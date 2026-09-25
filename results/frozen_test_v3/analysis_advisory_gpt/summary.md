# GPT advisory against the enforcing arm

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | gpt55_gated | gpt55_advisory | gpt55_no_gate |
|---|---:|---:|---:|
| Action accuracy | 122 (0.845) | 129 (0.896) | 131 (0.912) |
| EXECUTE correct | 35/44 | 43/44 | 43/44 |
| CLARIFY correct | 12/12 | 12/12 | 12/12 |
| REJECT correct | 5/16 | 4/16 | 6/16 |
| UNSUPPORTED correct | 70/72 | 70/72 | 71/72 |
| Task completion (gold-aware) | 122 (0.845) | 129 (0.896) | 131 (0.912) |
| Field exact match on EXECUTE | 0.792 | 0.952 | 0.946 |
| False acceptance | 3 (0.023) | 4 (0.025) | 2 (0.014) |
| Valid schedule on gold EXECUTE | 35/44 | 43/44 | 42/44 |
| Paraphrase-consistent groups | 68/72 | 70/72 | 69/72 |
| Semantic / schedule / infra failures | 22 / 0 / 0 | 15 / 0 / 0 | 14 / 0 / 0 |
| Retries / calls / tokens | 13 / 128 / 167167 | 15 / 145 / 194112 | 15 / 145 / 192965 |
| Mean wall seconds | 3.76 | 3.76 | 4.01 |

## Paired action-accuracy differences, resampling by paraphrase_group

| Comparison | Mean difference | 95% CI | 95% CI by request | Pairs |
|---|---:|---|---|---:|
| gpt55_advisory minus gpt55_gated | +0.0509 | [+0.0046, +0.1065] | [+0.0139, +0.0903] | 144 |
| gpt55_no_gate minus gpt55_gated | +0.0671 | [+0.0208, +0.1227] | [+0.0301, +0.1088] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| gpt55_gated | 60/72 | 62/72 |
| gpt55_advisory | 63/72 | 66/72 |
| gpt55_no_gate | 64/72 | 66/72 |
