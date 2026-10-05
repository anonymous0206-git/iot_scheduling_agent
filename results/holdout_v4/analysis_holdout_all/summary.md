# Holdout v4: every arm, frontier and 14B, against the rule baseline

Harness: `benchmarks/holdout_v4/harness/holdout_v4_harness.jsonl` (72 items)

| Metric | rule_based | phi4_gated | phi4_no_gate | phi4_advisory | qwen25_gated | gpt55_gated | gpt55_no_gate | gpt55_advisory |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Action accuracy | 36 (0.500) | 29 (0.403) | 26 (0.361) | 30 (0.417) | 29 (0.403) | 52 (0.722) | 58 (0.801) | 58 (0.801) |
| EXECUTE correct | 16/24 | 8/24 | 14/24 | 15/24 | 10/24 | 12/24 | 19/24 | 19/24 |
| CLARIFY correct | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 |
| REJECT correct | 0/8 | 1/8 | 1/8 | 1/8 | 1/8 | 1/8 | 1/8 | 1/8 |
| UNSUPPORTED correct | 16/36 | 16/36 | 7/36 | 10/36 | 14/36 | 35/36 | 34/36 | 34/36 |
| Task completion (gold-aware) | 36 (0.500) | 29 (0.403) | 26 (0.361) | 30 (0.417) | 29 (0.403) | 52 (0.722) | 58 (0.801) | 58 (0.801) |
| Field exact match on EXECUTE | 0.375 | 0.381 | 0.595 | 0.631 | 0.452 | 0.524 | 0.762 | 0.774 |
| False acceptance | 24 (0.333) | 15 (0.208) | 17 (0.236) | 15 (0.208) | 21 (0.292) | 4 (0.056) | 4 (0.056) | 4 (0.060) |
| Valid schedule on gold EXECUTE | 16/24 | 8/24 | 14/24 | 15/24 | 10/24 | 11/24 | 19/24 | 19/24 |
| Paraphrase-consistent groups | 32/36 | 21/36 | 23/36 | 23/36 | 22/36 | 30/36 | 30/36 | 32/36 |
| Semantic / schedule / infra failures | 36 / 0 / 0 | 43 / 0 / 0 | 46 / 0 / 0 | 42 / 0 / 0 | 43 / 0 / 0 | 21 / 0 / 0 | 14 / 0 / 0 | 14 / 0 / 0 |
| Retries / calls / tokens | 0 / 0 / 0 | 15 / 58 / 50012 | 15 / 78 / 66191 | 16 / 79 / 69405 | 14 / 57 / 50513 | 17 / 60 / 82891 | 18 / 80 / 109144 | 16 / 80 / 108340 |
| Mean wall seconds | 0.02 | 1.49 | 1.77 | 1.85 | 1.56 | 3.40 | 4.44 | 4.26 |

## Paired action-accuracy differences, resampling by paraphrase_group

| Comparison | Mean difference | 95% CI | 95% CI by request | Pairs |
|---|---:|---|---|---:|
| phi4_gated minus rule_based | -0.0972 | [-0.2222, +0.0139] | [-0.1944, +0.0000] | 72 |
| phi4_no_gate minus rule_based | -0.1389 | [-0.3056, +0.0278] | [-0.2778, +0.0000] | 72 |
| phi4_advisory minus rule_based | -0.0833 | [-0.2500, +0.0833] | [-0.2222, +0.0556] | 72 |
| qwen25_gated minus rule_based | -0.0972 | [-0.2083, +0.0000] | [-0.1944, -0.0139] | 72 |
| gpt55_gated minus rule_based | +0.2222 | [+0.0648, +0.3843] | [+0.0972, +0.3472] | 72 |
| gpt55_no_gate minus rule_based | +0.3009 | [+0.1204, +0.4815] | [+0.1620, +0.4398] | 72 |
| gpt55_advisory minus rule_based | +0.3009 | [+0.1204, +0.4815] | [+0.1620, +0.4398] | 72 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| rule_based | 17/36 | 19/36 |
| phi4_gated | 11/36 | 18/36 |
| phi4_no_gate | 10/36 | 16/36 |
| phi4_advisory | 13/36 | 17/36 |
| qwen25_gated | 12/36 | 17/36 |
| gpt55_gated | 24/36 | 27/36 |
| gpt55_no_gate | 27/36 | 31/36 |
| gpt55_advisory | 26/36 | 32/36 |
