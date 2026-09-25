# Legacy ANEX compatibility audit

## Scope and method

This audit characterizes the unmodified implementation under `source/`. It does
not correct or reinterpret the published algorithm. Regression tests live in
`tests/test_legacy_compatibility.py`; expected-failure tests are bounded,
executable defect reports rather than proposed behavior changes.

The reference fixture remains a generated 30-node connected topology with
seed 7, working period 10, two active slots, two channels, communication range
18, and interference ratio 1.5. Its published-compatible result is max timeslot
25, or 26 elapsed slots when slot zero is counted.

## Safe behavior

- A fixed generated topology produces a deterministic schedule. ANEX itself
  does not consume randomness; `AnexConfig.seed` affects generation only.
- `run_anex` deep-copies by default, so running it repeatedly on the same input
  topology is deterministic and leaves that topology unchanged.
- For the reference fixture, every non-sink node is scheduled and the existing
  independent validator accepts the schedule.
- Parent pointers and child lists are mutually consistent after a normal
  reference run, including after dynamic reparenting.
- Adapter configuration rejects non-positive working periods, channel counts,
  and communication ranges, and interference ratios below 1.
- The topology adapter rejects active-slot counts outside
  `1 <= count < working_period` and gives up after a bounded number of failed
  random-generation attempts.

## Compatibility quirks

- `gentopo.random_rect` samples from `range(0, working_period - 1)`. The final
  active slot is therefore never selected. This is preserved deliberately.
- Active-slot lists are unsorted `random.sample` results. Their order can break
  equal-delay parent-selection ties, so sorting them would be a behavior change.
- Topology generation calls `random.seed(seed)` and advances Python's
  module-global RNG. It does not isolate random state.
- Node IDs are assumed to equal list indices, with sink ID/index 0. Neighbor,
  parent, child, and descendant values are all used as list indices.
- Neighbor lists are assumed symmetric, duplicate-free, in range, and derived
  from Euclidean distance using the same communication range passed to ANEX.
- Every node is assumed to have at least one active slot in `[0, T-1]` and every
  reachable layer is assumed to have a feasible parent/active-slot pair.
- Inputs are mutable legacy `Node` objects. `copy_input=False` exposes all tree,
  schedule, layer, descendant, and interference mutations and is not safe for a
  second execution without a complete state reset.
- Channel numbers are one-based. Timeslots are zero-based absolute indices.
- `legacy_max_timeslot` is the largest index, not a duration. `elapsed_slots` is
  therefore `legacy_max_timeslot + 1`; the reference values are 25 and 26.
- Candidate and tie order follows list/index order. Set construction in layering
  is converted back to a list; integer iteration is stable in supported Python
  runtimes but is not an explicit algorithmic tie-break contract.
- The sink begins in the scheduler's completed set and is never assigned a
  transmit slot or channel.

## Confirmed bugs

- Disconnected input is not rejected by the legacy tree builder. `layering`
  loops forever once no new reachable node can be added. The bounded
  expected-failure test demonstrates the non-termination.
- The scheduling loop has no no-progress guard. If a full working period
  schedules nobody (for example, receivers have no active slots), it loops
  forever. A process-bounded expected-failure test reproduces this.
- Dynamic channel coloring allocates exactly seven color buckets
  (`range(1, 8)`). A configured channel count above seven cannot expose an
  eighth color; a constructed eight-way conflict leaves a sender unscheduled.
- ANEX computes `interfereIDs` using `communication_range * interference_ratio`
  but collision coloring consults `neighborIDs` instead. Consequently values of
  `interference_ratio > 1` enlarge stored interference lists without enforcing
  those additional conflicts. The validator intentionally mirrors this legacy
  neighbor-only model, so `validation.valid` does not mean alpha-expanded
  interference safety.
- The independent validator reports non-contiguous IDs but `run_anex` does not
  reject them before invoking index-based legacy code. Behavior can be wrong,
  misleading, or raise an unrelated exception.
- The validator does not check the bidirectional invariant
  `child.parentID == parent` iff `child in parent.childrenIDs`. A deliberately
  corrupted tree can therefore omit the expected relation-specific violation.
- Re-executing mutated nodes directly, or through `run_anex(...,
  copy_input=False)`, retains schedules and accumulated lists. The ANEX loop can
  then make no progress forever because its local completed set is reset while
  nodes remain marked scheduled.
- `Node.__init__` uses a mutable default for `active_slot`. Nodes constructed
  without an explicit list share that object. Current topology generators pass
  explicit lists, so the reference path is not affected.
- Tree construction can reference `temp_parent` before assignment if a node is
  layered but has no feasible active-slot comparison. This produces an
  `UnboundLocalError` rather than a domain-level rejection.

## Research decisions

The project decisions following this audit are recorded below. They are target
semantics for a future guarded/model-driven implementation, not retroactive
changes to the published legacy mode.

- **Interference model:** use an explicit interference multiplier `alpha`, with
  interference radius `communication_range * alpha`. Therefore `alpha == 1`
  gives the communication-neighbor model, `alpha > 1` expands the interference
  region, and `0 < alpha < 1` contracts it. `alpha` is dimensionless; setting
  `alpha == communication_range` does *not* recover communication neighbors.
  The current `AnexConfig` rejects `alpha < 1`, so contracted regions require a
  future configuration-policy change. The selected alpha must be reported with
  every experiment and supplied according to the user's requested model.
- **Duty-cycle domain:** define valid active slots as the complete zero-based
  interval `[0, T-1]`, including the final slot. Legacy generation's `[0, T-2]`
  behavior remains available only as an explicitly labeled compatibility mode
  because changing it changes seeded fixtures.
- **Channels:** support arbitrary positive channel counts. Coloring must create
  its channel domain from the requested count rather than a fixed seven-color
  map. Legacy seven-bucket behavior remains frozen for compatibility comparisons.
- **Input policy:** validate before invoking scheduling and reject malformed or
  sink-disconnected topologies with actionable diagnostics. Do not pass such
  inputs into legacy layering, and do not silently normalize topology structure.
  An agent may explain which nodes/edges or identifiers need correction and ask
  the user for an updated topology.
- **Repeat-run policy:** prohibit reuse of already-mutated scheduling state.
  Public execution should operate from a fresh/deep-copied topology. An explicit
  in-place call must reject nodes that already contain derived tree, schedule,
  descendant, layer, or interference state rather than attempting a partial
  reset.
- **Deterministic tie-breaking:** canonicalize all decision inputs without
  rewriting the user's topology: iterate candidate node IDs in ascending order;
  inspect active slots in ascending numeric order; choose the lowest parent ID
  when link delay and all preceding objective values tie; choose the lowest
  channel number that satisfies constraints; and serialize children, neighbors,
  and reported schedule entries by ascending node ID. Sets may be used only for
  membership, never to determine iteration order. This provides cross-runtime
  reproducibility. Because active-slot list order currently affects legacy ties,
  canonical ordering belongs to the new deterministic mode and must not silently
  alter published legacy results.
- **Latency reporting:** research tables report latency in elapsed slots. One
  slot is assumed long enough to complete one packet transmission from one
  sensor to another. Preserve the named legacy max-index metric for replication,
  but label it separately: the reference schedule has max index 25 and latency
  26 elapsed slots.
- **Validation:** the selected alpha model and full bidirectional tree
  consistency must be validated. Reports must state the communication range,
  alpha, derived interference radius, and collision model so a schedule cannot
  be ambiguously labeled valid.

## Coverage map and limitations

Every issue above is exercised by a regression test or directly tied to a
source-level precondition. The mutable default is documented rather than tested
through the ANEX reference path because all shipped topology readers/generators
provide explicit active-slot lists. Cross-runtime set-order determinism cannot
be established in a single-runtime unit test; fixed-runtime determinism and the
ordering dependency are recorded instead. Research-policy choices are not
encoded as passing requirements until their intended semantics are selected.
