# Ledger audit tables

Harness: `benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl` (144 items)

## Which stage decided the request

| Arm | scope_gate | parameter_check | topology_gate | baseline_filter | model | none | unclassified | decided pre-model | errors forced / total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rule_based | 0 | 1 | 0 | 18 | 0 | 125 | 0 | 1 | 1 / 90 |
| phi4_gated | 18 | 1 | 12 | 0 | 113 | 0 | 0 | 31 | 12 / 80 |
| phi4_no_gate | 0 | 1 | 12 | 0 | 131 | 0 | 0 | 13 | 5 / 77 |
| qwen25 | 18 | 1 | 12 | 0 | 113 | 0 | 0 | 31 | 12 / 89 |
| gpt55_gated | 18 | 1 | 12 | 0 | 113 | 0 | 0 | 31 | 12 / 22 |
| gpt55_no_gate | 0 | 1 | 12 | 0 | 131 | 0 | 0 | 13 | 5 / 14 |

`decided pre-model` counts the three stages every gated arm shares;
an arm with no model behind it refuses under `baseline_filter`, which is a
different implementation and is not part of that count.

## False acceptance, by item

Item identities matter here because two arms can differ by one in count
while differing by more than one in membership. Sets longer than
12 items are in `false_acceptance.json` rather than inline.

* **rule_based** — 77, over 39 categories; most frequent: ambiguous_channel_count (2), catalogue_range_mismatch (2), charge_constrained_latency (2), charge_driven_forwarding_compositional (2), communication_range_mismatch (2)
* **phi4_gated** — 30, over 23 categories; most frequent: charge_constrained_latency (2), charge_driven_forwarding_compositional (2), delivery_reliability_compositional (2), ongoing_deadline_collection (2), packet_level_network_emulation (2)
* **phi4_no_gate** — 33, over 24 categories; most frequent: charge_constrained_latency (2), charge_driven_forwarding_compositional (2), delivery_reliability_compositional (2), finite_periodic_collection (2), ongoing_deadline_collection (2)
* **qwen25** — 54, over 30 categories; most frequent: ambiguous_channel_count (2), charge_constrained_latency (2), charge_driven_forwarding_compositional (2), communication_range_mismatch (2), continuous_state_alignment_compositional_mixed (2)
* **gpt55_gated** — 3: `ft3-r0033` (communication_range_mismatch), `ft3-r0130` (communication_range_mismatch), `ft3-r0141` (catalogue_range_mismatch)
* **gpt55_no_gate** — 2: `ft3-r0033` (communication_range_mismatch), `ft3-r0106` (catalogue_range_mismatch)

## Per batch

| Arm | frontier-model-a | frontier-model-b | widest gap |
|---|---:|---:|---:|
| rule_based | 28/72 | 26/72 | 2 |
| phi4_gated | 30/72 | 34/72 | 4 |
| phi4_no_gate | 32/72 | 35/72 | 3 |
| qwen25 | 28/72 | 27/72 | 1 |
| gpt55_gated | 59/72 | 63/72 | 4 |
| gpt55_no_gate | 64/72 | 66/72 | 2 |

## What removing the scope gate changed

Recovered over-blocks are a cost the gate was imposing; lost refusals
are work the gate was doing that the model cannot do for itself.
Both columns are keyed on where the *gated* arm's answer came from.

| Pair | recovered over-blocks | other recoveries | correct refusals lost | model regressions | net |
|---|---:|---:|---:|---:|---:|
| gpt55_gated minus gpt55_no_gate | 7 | 2 | 0 | 1 | +8 |
| phi4_gated minus phi4_no_gate | 7 | 0 | 4 | 0 | +3 |

### gpt55_gated minus gpt55_no_gate

| Request | Gold | Gated | Ungated | Direction | Gated answer from |
|---|---|---|---|---|---|
| `ft3-r0017` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0032` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0040` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0059` | EXECUTE | REJECT | EXECUTE | wrong to right | model |
| `ft3-r0060` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0083` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0105` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0112` | REJECT | REJECT | CLARIFY | right to wrong | model |
| `ft3-r0118` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0141` | REJECT | EXECUTE | REJECT | wrong to right | model |

### phi4_gated minus phi4_no_gate

| Request | Gold | Gated | Ungated | Direction | Gated answer from |
|---|---|---|---|---|---|
| `ft3-r0008` | UNSUPPORTED | UNSUPPORTED | EXECUTE | right to wrong | gate |
| `ft3-r0017` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0032` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0040` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0049` | UNSUPPORTED | UNSUPPORTED | REJECT | right to wrong | gate |
| `ft3-r0060` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0083` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0105` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0118` | EXECUTE | UNSUPPORTED | EXECUTE | wrong to right | gate |
| `ft3-r0122` | UNSUPPORTED | UNSUPPORTED | EXECUTE | right to wrong | gate |
| `ft3-r0124` | UNSUPPORTED | UNSUPPORTED | EXECUTE | right to wrong | gate |
