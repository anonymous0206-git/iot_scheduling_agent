# Scope gate ablation under the repaired pipeline

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | gpt55_gated | gpt55_no_gate | phi4_gated | phi4_no_gate |
|---|---:|---:|---:|---:|
| Action accuracy | 122 (0.847) | 130 (0.903) | 61 (0.424) | 64 (0.444) |
| EXECUTE correct | 35/44 | 43/44 | 21/44 | 28/44 |
| CLARIFY correct | 12/12 | 12/12 | 8/12 | 8/12 |
| REJECT correct | 5/16 | 5/16 | 10/16 | 10/16 |
| UNSUPPORTED correct | 70/72 | 70/72 | 22/72 | 18/72 |
| Task completion (gold-aware) | 122 (0.847) | 130 (0.903) | 61 (0.424) | 64 (0.444) |
| Field exact match on EXECUTE | 0.799 | 0.951 | 0.529 | 0.666 |
| False acceptance | 3 (0.021) | 2 (0.014) | 29 (0.201) | 32 (0.222) |
| Valid schedule on gold EXECUTE | 35/44 | 43/44 | 21/44 | 28/44 |
| Paraphrase-consistent groups | 67/72 | 69/72 | 45/72 | 46/72 |
| Semantic / schedule / infra failures | 22 / 0 / 0 | 14 / 0 / 0 | 83 / 0 / 0 | 80 / 0 / 0 |
| Retries / calls / tokens | 14 / 127 / 170363 | 14 / 145 / 191030 | 27 / 140 / 116478 | 27 / 158 / 130994 |
| Mean wall seconds | 3.74 | 3.97 | 24.17 | 25.68 |

## Paired action-accuracy differences

| Comparison | Mean difference | 95% CI | Pairs |
|---|---:|---|---:|
| gpt55_no_gate minus gpt55_gated | +0.0556 | [+0.0139, +0.0972] | 144 |
| phi4_gated minus gpt55_gated | -0.4236 | [-0.5139, -0.3333] | 144 |
| phi4_no_gate minus gpt55_gated | -0.4028 | [-0.5069, -0.2986] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| gpt55_gated | 59/72 | 63/72 |
| gpt55_no_gate | 64/72 | 66/72 |
| phi4_gated | 30/72 | 31/72 |
| phi4_no_gate | 32/72 | 32/72 |
