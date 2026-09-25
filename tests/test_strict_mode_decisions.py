"""Parsing decisions produced under a strict structured-output mode.

A strict mode cannot omit a property, so a field the user never stated arrives
as null rather than missing. These tests pin how each null is read, because
getting one of them wrong is invisible in aggregate and shows up only as an
inflated error count for one action.
"""

import unittest

from agentic_anex.orchestration import (
    NULL_MEANS_CONTRACT_DEFAULT, AgentDecision,
)
from agentic_anex.schemas import SchemaError
from agentic_anex.topology_io import generate_network_instance


def network():
    return generate_network_instance(
        node_count=30, x_range=40, y_range=40, communication_range=18,
        working_period=10, active_slots_per_node=2, seed=7,
    )


def execute_payload(**overrides):
    request = {"channels": 2, "interference_ratio": 1.0, "workload": "one_shot",
               "objective": "minimize_latency", "seed": None,
               "collision_model": None, "latency_target_slots": None}
    request.update(overrides)
    return {"status": "EXECUTE", "decision_summary": "Run deterministic ANEX.",
            "request": request, "clarification_questions": None,
            "approved_tool_calls": ["inspect_network", "run_anex",
                                    "validate_schedule", "measure_schedule"]}


class StrictModeDecisionTests(unittest.TestCase):
    def setUp(self):
        self.instance = network()

    def test_null_defaulted_fields_fall_back_to_the_contract_default(self):
        decision = AgentDecision.from_llm_dict(execute_payload(), self.instance)
        self.assertEqual(decision.request.seed, 0)
        self.assertEqual(decision.request.collision_model, "legacy_neighbor")
        self.assertEqual(decision.request.workload, "one_shot")
        self.assertEqual(decision.request.objective, "minimize_latency")

    def test_a_stated_value_still_wins_over_the_default(self):
        decision = AgentDecision.from_llm_dict(
            execute_payload(seed=14, collision_model="interference_range"), self.instance)
        self.assertEqual(decision.request.seed, 14)
        self.assertEqual(decision.request.collision_model, "interference_range")

    def test_null_latency_target_is_kept_because_null_is_its_meaning(self):
        self.assertNotIn("latency_target_slots", NULL_MEANS_CONTRACT_DEFAULT)
        decision = AgentDecision.from_llm_dict(execute_payload(), self.instance)
        self.assertIsNone(decision.request.latency_target_slots)

    def test_null_clarification_questions_is_read_as_none_asked(self):
        decision = AgentDecision.from_llm_dict(execute_payload(), self.instance)
        self.assertEqual(decision.clarification_questions, ())

    def test_a_clarify_decision_survives_the_strict_shape(self):
        payload = {
            "status": "CLARIFY",
            "decision_summary": "The approved channel count is ambiguous.",
            "request": None,
            "clarification_questions": [{
                "field": "channels",
                "question": "Which channel count should be used: 3 or 7?",
                "expected_type": "integer",
                "reason": "A single approved channel count is required.",
            }],
            "approved_tool_calls": [],
        }
        decision = AgentDecision.from_llm_dict(payload, self.instance)
        self.assertEqual(decision.status, "CLARIFY")
        self.assertEqual(len(decision.clarification_questions), 1)
        self.assertEqual(decision.clarification_questions[0].field, "channels")

    def test_clarify_without_questions_is_still_refused(self):
        """The repair must not weaken the rule that CLARIFY has to ask something."""
        payload = {"status": "CLARIFY", "decision_summary": "Something is unclear.",
                   "request": None, "clarification_questions": None,
                   "approved_tool_calls": []}
        with self.assertRaises(SchemaError) as caught:
            AgentDecision.from_llm_dict(payload, self.instance)
        self.assertEqual(caught.exception.code, "MISSING_CLARIFICATION_QUESTIONS")

    def test_an_invalid_channel_count_is_still_refused_after_the_rewrite(self):
        """The strict rewrite drops the schema's bounds, so the Python check is
        now the only thing enforcing them. It must still fire."""
        with self.assertRaises(SchemaError) as caught:
            AgentDecision.from_llm_dict(execute_payload(channels=0), self.instance)
        self.assertEqual(caught.exception.code, "INVALID_CHANNEL_COUNT")

    def test_an_unknown_field_is_still_refused(self):
        payload = execute_payload()
        payload["clarification"] = "not a field of this schema"
        with self.assertRaises(SchemaError) as caught:
            AgentDecision.from_llm_dict(payload, self.instance)
        self.assertEqual(caught.exception.code, "MALFORMED_LLM_OUTPUT")

    def test_forbidden_topology_output_is_still_refused(self):
        with self.assertRaises(SchemaError) as caught:
            AgentDecision.from_llm_dict(
                execute_payload(network={"nodes": []}), self.instance)
        self.assertEqual(caught.exception.code, "TOPOLOGY_OR_SCHEDULE_OUTPUT_FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
