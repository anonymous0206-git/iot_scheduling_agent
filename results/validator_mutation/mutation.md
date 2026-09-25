# Validator mutation test

945 mutants over 7 topologies; 945 rejected, 0 survivors.

Every mutant is one certified schedule with one injected defect. `rejected` is what
the guarantee needs; `targeted` is the stronger reading, that the check aimed at
fired rather than a side effect of the mutation.

## By condition

| Condition | Mutants | Rejected | Targeted | Statement |
|---|---:|---:|---:|---|
| (i) | 168 | 168 (1.000) | 168 (1.000) | every non-sink node transmits exactly once |
| (ii) | 84 | 84 (1.000) | 84 (1.000) | a transmission uses a communication link |
| (iii) | 26 | 26 (1.000) | 26 (1.000) | the sink never transmits |
| (iv) | 247 | 247 (1.000) | 247 (1.000) | no two transmissions sharing a slot and a channel collide |
| (v) | 84 | 84 (1.000) | 84 (1.000) | a node transmits only after every node it receives from |
| beyond | 336 | 336 (1.000) | 336 (1.000) | checks the validator makes beyond conditions (i)-(v) |

## By operator

| Operator | Condition | Expected code | Mutants | Rejected | Targeted |
|---|---|---|---:|---:|---:|
| `drop_transmission` | (i) | `MISSING_TRANSMISSION` | 84 | 84 | 84 |
| `duplicate_transmission` | (i) | `DUPLICATE_TRANSMISSION` | 84 | 84 | 84 |
| `non_neighbour_receiver` | (ii) | `NON_NEIGHBOR_LINK` | 84 | 84 | 84 |
| `sink_transmits` | (iii) | `SINK_TRANSMISSION` | 26 | 26 | 26 |
| `primary_collision` | (iv) | `PRIMARY_COLLISION` | 79 | 79 | 79 |
| `secondary_collision` | (iv) | `SECONDARY_COLLISION` | 84 | 84 | 84 |
| `half_duplex` | (iv) | `HALF_DUPLEX_VIOLATION` | 84 | 84 | 84 |
| `precedence_inversion` | (v) | `PRECEDENCE_VIOLATION` | 84 | 84 | 84 |
| `channel_out_of_range` | beyond | `INVALID_CHANNEL` | 84 | 84 | 84 |
| `unknown_receiver` | beyond | `UNKNOWN_RECEIVER` | 84 | 84 | 84 |
| `active_slot_field_mismatch` | beyond | `ACTIVE_SLOT_FIELD_MISMATCH` | 84 | 84 | 84 |
| `parent_cycle` | beyond | `PARENT_CYCLE` | 84 | 84 | 84 |
