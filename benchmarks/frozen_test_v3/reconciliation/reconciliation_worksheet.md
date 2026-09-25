# Frozen Test v2 human-adjudication worksheet

Generated: 2026-09-14T06:06:16Z

No disagreement was resolved automatically. Record a decision for every group listed under "Groups requiring a human decision" in a decisions JSON file (start from human_decisions_template.json) before sealing.

## Summary

| Classification | Groups |
|---|---:|
| FULL_AGREEMENT | 63 |
| FIELD_DISAGREEMENT | 0 |
| ACTION_DISAGREEMENT | 0 |
| PARAPHRASE_MISMATCH | 8 |
| DEFECTIVE_ITEM | 1 |

Groups: 72; requests: 144; groups requiring a human decision: 9

## Groups requiring a human decision

### v3-b-002 (frontier-model-b) - PARAPHRASE_MISMATCH

- Generator: action=EXECUTE, difficulty=hard, category=negated_digital_twin_hard_negative, ambiguity_risk=low
- Generator fields: `{"channels": 2, "collision_model": "legacy_neighbor", "communication_range": 20.0, "interference_ratio": 1.0, "latency_target_slots": null, "objective": "minimize_latency", "seed": 0, "topology_id": "topo150_seed0", "working_period": 10, "workload": "one_shot"}`
- Reviewer: action=EXECUTE, paraphrase_equivalent=False, item_quality=revise
- Reviewer fields: `{"channels": 2, "collision_model": "legacy_neighbor", "communication_range": 20.0, "interference_ratio": 1.0, "latency_target_slots": null, "objective": "minimize_latency", "seed": 0, "topology_id": "topo150_seed0", "working_period": 10, "workload": "one_shot"}`
- Reviewer reason: EXECUTE is the natural scheduling-context reading, and Digital Twin construction is negated. However, p2 specifies the input and defaults without stating the aggregation-schedule deliverable requested in p1. In isolation its task is underspecified, making CLARIFY defensible. The fields describe the scheduling reading, not a silent repair of p2.
- Signals:
  - reviewer judged the paraphrases not equivalent
  - reviewer item_quality=revise
- Paraphrases:
  - `v3-b-002-p1`: We are not building a Digital Twin of this deployment. All I need is the aggregation schedule for topo150_seed0, worked out from the stored topology with the usual settings.
  - `v3-b-002-p2`: Work from the stored topology file for topo150_seed0 and nothing else, default settings throughout. No Digital Twin is to be built for it.
- Decision needed: resolution (keep, keep_with_edits, exclude), final_action, final_fields, final_invalid_fields, paraphrase_equivalent, rationale.

### v3-b-008 (frontier-model-b) - PARAPHRASE_MISMATCH

- Generator: action=EXECUTE, difficulty=hard, category=historical_energy_mention_hard_negative, ambiguity_risk=low
- Generator fields: `{"channels": 5, "collision_model": "legacy_neighbor", "communication_range": 20.0, "interference_ratio": 1.0, "latency_target_slots": null, "objective": "minimize_latency", "seed": 21, "topology_id": "topo150_seed0", "working_period": 10, "workload": "one_shot"}`
- Reviewer: action=EXECUTE, paraphrase_equivalent=False, item_quality=revise
- Reviewer fields: `{"channels": 5, "collision_model": "legacy_neighbor", "communication_range": 20.0, "interference_ratio": 1.0, "latency_target_slots": null, "objective": "minimize_latency", "seed": 21, "topology_id": "topo150_seed0", "working_period": 10, "workload": "one_shot"}`
- Reviewer reason: The execution requirements match and battery-based planning is excluded, so EXECUTE is stable. However, p2 adds that the older planner was benchmarked last year, a fact absent from p1. This violates the strict same-facts construction rule even though it does not change the configuration.
- Signals:
  - reviewer judged the paraphrases not equivalent
  - reviewer item_quality=revise
- Paraphrases:
  - `v3-b-008-p1`: An older planner of ours used to spread battery drain across the nodes, but that comparison is not part of this run. Schedule topo150_seed0 with five channels and seed 21, with latency the only thing being minimized.
  - `v3-b-008-p2`: Leave the battery-spreading planner we benchmarked last year out of it. This run is topo150_seed0, five channels, scheduler seed 21, minimizing latency alone.
- Decision needed: resolution (keep, keep_with_edits, exclude), final_action, final_fields, final_invalid_fields, paraphrase_equivalent, rationale.

### v3-b-010 (frontier-model-b) - PARAPHRASE_MISMATCH

- Generator: action=EXECUTE, difficulty=hard, category=latency_target_below_baseline, ambiguity_risk=low
- Generator fields: `{"channels": 2, "collision_model": "legacy_neighbor", "communication_range": 20.0, "interference_ratio": 1.0, "latency_target_slots": 20, "objective": "minimize_latency", "seed": 0, "topology_id": "topo100_seed0", "working_period": 10, "workload": "one_shot"}`
- Reviewer: action=EXECUTE, paraphrase_equivalent=False, item_quality=revise
- Reviewer fields: `{"channels": 2, "collision_model": "legacy_neighbor", "communication_range": 20.0, "interference_ratio": 1.0, "latency_target_slots": 20, "objective": "minimize_latency", "seed": 0, "topology_id": "topo100_seed0", "working_period": 10, "workload": "one_shot"}`
- Reviewer reason: Both have the same valid 20-slot target and comparison requirement; a target below the 29-slot baseline remains EXECUTE. Under the strict same-facts rule, p2 drops p1's statement that the deadline comes from a downstream job. Preserve that context in both texts.
- Signals:
  - reviewer judged the paraphrases not equivalent
  - reviewer item_quality=revise
- Paraphrases:
  - `v3-b-010-p1`: The downstream job wants the topo100_seed0 aggregation finished inside 20 slots. Schedule against that figure and report how the result compares.
  - `v3-b-010-p2`: Aim for 20 elapsed slots on the topo100_seed0 collection, and let me know where the produced schedule lands against it.
- Decision needed: resolution (keep, keep_with_edits, exclude), final_action, final_fields, final_invalid_fields, paraphrase_equivalent, rationale.

### v3-b-018 (frontier-model-b) - DEFECTIVE_ITEM

- Generator: action=REJECT, difficulty=hard, category=contradictory_channel_specification, ambiguity_risk=medium
- Generator fields: `{"channels": null, "collision_model": "legacy_neighbor", "seed": 4, "topology_id": "topo200_seed0"}`
- Generator invalid_fields: `{"channels": {"observed": {"parameter_block": 5, "prose": 2}, "reason": "The prose and the pasted parameter block give different channel counts for the same run."}}`
- Reviewer: action=REJECT, paraphrase_equivalent=True, item_quality=revise
- Reviewer fields: `{"collision_model": "legacy_neighbor", "seed": 4, "topology_id": "topo200_seed0"}`
- Reviewer reason: REJECT applies when both prose and parameter block are current requirements. However, both texts explicitly identify the five-channel settings as historical, making EXECUTE with channels=2 defensible as a current override of the prior configuration. The contradiction is therefore not unambiguous. No scalar channels value has been silently selected.
- Signals:
  - reviewer item_quality=revise
  - reviewer did not enumerate invalid_fields; only overlapping explicit values were compared
  - generator ambiguity_risk=medium
- Paraphrases:
  - `v3-b-018-p1`: We are keeping this one on two channels. Parameters as run last time: topology topo200_seed0, channels 5, seed 4, collision_model legacy_neighbor.
  - `v3-b-018-p2`: Two channels for this collection please. Settings copied straight from the previous ticket: topo200_seed0, channels: 5, seed: 4, collision_model: legacy_neighbor.
- Decision needed: resolution (keep, keep_with_edits, exclude), final_action, final_fields, final_invalid_fields, paraphrase_equivalent, rationale.

### v3-b-021 (frontier-model-b) - PARAPHRASE_MISMATCH

- Generator: action=UNSUPPORTED, difficulty=hard, category=charge_driven_forwarding_compositional, ambiguity_risk=low
- Generator fields: `null`
- Reviewer: action=UNSUPPORTED, paraphrase_equivalent=False, item_quality=revise
- Reviewer fields: `null`
- Reviewer reason: Both require charge-dependent forwarding and are unsupported. However, preferring the node with the most charge at the time does not impose the same selection rule as excluding depleted nodes. P2 also loses p1's explicit time-dependent maximum-charge preference. The pair needs a common forwarding requirement.
- Signals:
  - reviewer judged the paraphrases not equivalent
  - reviewer item_quality=revise
- Paraphrases:
  - `v3-b-021-p1`: The motes on topo200_seed0 run off small solar cells and hold very different amounts of charge, so the forwarding choices should lean on whichever node has the most at the time.
  - `v3-b-021-p2`: Charge levels vary a lot across the solar-powered motes of topo200_seed0; whoever forwards should be picked to match, leaving the depleted ones out of it.
- Decision needed: resolution (keep, keep_with_edits, exclude), final_action, final_fields, final_invalid_fields, paraphrase_equivalent, rationale.

### v3-b-022 (frontier-model-b) - PARAPHRASE_MISMATCH

- Generator: action=UNSUPPORTED, difficulty=hard, category=network_lifetime_objective_compositional, ambiguity_risk=low
- Generator fields: `null`
- Reviewer: action=UNSUPPORTED, paraphrase_equivalent=False, item_quality=revise
- Reviewer fields: `null`
- Reviewer reason: Both prioritize time to first node failure rather than aggregation latency, so UNSUPPORTED is stable without assuming battery depletion causes failure. P1 additionally requires continued field reporting over weeks; p2 states only delayed failure and could permit inactivity. Preserve the reporting requirement in both.
- Signals:
  - reviewer judged the paraphrases not equivalent
  - reviewer item_quality=revise
- Paraphrases:
  - `v3-b-022-p1`: What I want for topo50_seed0 is the plan that keeps the whole field reporting for as many weeks as it can before the first node goes dark.
  - `v3-b-022-p2`: Choose the plan for topo50_seed0 that pushes the first node failure as far out in time as possible.
- Decision needed: resolution (keep, keep_with_edits, exclude), final_action, final_fields, final_invalid_fields, paraphrase_equivalent, rationale.

### v3-b-023 (frontier-model-b) - PARAPHRASE_MISMATCH

- Generator: action=UNSUPPORTED, difficulty=easy, category=digital_twin_construction, ambiguity_risk=none
- Generator fields: `null`
- Reviewer: action=UNSUPPORTED, paraphrase_equivalent=False, item_quality=revise
- Reviewer fields: `null`
- Reviewer reason: Both require a Digital Twin and aggregation inside it. P1 also requests that the team can watch the slots progress, which p2 does not preserve. The unsupported action remains unambiguous, but the observable-execution requirement should match.
- Signals:
  - reviewer judged the paraphrases not equivalent
  - reviewer item_quality=revise
- Paraphrases:
  - `v3-b-023-p1`: Stand up a Digital Twin of topo300_seed0 and run the collection inside it so the team can watch the slots go by.
  - `v3-b-023-p2`: I would like topo300_seed0 mirrored as a Digital Twin, with the aggregation carried out in that mirror.
- Decision needed: resolution (keep, keep_with_edits, exclude), final_action, final_fields, final_invalid_fields, paraphrase_equivalent, rationale.

### v3-b-034 (frontier-model-b) - PARAPHRASE_MISMATCH

- Generator: action=UNSUPPORTED, difficulty=easy, category=physical_device_control_mixed, ambiguity_risk=none
- Generator fields: `null`
- Reviewer: action=UNSUPPORTED, paraphrase_equivalent=False, item_quality=revise
- Reviewer fields: `null`
- Reviewer reason: Both require deploying a schedule to physical motes and controlling transmissions, so UNSUPPORTED is stable. P1 additionally requires scheduled waking; p2 only requires transmitting on cue and does not preserve wake control.
- Signals:
  - reviewer judged the paraphrases not equivalent
  - reviewer item_quality=revise
- Paraphrases:
  - `v3-b-034-p1`: Work out the schedule for topo50_seed0 and then push it down to the motes so they wake and send in their assigned slots.
  - `v3-b-034-p2`: When the topo50_seed0 schedule is ready, load it onto the physical motes and have them start transmitting on cue.
- Decision needed: resolution (keep, keep_with_edits, exclude), final_action, final_fields, final_invalid_fields, paraphrase_equivalent, rationale.

### v3-b-035 (frontier-model-b) - PARAPHRASE_MISMATCH

- Generator: action=UNSUPPORTED, difficulty=hard, category=load_balancing_compositional, ambiguity_risk=low
- Generator fields: `null`
- Reviewer: action=UNSUPPORTED, paraphrase_equivalent=False, item_quality=revise
- Reviewer fields: `null`
- Reviewer reason: Both request load balancing at the expense of latency, an unsupported objective. However, three nodes next to the sink and the sink's immediate neighbors need not denote the same set. The catalogue does not establish that equivalence. P2 also changes disproportionate work into carrying most traffic.
- Signals:
  - reviewer judged the paraphrases not equivalent
  - reviewer item_quality=revise
- Paraphrases:
  - `v3-b-035-p1`: The three nodes next to the sink on topo300_seed0 are doing far more work than the rest, and the plan should even that out across the field even if the round takes longer.
  - `v3-b-035-p2`: On topo300_seed0 the sink's immediate neighbours carry most of the traffic; spread that load more evenly, longer round or not.
- Decision needed: resolution (keep, keep_with_edits, exclude), final_action, final_fields, final_invalid_fields, paraphrase_equivalent, rationale.

## Groups in full agreement

| Group | Batch | Action | Difficulty | Category |
|---|---|---|---|---|
| v3-a-001 | frontier-model-a | EXECUTE | easy | standard_latency_report |
| v3-a-002 | frontier-model-a | EXECUTE | medium | generation_seed_not_scheduler_seed |
| v3-a-003 | frontier-model-a | EXECUTE | hard | digital_twin_explicitly_excluded |
| v3-a-004 | frontier-model-a | EXECUTE | hard | past_continuous_collection_context |
| v3-a-005 | frontier-model-a | EXECUTE | easy | single_channel_neighbor_seed |
| v3-a-006 | frontier-model-a | EXECUTE | medium | range_model_matching_geometry |
| v3-a-007 | frontier-model-a | EXECUTE | hard | historical_battery_objective_excluded |
| v3-a-008 | frontier-model-a | EXECUTE | medium | large_valid_channel_count |
| v3-a-009 | frontier-model-a | EXECUTE | easy | above_topology_baseline |
| v3-a-010 | frontier-model-a | EXECUTE | hard | valid_target_below_baseline |
| v3-a-011 | frontier-model-a | EXECUTE | medium | explicit_absence_of_target |
| v3-a-012 | frontier-model-a | CLARIFY | easy | topology_absent |
| v3-a-013 | frontier-model-a | CLARIFY | medium | two_catalogue_ids_one_run |
| v3-a-014 | frontier-model-a | CLARIFY | hard | unresolved_material_channel_setting |
| v3-a-015 | frontier-model-a | REJECT | easy | unlisted_topology |
| v3-a-016 | frontier-model-a | REJECT | medium | unequal_interference_range |
| v3-a-017 | frontier-model-a | REJECT | medium | catalogue_range_mismatch |
| v3-a-018 | frontier-model-a | REJECT | hard | prose_parameter_channel_conflict |
| v3-a-019 | frontier-model-a | UNSUPPORTED | easy | explicit_energy_aware_selection |
| v3-a-020 | frontier-model-a | UNSUPPORTED | medium | per_transmission_charge_accounting |
| v3-a-021 | frontier-model-a | UNSUPPORTED | hard | charge_constrained_latency |
| v3-a-022 | frontier-model-a | UNSUPPORTED | medium | battery_trajectory_report |
| v3-a-023 | frontier-model-a | UNSUPPORTED | easy | digital_twin_execution |
| v3-a-024 | frontier-model-a | UNSUPPORTED | medium | packet_level_network_emulation |
| v3-a-025 | frontier-model-a | UNSUPPORTED | hard | live_state_updates_after_schedule |
| v3-a-026 | frontier-model-a | UNSUPPORTED | medium | explicit_streaming_mirror |
| v3-a-027 | frontier-model-a | UNSUPPORTED | easy | finite_periodic_collection |
| v3-a-028 | frontier-model-a | UNSUPPORTED | medium | restart_after_completion |
| v3-a-029 | frontier-model-a | UNSUPPORTED | hard | ongoing_deadline_collection |
| v3-a-030 | frontier-model-a | UNSUPPORTED | medium | replan_on_node_departure |
| v3-a-031 | frontier-model-a | UNSUPPORTED | hard | live_route_replacement |
| v3-a-032 | frontier-model-a | UNSUPPORTED | medium | integrate_joining_nodes |
| v3-a-033 | frontier-model-a | UNSUPPORTED | easy | minimize_transmission_total |
| v3-a-034 | frontier-model-a | UNSUPPORTED | medium | minimax_sender_load |
| v3-a-035 | frontier-model-a | UNSUPPORTED | hard | device_control_precedes_bad_channel_value |
| v3-a-036 | frontier-model-a | UNSUPPORTED | medium | minimize_channel_usage_objective |
| v3-b-001 | frontier-model-b | EXECUTE | easy | default_execution_without_seed |
| v3-b-003 | frontier-model-b | EXECUTE | hard | excluded_stream_hard_negative |
| v3-b-004 | frontier-model-b | EXECUTE | easy | default_execution_alternate_range |
| v3-b-005 | frontier-model-b | EXECUTE | medium | explicit_channels_and_seed |
| v3-b-006 | frontier-model-b | EXECUTE | medium | interference_range_with_explicit_ratio |
| v3-b-007 | frontier-model-b | EXECUTE | medium | explicit_consistent_topology_parameters |
| v3-b-009 | frontier-model-b | EXECUTE | medium | latency_target_above_baseline |
| v3-b-011 | frontier-model-b | EXECUTE | medium | explicit_null_latency_target |
| v3-b-012 | frontier-model-b | CLARIFY | easy | missing_topology_id |
| v3-b-013 | frontier-model-b | CLARIFY | medium | ambiguous_topology_selection |
| v3-b-014 | frontier-model-b | CLARIFY | medium | ambiguous_channel_count |
| v3-b-015 | frontier-model-b | REJECT | easy | nonexistent_topology_id |
| v3-b-016 | frontier-model-b | REJECT | medium | interference_ratio_above_one |
| v3-b-017 | frontier-model-b | REJECT | medium | communication_range_mismatch |
| v3-b-019 | frontier-model-b | UNSUPPORTED | easy | energy_aware_scheduling |
| v3-b-020 | frontier-model-b | UNSUPPORTED | medium | residual_battery_evolution_mixed |
| v3-b-024 | frontier-model-b | UNSUPPORTED | hard | software_replica_compositional |
| v3-b-025 | frontier-model-b | UNSUPPORTED | medium | continuous_state_alignment_compositional_mixed |
| v3-b-026 | frontier-model-b | UNSUPPORTED | easy | streaming_view |
| v3-b-027 | frontier-model-b | UNSUPPORTED | easy | periodic_rounds |
| v3-b-028 | frontier-model-b | UNSUPPORTED | medium | repeating_pull_compositional |
| v3-b-029 | frontier-model-b | UNSUPPORTED | hard | self_repeating_schedule_compositional_mixed |
| v3-b-030 | frontier-model-b | UNSUPPORTED | medium | runtime_adaptation |
| v3-b-031 | frontier-model-b | UNSUPPORTED | hard | mid_round_reparenting_compositional |
| v3-b-032 | frontier-model-b | UNSUPPORTED | hard | runtime_rerouting_with_invalid_range |
| v3-b-033 | frontier-model-b | UNSUPPORTED | medium | minimize_transmission_count |
| v3-b-036 | frontier-model-b | UNSUPPORTED | hard | delivery_reliability_compositional |
