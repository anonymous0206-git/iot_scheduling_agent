"""The scope gate's authority is a parameter; nothing else may move with it.

An advisory-gate arm is only interpretable if it differs from the enforcing
and ungated arms in exactly one respect. These tests pin that down: on a
request the gate does not match, all three modes send the model a
byte-identical prompt, and on a request it does match, the modes differ only
in whether the run stops, carries a notice, or proceeds unaware.
"""

import unittest

from agentic_anex.experiments import SCOPE_MODE_SYSTEM_NAMES, AgentBenchmarkSystem
from agentic_anex.llm_clients import LLMResponse, MockLLMClient
from agentic_anex.orchestration import (
    ABLATED_POLICY_VERSION,
    ADVISORY_PROMPT_VERSION,
    PROMPT_VERSION,
    SCOPE_MODES,
    Orchestrator,
    RequirementAgent,
)
from agentic_anex.schemas import SchedulingRequest
from agentic_anex.topology_io import generate_network_instance

# Matches ENERGY_OBJECTIVE in the scope policy.
GATED_TEXT = "Schedule on topo50_seed0 but optimize battery lifetime across the network."
CLEAN_TEXT = "Schedule one-shot aggregation on topo50_seed0 and minimize latency."


def topology():
    return generate_network_instance(
        node_count=30, x_range=40, y_range=40, communication_range=18,
        working_period=10, active_slots_per_node=2, seed=7,
    )


def execute_output(network):
    draft = SchedulingRequest(
        network=network, channels=2, interference_ratio=1.0, workload="one_shot",
        objective="minimize_latency", seed=0, collision_model="legacy_neighbor",
        latency_target_slots=None,
    ).to_dict()
    draft.pop("network")
    return {
        "status": "EXECUTE", "decision_summary": "Run the supported request.",
        "request": draft, "clarification_questions": [],
        "approved_tool_calls": ["inspect_network", "run_anex", "validate_schedule",
                                "measure_schedule"],
    }


def unsupported_output():
    return {
        "status": "UNSUPPORTED", "decision_summary": "Battery lifetime is out of scope.",
        "request": None, "clarification_questions": [], "approved_tool_calls": [],
    }


def run(mode, text, network, output):
    client = MockLLMClient([LLMResponse(output, {"provider": "mock", "model": "mock-v1"})])
    report = Orchestrator(RequirementAgent(client), scope_mode=mode).run(text, network)
    return report, client


class ModeSelectionTests(unittest.TestCase):
    def test_the_three_modes_are_the_documented_ones(self):
        self.assertEqual(SCOPE_MODES, ("enforcing", "advisory", "off"))

    def test_an_unknown_mode_is_refused_at_construction(self):
        with self.assertRaises(ValueError):
            Orchestrator(RequirementAgent(MockLLMClient([])), scope_mode="permissive")

    def test_each_mode_records_itself_under_its_own_arm_name(self):
        names = {mode: AgentBenchmarkSystem(MockLLMClient([]), "m", scope_mode=mode).system_name
                 for mode in SCOPE_MODES}
        self.assertEqual(names, SCOPE_MODE_SYSTEM_NAMES)
        self.assertEqual(names["enforcing"], "llm_agent")
        self.assertEqual(len(set(names.values())), 3)


class EnforcingTests(unittest.TestCase):
    def test_a_matched_request_never_reaches_the_model(self):
        network = topology()
        report, client = run("enforcing", GATED_TEXT, network, execute_output(network))
        self.assertEqual(report.status, "UNSUPPORTED")
        self.assertEqual(client.calls, [], "the gate must short-circuit before the model")
        self.assertFalse(report.scope_policy.supported)


class AdvisoryTests(unittest.TestCase):
    def test_a_matched_request_reaches_the_model_and_the_model_decides(self):
        """The whole point: the gate's over-blocks stay recoverable."""
        network = topology()
        report, client = run("advisory", GATED_TEXT, network, execute_output(network))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(report.status, "EXECUTE")
        # the gate's finding is still recorded, it just did not decide
        self.assertFalse(report.scope_policy.supported)

    def test_the_model_can_also_agree_with_the_notice(self):
        network = topology()
        report, _ = run("advisory", GATED_TEXT, network, unsupported_output())
        self.assertEqual(report.status, "UNSUPPORTED")

    def test_the_notice_says_what_matched_and_that_it_is_not_binding(self):
        network = topology()
        _, client = run("advisory", GATED_TEXT, network, execute_output(network))
        prompt = client.calls[0]["prompt"]
        self.assertIn("ADVISORY SCOPE NOTICE", prompt)
        self.assertIn("energy_aware_scheduling", prompt)
        self.assertIn("not binding", prompt)
        self.assertIn(f"PROMPT_VERSION={ADVISORY_PROMPT_VERSION}", prompt)

    def test_an_unmatched_request_carries_no_notice_and_the_base_prompt_version(self):
        network = topology()
        _, client = run("advisory", CLEAN_TEXT, network, execute_output(network))
        prompt = client.calls[0]["prompt"]
        self.assertNotIn("ADVISORY SCOPE NOTICE", prompt)
        self.assertIn(f"PROMPT_VERSION={PROMPT_VERSION}", prompt)


class OffTests(unittest.TestCase):
    def test_the_gate_is_not_consulted_and_the_ledger_says_so(self):
        network = topology()
        report, client = run("off", GATED_TEXT, network, execute_output(network))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(report.status, "EXECUTE")
        self.assertTrue(report.scope_policy.supported)
        self.assertEqual(report.scope_policy.violations, ())
        self.assertEqual(report.scope_policy.policy_version, ABLATED_POLICY_VERSION)

    def test_no_notice_reaches_the_model(self):
        network = topology()
        _, client = run("off", GATED_TEXT, network, execute_output(network))
        self.assertNotIn("ADVISORY SCOPE NOTICE", client.calls[0]["prompt"])


class SingleDifferenceTests(unittest.TestCase):
    """What must stay equal between arms, so the comparison means something."""

    def prompt_for(self, mode, text):
        network = topology()
        _, client = run(mode, text, network, execute_output(network))
        return client.calls[0]["prompt"]

    def test_an_unmatched_request_gets_a_byte_identical_prompt_in_every_mode(self):
        prompts = {mode: self.prompt_for(mode, CLEAN_TEXT) for mode in SCOPE_MODES}
        self.assertEqual(len(set(prompts.values())), 1,
                         "the modes must differ only on requests the gate matched")

    def test_on_a_matched_request_advisory_differs_from_ungated_only_by_the_notice(self):
        advisory = self.prompt_for("advisory", GATED_TEXT)
        ungated = self.prompt_for("off", GATED_TEXT)
        self.assertNotEqual(advisory, ungated)
        head, _, notice = advisory.partition("\nADVISORY SCOPE NOTICE:")
        self.assertTrue(notice)
        # the only other difference is the prompt version, which names the change
        self.assertEqual(head.replace(ADVISORY_PROMPT_VERSION, PROMPT_VERSION), ungated)


if __name__ == "__main__":
    unittest.main()
