import csv
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from agentic_anex.experiments import (
    AgentBenchmarkSystem,
    ProviderAgentBenchmarkSystem,
    ExperimentRecord,
    RuleBasedBenchmarkSystem,
    SystemRunOutput,
    generate_summary_csv,
    load_experiment_records,
    paired_comparison,
    run_experiment_matrix,
)
from agentic_anex.llm_clients import LLMResponse, MockLLMClient
from agentic_anex.llm_clients import ProviderConfig
from agentic_anex.schemas import SchedulingRequest
from agentic_anex.topology_io import generate_network_instance


def benchmark_items():
    return [
        {
            "request_id": "r-execute", "paraphrase_group_id": "g-execute",
            "topology_id": None, "gold_action": "EXECUTE",
            "category": "execute_default", "complexity_level": "basic",
            "user_text": "execute",
        },
        {
            "request_id": "r-unsupported", "paraphrase_group_id": "g-unsupported",
            "topology_id": None, "gold_action": "UNSUPPORTED",
            "category": "unsupported_energy", "complexity_level": "basic",
            "user_text": "unsupported",
        },
    ]


@dataclass
class FakeSystem:
    system_name: str
    model_name: str
    latency: int
    token_cost: int

    def run(self, item, topology, seed):
        execute = item["gold_action"] == "EXECUTE"
        return SystemRunOutput(
            parsed_fields={"seed": seed, "intent": item["gold_action"]},
            action=item["gold_action"],
            tool_trace=({"tool_name": "fake", "status": "success"},),
            schedule_metrics={"latency_slots": self.latency} if execute else None,
            validation={"valid": True, "violations": []} if execute else None,
            retries=seed,
            prompt_tokens=self.token_cost,
            completion_tokens=5,
            model_calls=1,
            success=execute,
            failure_category=None if execute else "unsupported",
        )


class ExperimentRunnerTests(unittest.TestCase):
    def test_provider_agent_constructs_explicit_client_with_experiment_seed(self):
        network = generate_network_instance(
            node_count=30, x_range=40, y_range=40, communication_range=18,
            working_period=10, active_slots_per_node=2, seed=7,
        )
        response = {
            "status": "EXECUTE", "decision_summary": "Execute supported request.",
            "request": {
                "channels": 2, "interference_ratio": 1.0,
                "workload": "one_shot", "objective": "minimize_latency",
                "seed": 0, "collision_model": "legacy_neighbor",
                "latency_target_slots": None,
            },
            "clarification_questions": [],
            "approved_tool_calls": [
                "inspect_network", "run_anex", "validate_schedule", "measure_schedule",
            ],
        }
        client = MockLLMClient([LLMResponse(response, {
            "provider": "ollama", "model": "test", "prompt_tokens": 10,
            "completion_tokens": 5,
        })])
        system = ProviderAgentBenchmarkSystem(ProviderConfig(
            "ollama", "test", timeout_seconds=5, max_retries=0,
        ))
        with patch("agentic_anex.experiments.create_llm_client", return_value=client) as factory:
            output = system.run({"user_text": "one-shot minimum latency"}, network, 9)
        self.assertEqual(factory.call_args.args[0].seed, 9)
        self.assertTrue(output.success)
        self.assertEqual(output.prompt_tokens, 10)
        self.assertEqual(output.completion_tokens, 5)
        self.assertEqual(output.schedule_metrics["latency_slots"], 26)

    def test_matrix_uses_identical_request_topology_seed_keys(self):
        systems = [FakeSystem("a", "m1", 10, 100), FakeSystem("b", "m2", 8, 120)]
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.jsonl"
            status = run_experiment_matrix(
                benchmark_items(), systems, (0, 1), raw,
                topology_resolver=lambda _: None,
            )
            records = load_experiment_records(raw)
        self.assertEqual(status, {"expected": 8, "completed": 8, "written": 8, "skipped": 0})
        for system in systems:
            keys = {(record.request_id, record.topology_id, record.seed) for record in records
                    if record.system == system.system_name}
            self.assertEqual(keys, {
                ("r-execute", None, 0), ("r-execute", None, 1),
                ("r-unsupported", None, 0), ("r-unsupported", None, 1),
            })

    def test_resume_does_not_duplicate_or_overwrite_raw_records(self):
        system = FakeSystem("a", "m1", 10, 100)
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.jsonl"
            first = run_experiment_matrix(
                benchmark_items(), (system,), (0,), raw, topology_resolver=lambda _: None,
            )
            original = raw.read_bytes()
            second = run_experiment_matrix(
                benchmark_items(), (system,), (0,), raw, topology_resolver=lambda _: None,
            )
            self.assertEqual(raw.read_bytes(), original)
            records = load_experiment_records(raw)
        self.assertEqual(first["written"], 2)
        self.assertEqual(second["written"], 0)
        self.assertEqual(second["skipped"], 2)
        self.assertEqual(len(records), 2)

    def test_record_contains_required_raw_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.jsonl"
            run_experiment_matrix(
                benchmark_items(), (FakeSystem("a", "m", 10, 50),), (0,), raw,
                topology_resolver=lambda _: None,
            )
            record = load_experiment_records(raw)[0]
            serialized = record.to_dict()
        for field in (
            "parsed_fields", "action", "tool_trace", "schedule_metrics", "validation",
            "retries", "wall_time_seconds", "prompt_tokens", "completion_tokens",
            "total_tokens", "model_calls", "success", "failure_category",
            "clarification_fields", "error_code", "decision_summary", "llm_logs",
            "scope_policy",
        ):
            self.assertIn(field, serialized)
        self.assertGreaterEqual(record.wall_time_seconds, 0)

    def test_old_raw_record_without_new_evidence_fields_remains_loadable(self):
        record = ExperimentRecord(
            "agentic_anex.experiment_record.v1", "r", "g", None, "s", "m", 0,
            {}, "REJECT", "REJECT", (), None, None, 0, 0.1, 0, 0, 0, 0,
            False, "rejected", "invalid_parameter", "basic",
        ).to_dict()
        for field in ("clarification_fields", "error_code", "decision_summary", "llm_logs"):
            record.pop(field)
        restored = ExperimentRecord.from_dict(record)
        self.assertEqual(restored.clarification_fields, ())
        self.assertIsNone(restored.error_code)
        self.assertIsNone(restored.decision_summary)
        self.assertEqual(restored.llm_logs, ())

    def test_paired_bootstrap_is_reproducible(self):
        systems = [FakeSystem("base", "m", 10, 100), FakeSystem("candidate", "m", 8, 80)]
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.jsonl"
            run_experiment_matrix(
                benchmark_items(), systems, (0, 1), raw, topology_resolver=lambda _: None,
            )
            records = load_experiment_records(raw)
        first = paired_comparison(
            records, baseline=("base", "m"), candidate=("candidate", "m"),
            metric="latency_slots", bootstrap_samples=500, seed=7,
        )
        second = paired_comparison(
            records, baseline=("base", "m"), candidate=("candidate", "m"),
            metric="latency_slots", bootstrap_samples=500, seed=7,
        )
        self.assertEqual(first, second)
        self.assertEqual(first["paired_observations"], 2)
        self.assertEqual(first["mean_paired_difference_candidate_minus_baseline"], -2)
        self.assertEqual(first["confidence_interval"], [-2, -2])

    def test_summary_csv_is_derived_and_not_overwritten_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.jsonl"
            summary = Path(directory) / "summary.csv"
            run_experiment_matrix(
                benchmark_items(), (FakeSystem("a", "m", 10, 50),), (0,), raw,
                topology_resolver=lambda _: None,
            )
            records = load_experiment_records(raw)
            raw_before = raw.read_bytes()
            generate_summary_csv(records, summary)
            with summary.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            with self.assertRaises(FileExistsError):
                generate_summary_csv(records, summary)
            self.assertEqual(raw.read_bytes(), raw_before)
        self.assertEqual(rows[0]["system"], "a")
        self.assertEqual(rows[0]["records"], "2")

    def test_duplicate_raw_keys_are_rejected(self):
        record = ExperimentRecord(
            "agentic_anex.experiment_record.v1", "r", "g", None, "s", "m", 0,
            {}, "REJECT", "REJECT", (), None, None, 0, 0.1, 0, 0, 0, 0,
            False, "rejected", "invalid_parameter", "basic",
        )
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.jsonl"
            line = json.dumps(record.to_dict()) + "\n"
            raw.write_text(line + line, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_experiment_records(raw)

    def test_builtin_rule_based_system_preserves_legacy_baseline(self):
        network = generate_network_instance(
            node_count=30, x_range=40, y_range=40, communication_range=18,
            working_period=10, active_slots_per_node=2, seed=7,
        )
        item = {
            "request_id": "baseline", "paraphrase_group_id": "baseline",
            "topology_id": "legacy30_seed7", "gold_action": "EXECUTE",
            "category": "execute_default", "complexity_level": "basic",
            "user_text": "Run one-shot aggregation on topology legacy30_seed7 and minimize latency.",
        }
        output = RuleBasedBenchmarkSystem().run(item, network, 0)
        self.assertTrue(output.success)
        self.assertEqual(output.schedule_metrics["latency_slots"], 26)
        self.assertTrue(output.validation["valid"])

    def test_rule_baseline_runs_the_shared_scope_gate(self):
        """The baseline is the pipeline without its model, so it keeps the gate."""
        network = generate_network_instance(
            node_count=30, x_range=40, y_range=40, communication_range=18,
            working_period=10, active_slots_per_node=2, seed=7,
        )
        item = {
            "request_id": "gated", "paraphrase_group_id": "gated",
            "topology_id": "legacy30_seed7", "gold_action": "UNSUPPORTED",
            "category": "unsupported_digital_twin", "complexity_level": "basic",
            "user_text": "Build a digital twin of the network on topology legacy30_seed7.",
        }
        output = RuleBasedBenchmarkSystem().run(item, network, 0)
        self.assertEqual(output.action, "UNSUPPORTED")
        self.assertEqual(output.error_code, "UNSUPPORTED_DIGITAL_TWIN")
        self.assertIs(output.scope_policy["supported"], False)
        self.assertFalse(output.success)
        # The gate short-circuits, so the parser and the scheduler never ran.
        self.assertEqual(output.parsed_fields, {})
        self.assertIsNone(output.schedule_metrics)

    def test_a_gate_refusal_is_distinguishable_from_a_parser_refusal(self):
        """Both answer UNSUPPORTED; only the gate records why it could."""
        network = generate_network_instance(
            node_count=30, x_range=40, y_range=40, communication_range=18,
            working_period=10, active_slots_per_node=2, seed=7,
        )
        base = {"request_id": "x", "paraphrase_group_id": "x",
                "topology_id": "legacy30_seed7", "gold_action": "UNSUPPORTED",
                "category": "unsupported", "complexity_level": "basic"}
        # "network lifetime" is in the parser's own keyword list but is phrased
        # here so the gate's proximity rules do not fire on it.
        parser_only = RuleBasedBenchmarkSystem().run(
            {**base, "user_text": "Schedule on topology legacy30_seed7. "
                                  "Network lifetime is the metric of record."}, network, 0)
        self.assertEqual(parser_only.action, "UNSUPPORTED")
        self.assertEqual(parser_only.error_code, "UNSUPPORTED_OBJECTIVE")
        self.assertIs(parser_only.scope_policy["supported"], True)

    def test_a_request_the_gate_passes_still_reaches_the_parser(self):
        network = generate_network_instance(
            node_count=30, x_range=40, y_range=40, communication_range=18,
            working_period=10, active_slots_per_node=2, seed=7,
        )
        item = {
            "request_id": "clean", "paraphrase_group_id": "clean",
            "topology_id": "legacy30_seed7", "gold_action": "EXECUTE",
            "category": "execute_default", "complexity_level": "basic",
            "user_text": "Run one-shot aggregation on topology legacy30_seed7 "
                         "and minimize latency.",
        }
        output = RuleBasedBenchmarkSystem().run(item, network, 0)
        self.assertTrue(output.success)
        self.assertIs(output.scope_policy["supported"], True)

    def test_provider_neutral_agent_adapter_records_model_overhead(self):
        network = generate_network_instance(
            node_count=30, x_range=40, y_range=40, communication_range=18,
            working_period=10, active_slots_per_node=2, seed=7,
        )
        structured = SchedulingRequest(
            network, channels=2, interference_ratio=1.0, seed=0,
        )
        request_draft = structured.to_dict()
        request_draft.pop("network")
        response = {
            "status": "EXECUTE", "decision_summary": "Execute supported request.",
            "request": request_draft, "clarification_questions": [],
            "approved_tool_calls": [
                "inspect_network", "run_anex", "validate_schedule", "measure_schedule"
            ],
        }
        client = MockLLMClient([LLMResponse(response, {
            "model": "mock-paper", "usage": {"prompt_tokens": 80, "completion_tokens": 20}
        })])
        system = AgentBenchmarkSystem(client, "mock-paper")
        item = {
            "request_id": "agent", "paraphrase_group_id": "agent",
            "topology_id": "legacy30_seed7", "gold_action": "EXECUTE",
            "category": "execute_default", "complexity_level": "basic",
            "user_text": "Run one-shot aggregation and minimize latency.",
        }
        output = system.run(item, network, 7)
        self.assertTrue(output.success)
        self.assertEqual(output.model_calls, 1)
        self.assertEqual(output.prompt_tokens, 80)
        self.assertEqual(output.completion_tokens, 20)
        self.assertEqual(output.schedule_metrics["latency_slots"], 26)

    def test_agent_adapter_preserves_deterministic_topology_clarification(self):
        response = {
            "status": "CLARIFY", "decision_summary": "A topology is required.",
            "request": None,
            "clarification_questions": [{
                "field": "topology", "question": "Which topology should be used?",
                "expected_type": "NetworkInstance", "reason": "Scheduling needs a network.",
            }],
            "approved_tool_calls": [],
        }
        client = MockLLMClient([LLMResponse(response, {
            "provider": "mock", "model": "mock-paper", "prompt_tokens": 12,
            "completion_tokens": 6,
        })])
        output = AgentBenchmarkSystem(client, "mock-paper").run(
            {"user_text": "Schedule one-shot aggregation."}, None, 0,
        )
        self.assertEqual(output.action, "CLARIFY")
        self.assertEqual(output.clarification_fields, ("topology",))
        self.assertEqual(
            output.decision_summary,
            "Topology availability is resolved deterministically by the orchestrator.",
        )
        self.assertEqual(output.error_code, "MISSING_TOPOLOGY")
        self.assertEqual(output.llm_logs, ())
        self.assertEqual(output.model_calls, 0)
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
