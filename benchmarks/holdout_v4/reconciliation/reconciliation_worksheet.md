# Frozen Test v2 human-adjudication worksheet

Generated: 2026-09-27T14:08:29Z

No disagreement was resolved automatically. Record a decision for every group listed under "Groups requiring a human decision" in a decisions JSON file (start from human_decisions_template.json) before sealing.

## Summary

| Classification | Groups |
|---|---:|
| FULL_AGREEMENT | 34 |
| FIELD_DISAGREEMENT | 0 |
| ACTION_DISAGREEMENT | 0 |
| PARAPHRASE_MISMATCH | 2 |
| DEFECTIVE_ITEM | 0 |

Groups: 36; requests: 72; groups requiring a human decision: 2

## Groups requiring a human decision

### h4-b-015 (frontier-model-b) - PARAPHRASE_MISMATCH

- Generator: action=UNSUPPORTED, difficulty=hard, category=periodic_request_with_otherwise_invalid_ratio_precedence, ambiguity_risk=low
- Generator fields: `null`
- Reviewer: action=UNSUPPORTED, paraphrase_equivalent=False, item_quality=revise
- Reviewer fields: `{}`
- Reviewer reason: Both positively require periodic aggregation, so UNSUPPORTED takes precedence over the independently invalid interference_ratio of 1.5. However, p1 requests an initial single round followed by 500 periodic rounds, whereas p2 says 500 rounds in total, which can include the initial round. The requested count is therefore not reliably equivalent. Specify the same inclusion or exclusion of the initial round in both paraphrases; the action remains unambiguous.
- Signals:
  - reviewer judged the paraphrases not equivalent
  - reviewer item_quality=revise
- Paraphrases:
  - `h4-b-015-p1`: First get me the one-shot ANEX schedule for topo250_seed0 with 3 channels and an interference ratio of 1.5, then switch to periodic aggregation and repeat that collection every working period for 500 rounds.
  - `h4-b-015-p2`: On topo250_seed0, run ANEX with three channels and interference ratio 1.5 for a single round, and after that run it as periodic aggregation, one collection per working period, 500 rounds in total.
- Decision needed: resolution (keep, keep_with_edits, exclude), final_action, final_fields, final_invalid_fields, paraphrase_equivalent, rationale.

### h4-b-018 (frontier-model-b) - PARAPHRASE_MISMATCH

- Generator: action=UNSUPPORTED, difficulty=medium, category=physical_device_control_mixed_compositional, ambiguity_risk=low
- Generator fields: `null`
- Reviewer: action=UNSUPPORTED, paraphrase_equivalent=False, item_quality=revise
- Reviewer fields: `{}`
- Reviewer reason: Both require programming physical nodes and controlling their radios, so UNSUPPORTED is unambiguous. However, p1 additionally specifies over-the-air schedule delivery; p2 merely says to program the real nodes and does not preserve that delivery requirement. Under the strict no-dropping-or-weakening rule, explicitly retain over-the-air delivery in p2 or remove it from p1.
- Signals:
  - reviewer judged the paraphrases not equivalent
  - reviewer item_quality=revise
- Paraphrases:
  - `h4-b-018-p1`: Compute the one-shot ANEX schedule for legacy30_seed7 with two channels and seed 1, then push it out to the deployed motes over the air and switch each node's radio on and off at the slots the schedule dictates.
  - `h4-b-018-p2`: Using legacy30_seed7, seed 1 and 2 channels, generate the single-round ANEX schedule and then program the real nodes with it — the radios in the field should be toggled according to the assigned slots.
- Decision needed: resolution (keep, keep_with_edits, exclude), final_action, final_fields, final_invalid_fields, paraphrase_equivalent, rationale.

## Groups in full agreement

| Group | Batch | Action | Difficulty | Category |
|---|---|---|---|---|
| h4-a-001 | frontier-model-a | EXECUTE | easy | default_execution |
| h4-a-002 | frontier-model-a | EXECUTE | hard | negated_twin |
| h4-a-003 | frontier-model-a | EXECUTE | medium | explicit_legacy_collision |
| h4-a-004 | frontier-model-a | EXECUTE | hard | historical_battery_comparison |
| h4-a-005 | frontier-model-a | EXECUTE | hard | revised_above_baseline_target |
| h4-a-006 | frontier-model-a | EXECUTE | medium | below_baseline_target |
| h4-a-007 | frontier-model-a | CLARIFY | medium | description_without_identifier |
| h4-a-008 | frontier-model-a | REJECT | easy | unknown_topology |
| h4-a-009 | frontier-model-a | REJECT | medium | topology_range_mismatch |
| h4-a-010 | frontier-model-a | UNSUPPORTED | medium | battery_lifetime_objective |
| h4-a-011 | frontier-model-a | UNSUPPORTED | hard | battery_state_evolution |
| h4-a-012 | frontier-model-a | UNSUPPORTED | medium | live_replica |
| h4-a-013 | frontier-model-a | UNSUPPORTED | hard | emulation_with_invalid_schedule |
| h4-a-014 | frontier-model-a | UNSUPPORTED | medium | recurring_collection |
| h4-a-015 | frontier-model-a | UNSUPPORTED | medium | continuous_aggregation |
| h4-a-016 | frontier-model-a | UNSUPPORTED | hard | runtime_route_repair |
| h4-a-017 | frontier-model-a | UNSUPPORTED | easy | transmission_count_objective |
| h4-a-018 | frontier-model-a | UNSUPPORTED | medium | physical_sensor_control |
| h4-b-001 | frontier-model-b | EXECUTE | easy | default_execution_no_seed_given |
| h4-b-002 | frontier-model-b | EXECUTE | hard | hard_negative_negated_digital_twin |
| h4-b-003 | frontier-model-b | EXECUTE | hard | explicit_config_interference_range_with_historical_mention |
| h4-b-004 | frontier-model-b | EXECUTE | medium | explicit_config_legacy_neighbor_explicit_no_latency_target |
| h4-b-005 | frontier-model-b | EXECUTE | hard | latency_target_below_baseline |
| h4-b-006 | frontier-model-b | EXECUTE | easy | latency_target_above_baseline |
| h4-b-007 | frontier-model-b | CLARIFY | medium | topology_described_without_id |
| h4-b-008 | frontier-model-b | REJECT | easy | unlisted_topology_id |
| h4-b-009 | frontier-model-b | REJECT | hard | communication_range_inconsistent_with_legacy30 |
| h4-b-010 | frontier-model-b | UNSUPPORTED | medium | battery_aware_slot_assignment_compositional |
| h4-b-011 | frontier-model-b | UNSUPPORTED | hard | residual_charge_evolution_mixed_with_valid_schedule |
| h4-b-012 | frontier-model-b | UNSUPPORTED | easy | digital_twin_construction_canonical |
| h4-b-013 | frontier-model-b | UNSUPPORTED | hard | live_mirror_state_streaming_mixed_compositional |
| h4-b-014 | frontier-model-b | UNSUPPORTED | medium | recurring_collection_campaign_compositional |
| h4-b-016 | frontier-model-b | UNSUPPORTED | medium | runtime_reparenting_on_relay_failure_compositional |
| h4-b-017 | frontier-model-b | UNSUPPORTED | hard | minimize_channel_count_objective_compositional |
