# Holdout v4: the 14B scope-gate ablation against the enforcing arm

Harness: `benchmarks/holdout_v4/harness/holdout_v4_harness.jsonl` (72 items)

| Metric | phi4_gated | phi4_no_gate | phi4_advisory | qwen25_gated |
|---|---:|---:|---:|---:|
| Action accuracy | 29 (0.403) | 26 (0.361) | 30 (0.417) | 29 (0.403) |
| EXECUTE correct | 8/24 | 14/24 | 15/24 | 10/24 |
| CLARIFY correct | 4/4 | 4/4 | 4/4 | 4/4 |
| REJECT correct | 1/8 | 1/8 | 1/8 | 1/8 |
| UNSUPPORTED correct | 16/36 | 7/36 | 10/36 | 14/36 |
| Task completion (gold-aware) | 29 (0.403) | 26 (0.361) | 30 (0.417) | 29 (0.403) |
| Field exact match on EXECUTE | 0.381 | 0.595 | 0.631 | 0.452 |
| False acceptance | 15 (0.208) | 17 (0.236) | 15 (0.208) | 21 (0.292) |
| Valid schedule on gold EXECUTE | 8/24 | 14/24 | 15/24 | 10/24 |
| Paraphrase-consistent groups | 21/36 | 23/36 | 23/36 | 22/36 |
| Semantic / schedule / infra failures | 43 / 0 / 0 | 46 / 0 / 0 | 42 / 0 / 0 | 43 / 0 / 0 |
| Retries / calls / tokens | 15 / 58 / 50012 | 15 / 78 / 66191 | 16 / 79 / 69405 | 14 / 57 / 50513 |
| Mean wall seconds | 1.49 | 1.77 | 1.85 | 1.56 |

## Paired action-accuracy differences, resampling by paraphrase_group

| Comparison | Mean difference | 95% CI | 95% CI by request | Pairs |
|---|---:|---|---|---:|
| phi4_no_gate minus phi4_gated | -0.0417 | [-0.1667, +0.0833] | [-0.1528, +0.0694] | 72 |
| phi4_advisory minus phi4_gated | +0.0139 | [-0.1111, +0.1389] | [-0.0972, +0.1250] | 72 |
| qwen25_gated minus phi4_gated | +0.0000 | [-0.0556, +0.0556] | [-0.0556, +0.0556] | 72 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| phi4_gated | 11/36 | 18/36 |
| phi4_no_gate | 10/36 | 16/36 |
| phi4_advisory | 13/36 | 17/36 |
| qwen25_gated | 12/36 | 17/36 |
