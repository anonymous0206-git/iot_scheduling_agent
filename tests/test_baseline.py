import copy
import unittest

from agentic_anex import AnexConfig, generate_connected_topology, run_anex
from agentic_anex.validator import validate_schedule
from agentic_anex.topology_io import legacy_nodes_to_network_instance, legacy_nodes_to_schedule_entries


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
    config = AnexConfig(
        working_period=10,
        channels=2,
        communication_range=18,
        interference_ratio=1.5,
        seed=7,
    )
    return nodes, config


class BaselineTests(unittest.TestCase):
    def test_regression_baseline_is_valid_and_reproducible(self):
        nodes, config = baseline()
        first = run_anex(nodes, config)
        second = run_anex(nodes, config)
        self.assertTrue(first.validation.valid, first.validation.violations)
        self.assertEqual(first.schedule, second.schedule)
        self.assertEqual(first.legacy_max_timeslot, 25)
        self.assertEqual(first.elapsed_slots, 26)
        self.assertEqual(len(first.schedule), 29)

    def test_validator_detects_primary_collision(self):
        nodes, config = baseline()
        scheduled = copy.deepcopy(nodes)
        # Re-run to obtain the mutable scheduled legacy nodes.
        from agentic_anex.legacy import anex_module
        scheduled, _ = anex_module.tree_construction_based_minimum_link_delay(scheduled, config.working_period)
        anex_module.ANEX(scheduled, config.working_period, config.channels, config.communication_range, config.interference_ratio)
        parent_groups = {}
        for u in range(1, len(scheduled)):
            parent_groups.setdefault(scheduled[u].parentID, []).append(u)
        siblings = next(group for group in parent_groups.values() if len(group) >= 2)
        u, v = siblings[:2]
        scheduled[v].timeslot = scheduled[u].timeslot
        network = legacy_nodes_to_network_instance(
            scheduled, working_period=10, communication_range=18,
        )
        report = validate_schedule(
            network, legacy_nodes_to_schedule_entries(scheduled, working_period=10),
            channels=2,
        )
        self.assertFalse(report.valid)
        self.assertIn("PRIMARY_COLLISION", {item.code for item in report.violations})


if __name__ == "__main__":
    unittest.main()
