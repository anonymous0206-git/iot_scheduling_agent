"""Compatibility characterization for the unmodified published ANEX code.

Expected failures are executable defect reports.  They describe the behavior
we want at the adapter boundary without changing ``source/`` to obtain it.
"""

import copy
import multiprocessing
import random
import unittest

from agentic_anex import AnexConfig, generate_connected_topology, run_anex
from agentic_anex.legacy import anex_module
from agentic_anex.validator import validate_schedule
from agentic_anex.schemas import InfeasibleNetworkError, SchemaError
from agentic_anex.topology_io import legacy_nodes_to_network_instance
from libs.node import Node


def baseline():
    nodes, _ = generate_connected_topology(
        node_count=30,
        x_range=40,
        y_range=40,
        communication_range=18,
        working_period=10,
        active_slots_per_node=2,
        seed=7,
    )
    return nodes, AnexConfig(
        working_period=10,
        channels=2,
        communication_range=18,
        interference_ratio=1.5,
        seed=7,
    )


def _run_disconnected():
    nodes = [Node(0, 0, 0, [0]), Node(1, 100, 100, [0])]
    run_anex(nodes, AnexConfig(working_period=2, communication_range=1))


def _run_no_progress():
    nodes = [Node(0, 0, 0, []), Node(1, 1, 0, [])]
    nodes[0].neighborIDs = [1]
    nodes[1].neighborIDs = [0]
    nodes[0].childrenIDs = [1]
    nodes[1].parentID = 0
    anex_module.ANEX(nodes, 2, 1, 2, 1)


def _finishes(target, timeout=0.25):
    process = multiprocessing.Process(target=target)
    process.start()
    process.join(timeout)
    finished = not process.is_alive()
    if process.is_alive():
        process.terminate()
        process.join()
    return finished


class LegacyCompatibilityTests(unittest.TestCase):
    def test_fixed_topology_and_seed_are_deterministic(self):
        nodes_a, config_a = baseline()
        nodes_b, config_b = baseline()
        self.assertEqual(
            [(n.ID, n.x, n.y, n.active_slot, n.neighborIDs) for n in nodes_a],
            [(n.ID, n.x, n.y, n.active_slot, n.neighborIDs) for n in nodes_b],
        )
        self.assertEqual(run_anex(nodes_a, config_a).schedule, run_anex(nodes_b, config_b).schedule)

    def test_disconnected_topology_is_rejected_instead_of_hanging(self):
        nodes = [Node(0, 0, 0, [0]), Node(1, 100, 100, [0])]
        with self.assertRaises(InfeasibleNetworkError):
            run_anex(nodes, AnexConfig(working_period=2, communication_range=1))

    def test_non_contiguous_ids_are_reported_by_validator(self):
        nodes = [Node(0, 0, 0, [0]), Node(7, 1, 0, [0])]
        nodes[0].neighborIDs = [1]
        nodes[0].childrenIDs = [1]
        nodes[1].neighborIDs = [0]
        nodes[1].parentID = 0
        nodes[1].timeslot = 0
        nodes[1].channel = 1
        with self.assertRaises(SchemaError) as caught:
            legacy_nodes_to_network_instance(
                nodes, working_period=2, communication_range=2,
            )
        self.assertEqual(caught.exception.code, "NON_CONTIGUOUS_NODE_IDS")

    def test_runner_rejects_non_contiguous_ids_before_legacy_indexing(self):
        nodes, config = baseline()
        nodes[1].ID = 99
        with self.assertRaises(ValueError):
            run_anex(nodes, config)

    def test_legacy_active_slot_sampling_excludes_final_slot(self):
        nodes, _ = generate_connected_topology(
            node_count=20,
            x_range=10,
            y_range=10,
            communication_range=20,
            working_period=5,
            active_slots_per_node=4,
            seed=11,
        )
        self.assertTrue(all(sorted(node.active_slot) == [0, 1, 2, 3] for node in nodes))
        self.assertTrue(all(4 not in node.active_slot for node in nodes))

    def test_invalid_active_slot_counts_are_rejected_by_adapter(self):
        for count in (0, 5, 6):
            with self.subTest(count=count), self.assertRaises(ValueError):
                generate_connected_topology(
                    node_count=2, x_range=2, y_range=2,
                    communication_range=5, working_period=5,
                    active_slots_per_node=count, seed=1,
                )

    def test_repeated_default_execution_is_stable_and_non_mutating(self):
        nodes, config = baseline()
        pristine = copy.deepcopy(nodes)
        first = run_anex(nodes, config)
        second = run_anex(nodes, config)
        self.assertEqual(first.schedule, second.schedule)
        self.assertEqual(
            [(n.parentID, n.childrenIDs, n.timeslot, n.channel) for n in nodes],
            [(n.parentID, n.childrenIDs, n.timeslot, n.channel) for n in pristine],
        )

    def test_parent_and_children_relationships_are_consistent_after_run(self):
        nodes, config = baseline()
        scheduled = copy.deepcopy(nodes)
        scheduled, _ = anex_module.tree_construction_based_minimum_link_delay(
            scheduled, config.working_period
        )
        anex_module.ANEX(
            scheduled, config.working_period, config.channels,
            config.communication_range, config.interference_ratio,
        )
        for child in range(1, len(scheduled)):
            self.assertIn(child, scheduled[scheduled[child].parentID].childrenIDs)
        for parent, node in enumerate(scheduled):
            for child in node.childrenIDs:
                self.assertEqual(scheduled[child].parentID, parent)

    @unittest.expectedFailure
    def test_validator_rejects_parent_children_mismatch(self):
        # Public schedule schemas encode routing links directly and deliberately
        # do not expose mutable legacy childrenIDs. This remains a legacy-only
        # consistency defect rather than a public validator constraint.
        nodes, _ = baseline()
        nodes[1].parentID = 0
        nodes[0].childrenIDs = []
        nodes[1].timeslot = 0
        nodes[1].channel = 1
        network = legacy_nodes_to_network_instance(
            nodes[:2], working_period=10, communication_range=18,
        )
        self.assertIn("TREE_RELATION_MISMATCH", network.metadata)

    @unittest.expectedFailure
    def test_channel_coloring_can_use_an_eighth_channel(self):
        # All eight senders conflict.  The legacy color map is hard-coded to
        # keys 1..7, so one sender remains unscheduled even when f == 8.
        nodes = [Node(i, i, 0, [0]) for i in range(17)]
        senders, parents = list(range(1, 9)), list(range(9, 17))
        for sender, parent in zip(senders, parents):
            nodes[sender].parentID = parent
            nodes[parent].childrenIDs.append(sender)
        for sender in senders:
            nodes[sender].neighborIDs = parents.copy()
        for parent in parents:
            nodes[parent].neighborIDs = senders.copy()
        scheduled, receivers = [], []
        anex_module.dynamic_schedule(nodes, senders, scheduled, receivers, 1, 8, 0, 1)
        self.assertEqual(len(scheduled), 8)
        self.assertEqual({nodes[u].channel for u in scheduled}, set(range(1, 9)))

    @unittest.expectedFailure
    def test_no_progress_state_terminates_with_an_error(self):
        self.assertTrue(_finishes(_run_no_progress))

    @unittest.expectedFailure
    def test_interference_ratio_neighborhood_is_used_for_coloring(self):
        nodes = [Node(i, i, 0, [0]) for i in range(5)]
        nodes[1].parentID, nodes[2].parentID = 3, 4
        nodes[3].neighborIDs, nodes[4].neighborIDs = [1], [2]
        nodes[3].interfereIDs, nodes[4].interfereIDs = [2], [1]
        self.assertTrue(anex_module.collision_in_eligible_senders(nodes, 2, [1]))

    def test_legacy_and_elapsed_latency_keep_distinct_conventions(self):
        nodes, config = baseline()
        result = run_anex(nodes, config)
        self.assertEqual(result.legacy_max_timeslot, 25)
        self.assertEqual(result.elapsed_slots, 26)
        self.assertEqual(result.elapsed_slots, result.legacy_max_timeslot + 1)

    def test_seed_is_a_generation_input_not_a_scheduler_input(self):
        nodes, config = baseline()
        changed_seed = AnexConfig(**{**config.__dict__, "seed": 123456})
        self.assertEqual(run_anex(nodes, config).schedule, run_anex(nodes, changed_seed).schedule)
        # Record that topology generation uses and resets module-global RNG.
        random.seed(99)
        expected = random.random()
        random.seed(99)
        generate_connected_topology(
            node_count=2, x_range=2, y_range=2, communication_range=5,
            working_period=3, active_slots_per_node=1, seed=4,
        )
        self.assertNotEqual(random.random(), expected)


if __name__ == "__main__":
    unittest.main()
