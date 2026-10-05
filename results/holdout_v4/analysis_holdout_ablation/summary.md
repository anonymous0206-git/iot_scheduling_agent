# Holdout v4: the ablation against the enforcing arm

Harness: `benchmarks/holdout_v4/harness/holdout_v4_harness.jsonl` (72 items)

| Metric | gpt55_gated | gpt55_no_gate | gpt55_advisory |
|---|---:|---:|---:|
| Action accuracy | 52 (0.722) | 58 (0.801) | 58 (0.801) |
| EXECUTE correct | 12/24 | 19/24 | 19/24 |
| CLARIFY correct | 4/4 | 4/4 | 4/4 |
| REJECT correct | 1/8 | 1/8 | 1/8 |
| UNSUPPORTED correct | 35/36 | 34/36 | 34/36 |
| Task completion (gold-aware) | 52 (0.722) | 58 (0.801) | 58 (0.801) |
| Field exact match on EXECUTE | 0.524 | 0.762 | 0.774 |
| False acceptance | 4 (0.056) | 4 (0.056) | 4 (0.060) |
| Valid schedule on gold EXECUTE | 11/24 | 19/24 | 19/24 |
| Paraphrase-consistent groups | 30/36 | 30/36 | 32/36 |
| Semantic / schedule / infra failures | 21 / 0 / 0 | 14 / 0 / 0 | 14 / 0 / 0 |
| Retries / calls / tokens | 17 / 60 / 82891 | 18 / 80 / 109144 | 16 / 80 / 108340 |
| Mean wall seconds | 3.40 | 4.44 | 4.26 |

## Paired action-accuracy differences, resampling by paraphrase_group

| Comparison | Mean difference | 95% CI | 95% CI by request | Pairs |
|---|---:|---|---|---:|
| gpt55_no_gate minus gpt55_gated | +0.0787 | [-0.0139, +0.1852] | [+0.0046, +0.1574] | 72 |
| gpt55_advisory minus gpt55_gated | +0.0787 | [-0.0139, +0.1898] | [+0.0046, +0.1574] | 72 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| gpt55_gated | 24/36 | 27/36 |
| gpt55_no_gate | 27/36 | 31/36 |
| gpt55_advisory | 26/36 | 32/36 |
