# Ablation on clean sessions

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

| Metric | phi4_gated | phi4_no_gate | phi4_gated_s2 | phi4_no_gate_s2 |
|---|---:|---:|---:|---:|
| Action accuracy | 62 (0.431) | 65 (0.451) | 62 (0.431) | 65 (0.451) |
| EXECUTE correct | 22/44 | 29/44 | 22/44 | 29/44 |
| CLARIFY correct | 8/12 | 8/12 | 8/12 | 8/12 |
| REJECT correct | 10/16 | 10/16 | 10/16 | 10/16 |
| UNSUPPORTED correct | 22/72 | 18/72 | 22/72 | 18/72 |
| Task completion (gold-aware) | 62 (0.431) | 65 (0.451) | 62 (0.431) | 65 (0.451) |
| Field exact match on EXECUTE | 0.549 | 0.685 | 0.549 | 0.685 |
| False acceptance | 30 (0.208) | 33 (0.229) | 30 (0.208) | 33 (0.229) |
| Valid schedule on gold EXECUTE | 22/44 | 29/44 | 22/44 | 29/44 |
| Paraphrase-consistent groups | 44/72 | 45/72 | 44/72 | 45/72 |
| Semantic / schedule / infra failures | 82 / 0 / 0 | 79 / 0 / 0 | 82 / 0 / 0 | 79 / 0 / 0 |
| Retries / calls / tokens | 25 / 138 / 114949 | 25 / 156 / 129463 | 25 / 138 / 114949 | 25 / 156 / 129463 |
| Mean wall seconds | 2.10 | 1.58 | 2.47 | 1.60 |

## Paired action-accuracy differences

| Comparison | Mean difference | 95% CI | Pairs |
|---|---:|---|---:|
| phi4_no_gate minus phi4_gated | +0.0208 | [-0.0208, +0.0694] | 144 |
| phi4_gated_s2 minus phi4_gated | +0.0000 | [+0.0000, +0.0000] | 144 |
| phi4_no_gate_s2 minus phi4_gated | +0.0208 | [-0.0208, +0.0694] | 144 |

## Per batch

| Arm | frontier-model-a | frontier-model-b |
|---|---:|---:|
| phi4_gated | 30/72 | 32/72 |
| phi4_no_gate | 32/72 | 33/72 |
| phi4_gated_s2 | 30/72 | 32/72 |
| phi4_no_gate_s2 | 32/72 | 33/72 |
