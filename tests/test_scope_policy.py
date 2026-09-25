import json
import unittest
from pathlib import Path
from unittest.mock import patch

from agentic_anex.llm_clients import MockLLMClient
from agentic_anex.orchestration import Orchestrator, RequirementAgent
from agentic_anex.scope_policy import ScopePolicyReport, evaluate_scope_policy
from agentic_anex.topology_io import generate_network_instance


def topology():
    return generate_network_instance(
        node_count=30, x_range=40, y_range=40, communication_range=18,
        working_period=10, active_slots_per_node=2, seed=7,
    )


class ScopePolicyTests(unittest.TestCase):
    def test_supported_paper1_requests_pass_closed_taxonomy(self):
        requests = (
            "Run one-shot aggregation and minimize latency.",
            "Use four channels and alpha 1.5 for a single collection round.",
            "Can the one-shot schedule finish within twenty slots?",
        )
        for text in requests:
            with self.subTest(text=text):
                report = evaluate_scope_policy(text)
                self.assertTrue(report.supported)
                self.assertFalse(report.violations)
                self.assertEqual(ScopePolicyReport.from_json(report.to_json()), report)

    def test_each_closed_taxonomy_category_has_new_synthetic_paraphrases(self):
        cases = {
            "digital_twin_or_emulation": "Construct a cyber-physical twin for this deployment.",
            "dynamic_state_synchronization": "Mirror live network state into an external controller.",
            "energy_aware_scheduling": "Reduce power consumption during packet collection.",
            "residual_battery_evolution": "Track the evolving remaining battery charge.",
            "periodic_or_continuous_aggregation": "Produce a recurring convergecast schedule.",
            "topology_adaptation": "Reconfigure the routing graph as links change.",
            "unsupported_optimization_objective": "Maximize throughput for the sensor network.",
        }
        for expected, text in cases.items():
            with self.subTest(category=expected):
                report = evaluate_scope_policy(text)
                self.assertFalse(report.supported)
                self.assertIn(expected, {item.category for item in report.violations})
                self.assertTrue(all(item.witness for item in report.violations))

    def test_unsupported_raw_capability_prevents_llm_and_tools(self):
        client = MockLLMClient([])
        with patch("agentic_anex.orchestration.run_anex") as run_tool:
            report = Orchestrator(RequirementAgent(client)).run(
                "Continuously mirror sensor state into a cyber-physical twin.", topology(),
            )
        self.assertEqual(report.status, "UNSUPPORTED")
        self.assertFalse(report.scope_policy.supported)
        self.assertEqual(client.calls, [])
        run_tool.assert_not_called()
        self.assertIsNone(report.validation_certificate)

    def test_valid_schedule_cannot_override_prior_scope_failure(self):
        client = MockLLMClient([])
        report = Orchestrator(RequirementAgent(client)).run(
            "Create a recurring collection schedule and minimize its latency.", topology(),
        )
        self.assertEqual(report.status, "UNSUPPORTED")
        self.assertIsNone(report.result)
        self.assertIsNone(report.final_validation)
        self.assertFalse(report.scope_policy.supported)

    def test_frozen_v1_dt02_is_only_a_named_regression_not_new_evaluation(self):
        benchmark = Path("benchmarks/requests_test.jsonl")
        item = next(json.loads(line) for line in benchmark.read_text(encoding="utf-8").splitlines()
                    if json.loads(line)["request_id"] == "test-dt-02")
        report = evaluate_scope_policy(item["user_text"])
        self.assertFalse(report.supported)
        self.assertIn("digital_twin_or_emulation",
                      {violation.category for violation in report.violations})


if __name__ == "__main__":
    unittest.main()
