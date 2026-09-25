import random
import tempfile
import unittest
from pathlib import Path

from agentic_anex import AnexConfig, generate_connected_topology, run_anex
from agentic_anex.schemas import InfeasibleNetworkError, NetworkInstance, SchemaError
from agentic_anex.topology_io import (
    FULL_PERIOD_ACTIVE_SLOT_MODE,
    LEGACY_ACTIVE_SLOT_MODE,
    generate_network_instance,
    legacy_nodes_to_network_instance,
    load_json_topology,
    load_legacy_topology,
    network_instance_to_legacy_nodes,
    save_json_topology,
    topology_statistics,
)


class TopologyIOTests(unittest.TestCase):
    def test_legacy_text_to_instance_to_json_round_trip(self):
        text = """D 3 L 10
0 0 0 0 3
1 4 0 1
2 8 0 2
"""
        config = AnexConfig(working_period=4, communication_range=5)
        with tempfile.TemporaryDirectory() as directory:
            legacy_path = Path(directory) / "network.txt"
            json_path = Path(directory) / "network.json"
            legacy_path.write_text(text, encoding="utf-8")
            instance = load_legacy_topology(legacy_path, config)
            save_json_topology(instance, json_path)
            restored = load_json_topology(json_path)
        self.assertEqual(restored, instance)
        self.assertEqual(restored.nodes[0].active_slots, (0, 3))

    def test_statistics_are_computed_and_embedded(self):
        instance = generate_network_instance(
            node_count=3, x_range=2, y_range=0, communication_range=1,
            working_period=3, active_slots_per_node=1, seed=2,
        )
        stats = topology_statistics(instance)
        self.assertEqual(stats["node_count"], 3)
        self.assertEqual(stats["edge_count"], 2)
        self.assertAlmostEqual(stats["average_degree"], 4 / 3)
        self.assertEqual(stats["maximum_degree"], 2)
        self.assertAlmostEqual(stats["density"], 2 / 3)
        self.assertEqual(stats["max_bfs_layer"], 1)
        self.assertEqual(instance.metadata["topology_statistics"], stats)

    def test_generation_is_reproducible_and_does_not_touch_global_rng(self):
        kwargs = dict(
            node_count=30, x_range=40, y_range=40, communication_range=18,
            working_period=10, active_slots_per_node=2, seed=7,
        )
        random.seed(9123)
        expected_next = random.random()
        random.seed(9123)
        first = generate_network_instance(**kwargs)
        actual_next = random.random()
        second = generate_network_instance(**kwargs)
        self.assertEqual(first, second)
        self.assertEqual(actual_next, expected_next)

    def test_explicit_active_slot_modes(self):
        common = dict(
            node_count=2, x_range=1, y_range=0, communication_range=2,
            working_period=4, seed=5,
        )
        legacy = generate_network_instance(
            **common, active_slots_per_node=3,
            active_slot_mode=LEGACY_ACTIVE_SLOT_MODE,
        )
        full = generate_network_instance(
            **common, active_slots_per_node=4,
            active_slot_mode=FULL_PERIOD_ACTIVE_SLOT_MODE,
        )
        self.assertTrue(all(set(node.active_slots) == {0, 1, 2} for node in legacy.nodes))
        self.assertTrue(all(set(node.active_slots) == {0, 1, 2, 3} for node in full.nodes))
        self.assertEqual(legacy.metadata["active_slot_mode"], LEGACY_ACTIVE_SLOT_MODE)
        self.assertEqual(full.metadata["active_slot_mode"], FULL_PERIOD_ACTIVE_SLOT_MODE)

    def test_default_mode_matches_legacy_30_node_regression(self):
        kwargs = dict(
            node_count=30, x_range=40, y_range=40, communication_range=18,
            working_period=10, active_slots_per_node=2, seed=7,
        )
        instance = generate_network_instance(**kwargs)
        old_nodes, old_attempt = generate_connected_topology(**kwargs)
        converted = network_instance_to_legacy_nodes(instance)
        topology_fields = lambda nodes: [
            (n.ID, n.x, n.y, n.active_slot, n.neighborIDs) for n in nodes
        ]
        self.assertEqual(topology_fields(converted), topology_fields(old_nodes))
        self.assertEqual(instance.metadata["generation_attempt"], old_attempt)
        result = run_anex(converted, AnexConfig(
            working_period=10, channels=2, communication_range=18,
            interference_ratio=1.5, seed=7,
        ))
        self.assertEqual(result.legacy_max_timeslot, 25)
        self.assertEqual(result.elapsed_slots, 26)

    def test_disconnected_json_is_rejected_before_conversion(self):
        payload = {
            "nodes": [
                {"id": 0, "x": 0, "y": 0, "active_slots": [0], "neighbor_ids": []},
                {"id": 1, "x": 10, "y": 0, "active_slots": [0], "neighbor_ids": []},
            ],
            "sink_id": 0, "working_period": 2, "communication_range": 1,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disconnected.json"
            path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            with self.assertRaises(InfeasibleNetworkError):
                load_json_topology(path)

    def test_ids_are_never_silently_renumbered(self):
        text = """D 2 L 10
1 0 0 0
2 1 0 0
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-ids.txt"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(SchemaError) as caught:
                load_legacy_topology(path, AnexConfig(working_period=2, communication_range=2))
        self.assertEqual(caught.exception.code, "NON_CONTIGUOUS_NODE_IDS")

    def test_impossible_coordinate_grid_is_rejected_without_looping(self):
        with self.assertRaises(InfeasibleNetworkError) as caught:
            generate_network_instance(
                node_count=3, x_range=0, y_range=0, communication_range=1,
                working_period=2, active_slots_per_node=1, seed=1,
            )
        self.assertEqual(caught.exception.code, "INSUFFICIENT_UNIQUE_POSITIONS")

    def test_conversion_is_lossless_and_returns_fresh_legacy_nodes(self):
        instance = generate_network_instance(
            node_count=8, x_range=8, y_range=8, communication_range=8,
            working_period=5, active_slots_per_node=2, seed=4,
        )
        first = network_instance_to_legacy_nodes(instance)
        second = network_instance_to_legacy_nodes(instance)
        self.assertIsNot(first[0], second[0])
        restored = legacy_nodes_to_network_instance(
            first, working_period=5, communication_range=8,
            metadata=instance.metadata,
        )
        self.assertEqual(restored, instance)


if __name__ == "__main__":
    unittest.main()
