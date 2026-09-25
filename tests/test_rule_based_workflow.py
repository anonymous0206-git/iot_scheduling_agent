import json
import unittest

from agentic_anex.topology_io import generate_network_instance
from agentic_anex.workflows.rule_based import (
    DEFAULT_CHANNELS,
    RuleBasedRequest,
    WorkflowReport,
    WorkflowStatus,
    process_request,
)


def topology():
    return generate_network_instance(
        node_count=30, x_range=40, y_range=40, communication_range=18,
        working_period=10, active_slots_per_node=2, seed=7,
    )


class RuleBasedWorkflowTests(unittest.TestCase):
    def test_full_workflow_executes_without_llm(self):
        report = process_request({
            "topology": topology().to_dict(),
            "workload": "one_shot",
            "objective": "minimize_latency",
            "channels": 2,
            "working_period": 10,
            "communication_range": 18,
            "interference_ratio": 1.5,
            "collision_model": "legacy_neighbor",
            "seed": 7,
        })
        self.assertEqual(report.status, WorkflowStatus.EXECUTE.value)
        self.assertTrue(report.final_validation.valid)
        self.assertEqual(report.result.max_timeslot_index, 25)
        self.assertEqual(report.metrics.latency_slots, 26)
        self.assertIsNotNone(report.final_validation_certificate)
        self.assertEqual(
            [trace.tool_name for trace in report.tool_trace],
            ["inspect_network", "run_anex", "validate_schedule", "measure_schedule"],
        )
        self.assertEqual(WorkflowReport.from_json(report.to_json()), report)
        json.dumps(report.to_dict())

    def test_missing_topology_causes_structured_clarification(self):
        report = process_request({
            "workload": "one_shot",
            "objective": "minimize_latency",
        })
        self.assertEqual(report.status, WorkflowStatus.CLARIFY.value)
        self.assertEqual(len(report.clarification_questions), 1)
        question = report.clarification_questions[0]
        self.assertEqual(question.field, "topology")
        self.assertEqual(question.expected_type, "NetworkInstance")
        self.assertEqual(report.tool_trace, ())

    def test_missing_intent_is_not_invented(self):
        report = process_request({"topology": topology().to_dict()})
        self.assertEqual(report.status, WorkflowStatus.CLARIFY.value)
        self.assertEqual(
            {question.field for question in report.clarification_questions},
            {"workload", "objective"},
        )

    def test_energy_optimization_is_unsupported(self):
        report = process_request({
            "topology": topology().to_dict(),
            "workload": "one_shot",
            "objective": "minimize_energy",
        })
        self.assertEqual(report.status, WorkflowStatus.UNSUPPORTED.value)
        self.assertEqual(report.error["code"], "UNSUPPORTED_OBJECTIVE")
        self.assertIsNone(report.result)
        self.assertEqual(report.tool_trace, ())

    def test_unsupported_workload_is_reported(self):
        report = process_request({
            "topology": topology().to_dict(),
            "workload": "periodic",
            "objective": "minimize_latency",
        })
        self.assertEqual(report.status, WorkflowStatus.UNSUPPORTED.value)
        self.assertEqual(report.error["code"], "UNSUPPORTED_WORKLOAD")

    def test_impossible_latency_target_keeps_valid_schedule(self):
        report = process_request({
            "topology": topology().to_dict(),
            "workload": "one_shot",
            "objective": "minimize_latency",
            "latency_target_slots": 1,
            "channels": 2,
            "interference_ratio": 1.5,
            "collision_model": "legacy_neighbor",
            "seed": 7,
        })
        self.assertEqual(report.status, WorkflowStatus.EXECUTE.value)
        self.assertTrue(report.result.validation.valid)
        self.assertTrue(report.final_validation.valid)
        self.assertEqual(report.metrics.latency_slots, 26)
        self.assertFalse(report.target_satisfied)

    def test_documented_noncritical_defaults_are_recorded(self):
        report = process_request(RuleBasedRequest(
            topology=topology(), workload="one_shot", objective="minimize_latency",
        ))
        self.assertEqual(report.status, WorkflowStatus.EXECUTE.value)
        decisions = {decision.requirement: decision.decision for decision in report.decisions}
        self.assertEqual(decisions["channels"], str(DEFAULT_CHANNELS))
        self.assertEqual(decisions["collision_model"], "legacy_neighbor")
        self.assertEqual(decisions["working_period"], "10")
        self.assertEqual(decisions["communication_range"], "18.0")

    def test_malformed_topology_is_rejected_before_tools(self):
        payload = topology().to_dict()
        payload["nodes"][1]["active_slots"] = []
        report = process_request({
            "topology": payload,
            "workload": "one_shot",
            "objective": "minimize_latency",
        })
        self.assertEqual(report.status, WorkflowStatus.REJECT.value)
        self.assertEqual(report.error["category"], "schema_error")
        self.assertEqual(report.tool_trace, ())

    def test_configuration_mismatch_rejects_with_complete_partial_trace(self):
        report = process_request({
            "topology": topology().to_dict(),
            "workload": "one_shot",
            "objective": "minimize_latency",
            "working_period": 9,
        })
        self.assertEqual(report.status, WorkflowStatus.REJECT.value)
        self.assertEqual(report.error["code"], "CONFIG_NETWORK_MISMATCH")
        self.assertEqual(
            [trace.tool_name for trace in report.tool_trace],
            ["inspect_network", "run_anex"],
        )
        self.assertEqual(report.tool_trace[-1].status, "domain_failure")

    def test_interference_range_disagreement_is_rejected_and_explained(self):
        report = process_request({
            "topology": topology().to_dict(),
            "workload": "one_shot",
            "objective": "minimize_latency",
            "channels": 2,
            "interference_ratio": 1.5,
            "collision_model": "interference_range",
            "seed": 7,
        })
        self.assertEqual(report.status, WorkflowStatus.REJECT.value)
        self.assertFalse(report.final_validation.valid)
        self.assertEqual(report.error["code"], "SCHEDULE_VALIDATION_FAILED")
        self.assertEqual({item.code for item in report.final_validation.violations},
                         {"SECONDARY_COLLISION"})
        self.assertEqual(report.tool_trace[-1].tool_name, "explain_violations")


if __name__ == "__main__":
    unittest.main()
