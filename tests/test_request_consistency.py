import unittest

from agentic_anex.llm_clients import MockLLMClient
from agentic_anex.orchestration import Orchestrator, RequirementAgent
from agentic_anex.request_consistency import (
    RequestConsistencyError, check_request_consistency, explicit_request_fields,
)
from agentic_anex.schemas import SchedulingRequest
from agentic_anex.topology_io import generate_network_instance


def topology():
    return generate_network_instance(
        node_count=30, x_range=40, y_range=40, communication_range=18,
        working_period=10, active_slots_per_node=2, seed=7,
    )


def request(**changes):
    values = {
        "network": topology(), "channels": 2, "interference_ratio": 1.0,
        "workload": "one_shot", "objective": "minimize_latency", "seed": 0,
        "collision_model": "legacy_neighbor", "latency_target_slots": None,
    }
    values.update(changes)
    return SchedulingRequest(**values)


def execute_output(value):
    draft = value.to_dict()
    draft.pop("network")
    return {
        "status": "EXECUTE", "decision_summary": "Execute checked request.",
        "request": draft, "clarification_questions": [],
        "approved_tool_calls": [
            "inspect_network", "run_anex", "validate_schedule", "measure_schedule",
        ],
    }


class RequestConsistencyTests(unittest.TestCase):
    def test_all_public_request_parameters_are_checked_with_provenance(self):
        network = topology()
        value = request(
            network=network, channels=4, interference_ratio=1.5, seed=7,
            collision_model="interference_range", latency_target_slots=20,
        )
        text = (
            "Run one-shot minimum latency with 4 channels, seed 7, alpha 1.5, "
            "interference-range validation, latency target of 20 slots, "
            "working period 10, and communication range 18."
        )
        report = check_request_consistency(text, network, value)
        self.assertTrue(report.valid)
        self.assertEqual({check.field for check in report.checks}, {
            "workload", "objective", "channels", "interference_ratio",
            "collision_model", "seed", "latency_target_slots",
            "working_period", "communication_range",
        })
        self.assertTrue(all(check.status == "match" for check in report.checks))
        self.assertEqual({check.source for check in report.checks}, {"explicit_user_text"})

    def test_every_llm_controlled_field_mismatch_is_typed(self):
        cases = {
            "channels": ("Use 4 channels for one-shot minimum latency.", {"channels": 2}),
            "interference_ratio": ("Use alpha 1.5 for one-shot minimum latency.",
                                   {"interference_ratio": 1.0}),
            "seed": ("Use seed 7 for one-shot minimum latency.", {"seed": 0}),
            "latency_target_slots": ("Use a latency target of 20 slots for one-shot minimum latency.",
                                     {"latency_target_slots": None}),
            "collision_model": ("Use interference-range validation for one-shot minimum latency.",
                                {"collision_model": "legacy_neighbor"}),
        }
        for field, (text, changes) in cases.items():
            with self.subTest(field=field), self.assertRaises(RequestConsistencyError) as caught:
                check_request_consistency(text, topology(), request(**changes))
            error = caught.exception.to_dict()
            self.assertEqual(error["code"], "REQUEST_FIELD_MISMATCH")
            failed = [item for item in error["consistency"]["checks"]
                      if item["status"] == "mismatch"]
            self.assertIn(field, {item["field"] for item in failed})

    def test_omitted_fields_must_use_documented_defaults(self):
        with self.assertRaises(RequestConsistencyError) as caught:
            check_request_consistency(
                "Run one-shot aggregation and minimize latency.", topology(), request(seed=7),
            )
        seed = next(item for item in caught.exception.report.checks if item.field == "seed")
        self.assertEqual((seed.expected, seed.actual, seed.source), (0, 7, "documented_default"))

    def test_topology_owned_fields_cannot_be_overridden(self):
        for text, field, expected in (
            ("Use working period 9 for one-shot minimum latency.", "working_period", 9),
            ("Use communication range 20 for one-shot minimum latency.",
             "communication_range", 20.0),
        ):
            with self.subTest(field=field), self.assertRaises(RequestConsistencyError) as caught:
                check_request_consistency(text, topology(), request())
            failed = next(item for item in caught.exception.report.checks if item.field == field)
            self.assertEqual(failed.expected, expected)
            self.assertEqual(failed.source, "explicit_user_text")

    def test_topology_identifier_does_not_supply_request_seed(self):
        fields = explicit_request_fields("Run minimum latency on topology legacy30_seed7.")
        self.assertNotIn("seed", fields)

    def test_interference_range_benchmark_phrase_is_explicit(self):
        fields = explicit_request_fields(
            "Validate interference out to 1.5 times the communication range."
        )
        self.assertEqual(fields["interference_ratio"], 1.5)
        self.assertEqual(fields["collision_model"], "interference_range")

    def test_mismatch_is_retried_with_exact_field_correction(self):
        network = topology()
        bad = execute_output(request(network=network, interference_ratio=1.0))
        good = execute_output(request(network=network, interference_ratio=1.5))
        client = MockLLMClient([bad, good])
        report = Orchestrator(RequirementAgent(client, max_retries=1)).run(
            "Run one-shot minimum latency with alpha 1.5.", network,
        )
        self.assertEqual(report.status, "EXECUTE")
        self.assertEqual(report.retry_count, 1)
        self.assertEqual(report.llm_logs[0].error["code"], "REQUEST_FIELD_MISMATCH")
        self.assertIn("required_field_corrections", report.llm_logs[1].prompt)

    def test_false_topology_clarification_is_rejected_or_retried(self):
        output = {
            "status": "CLARIFY", "decision_summary": "Need topology.", "request": None,
            "approved_tool_calls": [], "clarification_questions": [{
                "field": "topology", "question": "Provide topology.",
                "expected_type": "NetworkInstance", "reason": "Required.",
            }],
        }
        report = Orchestrator(RequirementAgent(MockLLMClient([output]), max_retries=0)).run(
            "Run one-shot minimum latency.", topology(),
        )
        self.assertEqual(report.status, "REJECT")
        self.assertEqual(report.error["code"], "FALSE_MISSING_TOPOLOGY")
        self.assertEqual(len(report.llm_logs), 1)

    def test_explicit_invalid_parameters_are_rejected_before_llm(self):
        cases = (
            ("Use 0 channels for one-shot minimum latency.", "INVALID_CHANNEL_COUNT"),
            ("Use alpha 0.5 for one-shot minimum latency.", "INVALID_INTERFERENCE_RATIO"),
            ("Use seed -1 for one-shot minimum latency.", "INVALID_SEED"),
            ("Use working period 0 for one-shot minimum latency.", "INVALID_WORKING_PERIOD"),
            ("Use communication range 0 for one-shot minimum latency.",
             "INVALID_COMMUNICATION_RANGE"),
        )
        for text, code in cases:
            with self.subTest(code=code):
                client = MockLLMClient([])
                report = Orchestrator(RequirementAgent(client)).run(text, topology())
                self.assertEqual(report.status, "REJECT")
                self.assertEqual(report.error["code"], code)
                self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
