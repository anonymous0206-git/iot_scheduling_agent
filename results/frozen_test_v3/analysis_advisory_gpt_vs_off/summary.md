# GPT advisory against the ungated arm

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | gpt55_no_gate | gpt55_advisory |
|---|---:|---:|
| Action accuracy | 131 (0.912) | 129 (0.896) |
| EXECUTE correct | 43/44 | 43/44 |
| CLARIFY correct | 12/12 | 12/12 |
| REJECT correct | 6/16 | 4/16 |
| UNSUPPORTED correct | 71/72 | 70/72 |
| Task completion (gold-aware) | 131 (0.912) | 129 (0.896) |
| Field exact match on EXECUTE | 0.946 | 0.952 |
| False acceptance | 2 (0.014) | 4 (0.025) |
| Valid schedule on gold EXECUTE | 42/44 | 43/44 |
| Paraphrase-consistent groups | 69/72 | 70/72 |
| Semantic / schedule / infra failures | 14 / 0 / 0 | 15 / 0 / 0 |
| Retries / calls / tokens | 15 / 145 / 192965 | 15 / 145 / 194112 |
| Mean wall seconds | 4.01 | 3.76 |

## Paired action-accuracy differences, resampling by paraphrase_group

| Comparison | Mean difference | 95% CI | 95% CI by request | Pairs |
|---|---:|---|---|---:|
| gpt55_advisory minus gpt55_no_gate | -0.0162 | [-0.0463, +0.0046] | [-0.0394, +0.0023] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| gpt55_no_gate | 64/72 | 66/72 |
| gpt55_advisory | 63/72 | 66/72 |
