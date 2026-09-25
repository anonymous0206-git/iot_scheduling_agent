import unittest
from unittest.mock import patch

from agentic_anex.llm_clients import LLMResponse, MockLLMClient
from agentic_anex.orchestration import (
    AGENT_DECISION_JSON_SCHEMA,
    MAX_RETRIES,
    RETRY_ACTION_ALLOWLIST,
    OrchestrationReport,
    Orchestrator,
    RequirementAgent,
)
from agentic_anex.schemas import SchedulingRequest, ValidationReport, Violation
from agentic_anex.topology_io import generate_network_instance


def topology():
    return generate_network_instance(
        node_count=30, x_range=40, y_range=40, communication_range=18,
        working_period=10, active_slots_per_node=2, seed=7,
    )


def request(network=None, *, latency_target=None):
    network = network or topology()
    return SchedulingRequest(
        network=network, channels=2, interference_ratio=1.0,
        workload="one_shot", objective="minimize_latency", seed=0,
        collision_model="legacy_neighbor", latency_target_slots=latency_target,
    )


def execute_output(network=None, *, latency_target=None, tools=None):
    request_draft = request(network, latency_target=latency_target).to_dict()
    request_draft.pop("network")
    return {
        "status": "EXECUTE",
        "decision_summary": "Run the supported one-shot latency experiment.",
        "request": request_draft,
        "clarification_questions": [],
        "approved_tool_calls": tools or [
            "inspect_network", "run_anex", "validate_schedule", "measure_schedule"
        ],
    }


class LLMOrchestrationTests(unittest.TestCase):
    def test_mock_full_execution_has_passing_certificate(self):
        network = topology()
        client = MockLLMClient([LLMResponse(
            execute_output(network), {"provider": "mock", "model": "mock-v1", "temperature": 0}
        )])
        report = Orchestrator(RequirementAgent(client)).run(
            "Schedule one-shot aggregation and minimize latency.", network
        )
        self.assertEqual(report.status, "EXECUTE")
        self.assertTrue(report.final_validation.valid)
        self.assertTrue(report.validation_certificate["valid"])
        self.assertEqual(report.validation_certificate["certificate_format"],
                         "agentic_anex.validation_certificate.v1")
        self.assertEqual(report.result.max_timeslot_index, 25)
        self.assertEqual(report.result.latency_slots, 26)
        self.assertEqual(report.request.network, network)
        self.assertNotIn("network", report.llm_logs[0].structured_output["request"])
        self.assertNotIn('"nodes"', report.llm_logs[0].prompt)
        self.assertIn("TOPOLOGY_CONTEXT", report.llm_logs[0].prompt)
        self.assertNotIn("legacy30_seed7", report.llm_logs[0].prompt)
        self.assertNotIn('"working_period"', report.llm_logs[0].prompt)
        self.assertIn("latency_target_slots must be null", report.llm_logs[0].prompt)
        self.assertIn("seed must be 0", report.llm_logs[0].prompt)
        self.assertIn("Apply a default only when that field is omitted", report.llm_logs[0].prompt)
        self.assertIn("CALLER_NETWORK_STATE=VALIDATED_AND_BOUND", report.llm_logs[0].prompt)
        self.assertIn("Topology presence is not an LLM decision", report.llm_logs[0].prompt)
        self.assertIn("Zero channels", report.llm_logs[0].prompt)
        self.assertIn("approve all four tools exactly", report.llm_logs[0].prompt)
        self.assertEqual([trace.tool_name for trace in report.tool_trace], [
            "inspect_network", "run_anex", "validate_schedule", "measure_schedule"
        ])
        self.assertEqual(OrchestrationReport.from_json(report.to_json()), report)

    def test_impossible_target_keeps_valid_success(self):
        network = topology()
        report = Orchestrator(RequirementAgent(MockLLMClient([
            execute_output(network, latency_target=1)
        ]))).run("Minimize one-shot latency with a target of one slot.", network)
        self.assertEqual(report.status, "EXECUTE")
        self.assertTrue(report.final_validation.valid)
        self.assertFalse(report.target_satisfied)

    def test_malformed_output_is_retried_then_accepted(self):
        network = topology()
        malformed = {"status": "EXECUTE", "schedule": [{"sender": 1}]}
        client = MockLLMClient([malformed, execute_output(network)])
        report = Orchestrator(RequirementAgent(client)).run("Run one-shot latency.", network)
        self.assertEqual(report.status, "EXECUTE")
        self.assertEqual(report.retry_count, 1)
        self.assertEqual(len(report.llm_logs), 2)
        self.assertIn(report.llm_logs[0].retry_action, RETRY_ACTION_ALLOWLIST)
        self.assertEqual(report.llm_logs[0].error["code"], "MALFORMED_LLM_OUTPUT")

    def test_malformed_output_is_safely_rejected_after_two_retries(self):
        malformed = {"status": "EXECUTE", "decision_summary": "bad",
                     "approved_tool_calls": [], "schedule": []}
        client = MockLLMClient([malformed, malformed, malformed])
        report = Orchestrator(RequirementAgent(client, max_retries=MAX_RETRIES)).run(
            "Run one-shot latency.", topology()
        )
        self.assertEqual(report.status, "REJECT")
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(report.retry_count, 2)
        self.assertIsNone(report.result)

    def test_schedule_injection_inside_request_is_rejected(self):
        network = topology()
        injected = execute_output(network)
        injected["request"]["schedule"] = [{"sender": 1, "timeslot": 0}]
        client = MockLLMClient([injected, injected, injected])
        report = Orchestrator(RequirementAgent(client)).run("Run one-shot latency.", network)
        self.assertEqual(report.status, "REJECT")
        self.assertEqual(report.error["code"], "TOPOLOGY_OR_SCHEDULE_OUTPUT_FORBIDDEN")
        self.assertIsNone(report.result)

    def test_unapproved_tool_call_is_rejected(self):
        network = topology()
        bad = execute_output(network, tools=["edit_schedule"])
        client = MockLLMClient([bad, bad, bad])
        report = Orchestrator(RequirementAgent(client)).run("Run one-shot latency.", network)
        self.assertEqual(report.status, "REJECT")
        self.assertEqual(report.error["code"], "UNAPPROVED_TOOL_CALL")

    def test_missing_validator_approval_cannot_succeed(self):
        network = topology()
        output = execute_output(network, tools=["inspect_network", "run_anex", "measure_schedule"])
        report = Orchestrator(RequirementAgent(MockLLMClient([output]))).run(
            "Run one-shot latency.", network
        )
        self.assertEqual(report.status, "REJECT")
        self.assertIn("validate_schedule", report.error["tools"])
        self.assertIsNone(report.result)

    def test_failed_independent_validation_cannot_report_success(self):
        network = topology()
        invalid = ValidationReport(
            False,
            (Violation("TEST_FAILURE", "Deliberate validator failure", (1,), {}, (), (0,)),),
            29, "legacy_neighbor", ("test",), "test-validator",
        )
        with patch("agentic_anex.orchestration.validate_schedule", return_value=invalid) as validator:
            report = Orchestrator(RequirementAgent(MockLLMClient([
                execute_output(network)
            ]))).run("Run one-shot latency.", network)
        validator.assert_called_once()
        self.assertEqual(report.status, "REJECT")
        self.assertFalse(report.validation_certificate["valid"])
        self.assertEqual(report.error["code"], "VALIDATION_CERTIFICATE_FAILED")

    def test_energy_optimization_is_deterministically_unsupported(self):
        client = MockLLMClient([execute_output(topology())])
        report = Orchestrator(RequirementAgent(client)).run(
            "Optimize energy consumption for this topology.", topology()
        )
        self.assertEqual(report.status, "UNSUPPORTED")
        self.assertEqual(report.error["code"], "UNSUPPORTED_OBJECTIVE")
        self.assertEqual(client.calls, [])

    def test_energy_scope_paraphrases_are_deterministically_unsupported(self):
        requests = (
            "Optimize sensor energy consumption for this topology.",
            "Minimize battery use and maximize network lifetime.",
            "Optimize residual energy for the sensor network.",
        )
        for text in requests:
            with self.subTest(text=text):
                client = MockLLMClient([])
                report = Orchestrator(RequirementAgent(client)).run(text, topology())
                self.assertEqual(report.status, "UNSUPPORTED")
                self.assertEqual(report.error["code"], "UNSUPPORTED_OBJECTIVE")
                self.assertEqual(client.calls, [])

    def test_digital_twin_scope_paraphrases_are_deterministically_unsupported(self):
        requests = (
            "Create a live Digital Twin and synchronize sensor state.",
            "Maintain a real-time virtual replica and forecast future node states.",
            "Build a virtual representation of the network.",
        )
        for text in requests:
            with self.subTest(text=text):
                client = MockLLMClient([])
                report = Orchestrator(RequirementAgent(client)).run(text, topology())
                self.assertEqual(report.status, "UNSUPPORTED")
                self.assertEqual(report.error["code"], "UNSUPPORTED_DIGITAL_TWIN")
                self.assertEqual(client.calls, [])

    def test_structured_clarification_is_returned(self):
        output = {
            "status": "CLARIFY",
            "decision_summary": "A topology is required.",
            "request": None,
            "approved_tool_calls": [],
            "clarification_questions": [{
                "field": "topology", "question": "Which topology should be used?",
                "expected_type": "NetworkInstance", "reason": "Scheduling requires a graph.",
            }],
        }
        client = MockLLMClient([output])
        report = Orchestrator(RequirementAgent(client)).run(
            "Schedule one-shot aggregation.", None
        )
        self.assertEqual(report.status, "CLARIFY")
        self.assertEqual(report.clarification_questions[0].field, "topology")
        self.assertEqual(client.calls, [])
        self.assertEqual(report.error["code"], "MISSING_TOPOLOGY")

    def test_llm_cannot_invent_a_missing_topology(self):
        invented = execute_output(topology())
        client = MockLLMClient([invented, invented, invented])
        report = Orchestrator(RequirementAgent(client)).run(
            "Schedule one-shot aggregation.", None
        )
        self.assertEqual(report.status, "CLARIFY")
        self.assertEqual(report.error["code"], "MISSING_TOPOLOGY")
        self.assertIsNone(report.result)
        self.assertEqual(client.calls, [])

    def test_logs_store_prompt_metadata_output_and_summary_but_no_chain_of_thought(self):
        network = topology()
        report = Orchestrator(RequirementAgent(MockLLMClient([LLMResponse(
            execute_output(network), {"provider": "mock", "model": "unit-test"}
        )]))).run("Run one-shot latency.", network)
        log = report.llm_logs[0]
        self.assertIn("USER_REQUEST", log.prompt)
        self.assertEqual(log.model_metadata["model"], "unit-test")
        self.assertEqual(log.structured_output["status"], "EXECUTE")
        self.assertTrue(log.decision_summary)
        serialized = log.to_dict()
        self.assertNotIn("chain_of_thought", serialized)
        self.assertNotIn("reasoning", serialized)

    def test_response_schema_forbids_schedule_and_enumerates_tools(self):
        request_schema = AGENT_DECISION_JSON_SCHEMA["properties"]["request"]
        self.assertIn("request", AGENT_DECISION_JSON_SCHEMA["required"])
        self.assertFalse(request_schema["additionalProperties"])
        self.assertNotIn("network", request_schema["properties"])
        self.assertNotIn("schedule", request_schema["properties"])
        self.assertEqual(request_schema["properties"]["seed"]["default"], 0)
        self.assertIsNone(request_schema["properties"]["latency_target_slots"]["default"])
        self.assertNotIn("allOf", AGENT_DECISION_JSON_SCHEMA)
        tool_enum = AGENT_DECISION_JSON_SCHEMA["properties"]["approved_tool_calls"]["items"]["enum"]
        self.assertNotIn("edit_schedule", tool_enum)

    def test_provider_client_failure_is_bounded_and_logged(self):
        client = MockLLMClient([])
        report = Orchestrator(RequirementAgent(client)).run("Run one-shot latency.", topology())
        self.assertEqual(report.status, "REJECT")
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(report.error["code"], "LLM_CLIENT_ERROR")
        self.assertTrue(all(log.retry_action in RETRY_ACTION_ALLOWLIST
                            for log in report.llm_logs[:-1]))


if __name__ == "__main__":
    unittest.main()
