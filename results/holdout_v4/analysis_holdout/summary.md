# Holdout v4: post-freeze batch, frontier arms and the rule baseline

Harness: `benchmarks/holdout_v4/harness/holdout_v4_harness.jsonl` (72 items)

| Metric | rule_based | gpt55_gated | gpt55_no_gate | gpt55_advisory |
|---|---:|---:|---:|---:|
| Action accuracy | 36 (0.500) | 52 (0.722) | 58 (0.801) | 58 (0.801) |
| EXECUTE correct | 16/24 | 12/24 | 19/24 | 19/24 |
| CLARIFY correct | 4/4 | 4/4 | 4/4 | 4/4 |
| REJECT correct | 0/8 | 1/8 | 1/8 | 1/8 |
| UNSUPPORTED correct | 16/36 | 35/36 | 34/36 | 34/36 |
| Task completion (gold-aware) | 36 (0.500) | 52 (0.722) | 58 (0.801) | 58 (0.801) |
| Field exact match on EXECUTE | 0.375 | 0.524 | 0.762 | 0.774 |
| False acceptance | 24 (0.333) | 4 (0.056) | 4 (0.056) | 4 (0.060) |
| Valid schedule on gold EXECUTE | 16/24 | 11/24 | 19/24 | 19/24 |
| Paraphrase-consistent groups | 32/36 | 30/36 | 30/36 | 32/36 |
| Semantic / schedule / infra failures | 36 / 0 / 0 | 21 / 0 / 0 | 14 / 0 / 0 | 14 / 0 / 0 |
| Retries / calls / tokens | 0 / 0 / 0 | 17 / 60 / 82891 | 18 / 80 / 109144 | 16 / 80 / 108340 |
| Mean wall seconds | 0.02 | 3.40 | 4.44 | 4.26 |

## Paired action-accuracy differences, resampling by paraphrase_group

| Comparison | Mean difference | 95% CI | 95% CI by request | Pairs |
|---|---:|---|---|---:|
| gpt55_gated minus rule_based | +0.2222 | [+0.0648, +0.3843] | [+0.0972, +0.3472] | 72 |
| gpt55_no_gate minus rule_based | +0.3009 | [+0.1204, +0.4815] | [+0.1620, +0.4398] | 72 |
| gpt55_advisory minus rule_based | +0.3009 | [+0.1204, +0.4815] | [+0.1620, +0.4398] | 72 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| rule_based | 17/36 | 19/36 |
| gpt55_gated | 24/36 | 27/36 |
| gpt55_no_gate | 27/36 | 31/36 |
| gpt55_advisory | 26/36 | 32/36 |
