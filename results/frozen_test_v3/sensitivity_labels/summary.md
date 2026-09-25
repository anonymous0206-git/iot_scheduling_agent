# Sensitivity of the Frozen Test v3 results to the contested gold labels

Re-scoring of the same ledgers under alternative labellings of the contested gold items. No model, scheduler or validator was invoked.

## Action accuracy, mean over repeats

| arm | published | channel=CLARIFY | range dropped | both | all 4 groups dropped |
| --- | --- | --- | --- | --- | --- |
| gpt55_advisory | 0.8958 | 0.9190 | 0.9214 | 0.9453 | 0.9461 |
| gpt55_gated | 0.8449 | 0.8681 | 0.8643 | 0.8881 | 0.8873 |
| gpt55_no_gate | 0.9121 | 0.9398 | 0.9238 | 0.9524 | 0.9510 |
| phi4_advisory | 0.4792 | 0.4514 | 0.4786 | 0.4500 | 0.4632 |
| phi4_gated | 0.4444 | 0.4167 | 0.4429 | 0.4143 | 0.4265 |
| phi4_no_gate | 0.4653 | 0.4375 | 0.4643 | 0.4357 | 0.4485 |
| qwen25 | 0.3750 | 0.3542 | 0.3786 | 0.3571 | 0.3676 |
| rule_based | 0.3819 | 0.3819 | 0.3929 | 0.3929 | 0.4044 |

## False acceptance, mean count over repeats

| arm | published | channel=CLARIFY | range dropped | both | all 4 groups dropped |
| --- | --- | --- | --- | --- | --- |
| gpt55_advisory | 3.6667 | 3.6667 | 0.3333 | 0.3333 | 0.3333 |
| gpt55_gated | 3.3333 | 3.3333 | 0 | 0 | 0 |
| gpt55_no_gate | 2 | 2 | 0 | 0 | 0 |
| phi4_advisory | 30 | 30 | 28 | 28 | 28 |
| phi4_gated | 30 | 30 | 28 | 28 | 28 |
| phi4_no_gate | 33 | 33 | 31 | 31 | 31 |
| qwen25 | 54 | 54 | 51 | 51 | 50 |
| rule_based | 74 | 74 | 70 | 70 | 66 |

## Paired differences, group-clustered bootstrap

| comparison | published | channel=CLARIFY | range dropped | both | all 4 groups dropped |
| --- | --- | --- | --- | --- | --- |
| gpt55_advisory minus gpt55_gated | +0.0509 [+0.0046, +0.1065] | +0.0509 [+0.0046, +0.1065] | +0.0571 [+0.0119, +0.1143] | +0.0571 [+0.0119, +0.1143] | +0.0588 [+0.0123, +0.1152] |
| gpt55_advisory minus gpt55_no_gate | -0.0162 [-0.0463, +0.0046] | -0.0208 [-0.0509, +0.0000] | -0.0024 [-0.0167, +0.0095] | -0.0071 [-0.0214, +0.0024] | -0.0049 [-0.0172, +0.0049] |
| gpt55_no_gate minus gpt55_gated | +0.0671 [+0.0208, +0.1227] | +0.0718 [+0.0255, +0.1273] | +0.0595 [+0.0143, +0.1167] | +0.0643 [+0.0190, +0.1214] | +0.0637 [+0.0172, +0.1201] |
| phi4_advisory minus phi4_gated | +0.0347 [-0.0208, +0.0903] | +0.0347 [-0.0208, +0.0903] | +0.0357 [-0.0214, +0.0929] | +0.0357 [-0.0214, +0.0929] | +0.0368 [-0.0147, +0.0956] |
| phi4_advisory minus phi4_no_gate | +0.0139 [+0.0000, +0.0347] | +0.0139 [+0.0000, +0.0347] | +0.0143 [+0.0000, +0.0357] | +0.0143 [+0.0000, +0.0357] | +0.0147 [+0.0000, +0.0368] |
| phi4_no_gate minus phi4_gated | +0.0208 [-0.0347, +0.0833] | +0.0208 [-0.0347, +0.0833] | +0.0214 [-0.0357, +0.0857] | +0.0214 [-0.0357, +0.0857] | +0.0221 [-0.0368, +0.0882] |

## Variants

* **published** --- the sealed gold labels, unchanged
* **channel=CLARIFY** --- the two channel-conflict groups read as CLARIFY instead of REJECT
* **range dropped** --- the two range-mismatch groups removed from the denominator
* **both** --- channel conflicts read as CLARIFY and range mismatches dropped
* **all 4 groups dropped** --- every contested item removed, the reading that trusts none of them
