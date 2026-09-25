import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from agentic_anex.agent_cli import main as agent_main
from agentic_anex.llm_clients import (
    LLMClientError, OllamaClient, OpenAIClient, OpenAICompatibleClient,
    ProviderConfig, create_llm_client,
)
from agentic_anex.llm_clients.http_transport import HTTPStatusError
from agentic_anex.llm_clients.http_transport import json_http_post
from agentic_anex.llm_clients.strict_schema import to_openai_strict
from agentic_anex.orchestration import AGENT_DECISION_JSON_SCHEMA, Orchestrator, RequirementAgent
from agentic_anex.schemas import SchemaError
from agentic_anex.topology_io import generate_network_instance, save_json_topology


def network():
    return generate_network_instance(
        node_count=30, x_range=40, y_range=40, communication_range=18,
        working_period=10, active_slots_per_node=2, seed=7,
    )


def decision(instance):
    return {
        "status": "EXECUTE", "decision_summary": "Run deterministic ANEX.",
        "request": {
            "channels": 2, "interference_ratio": 1.0,
            "workload": "one_shot", "objective": "minimize_latency", "seed": 0,
            "collision_model": "legacy_neighbor", "latency_target_slots": None,
        },
        "clarification_questions": [],
        "approved_tool_calls": [
            "inspect_network", "run_anex", "validate_schedule", "measure_schedule",
        ],
    }


def ollama_response(output):
    return {"model": "local-test", "message": {"content": json.dumps(output)},
            "prompt_eval_count": 10, "eval_count": 20}


def compatible_response(output):
    return {"model": "api-test", "choices": [{"message": {"content": json.dumps(output)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}


class QueueTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ProviderRuntimeTests(unittest.TestCase):
    def test_provider_config_validation_and_round_trip(self):
        config = ProviderConfig("ollama", "qwen", temperature=0, timeout_seconds=5, seed=9)
        self.assertEqual(ProviderConfig.from_json(config.to_json()), config)
        invalid = (
            ({"provider": "other", "model": "x"}, "UNKNOWN_PROVIDER"),
            ({"provider": "ollama", "model": ""}, "INVALID_MODEL"),
            ({"provider": "ollama", "model": "x", "base_url": "localhost"}, "INVALID_URL"),
            ({"provider": "ollama", "model": "x", "temperature": -1}, "INVALID_TEMPERATURE"),
            ({"provider": "ollama", "model": "x", "timeout_seconds": 0}, "INVALID_TIMEOUT"),
            ({"provider": "ollama", "model": "x", "secret": "bad"},
             "UNKNOWN_PROVIDER_CONFIG_FIELD"),
        )
        for payload, code in invalid:
            with self.subTest(code=code), self.assertRaises(SchemaError) as caught:
                ProviderConfig.from_dict(payload)
            self.assertEqual(caught.exception.code, code)

    def test_factory_routes_explicitly_without_fallback(self):
        self.assertIsInstance(create_llm_client(ProviderConfig("ollama", "x")), OllamaClient)
        self.assertIsInstance(create_llm_client(ProviderConfig(
            "openai_compatible", "x", "http://localhost:8000/v1"
        )), OpenAICompatibleClient)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}):
            self.assertIsInstance(create_llm_client(ProviderConfig("openai", "x")), OpenAIClient)

    def test_ollama_valid_structured_output_and_metadata(self):
        output = {"status": "CLARIFY"}
        transport = QueueTransport([ollama_response(output)])
        response = OllamaClient(model="local", transport=transport).generate_structured(
            prompt="request", response_schema=AGENT_DECISION_JSON_SCHEMA
        )
        self.assertEqual(response.structured_output, output)
        self.assertEqual(response.model_metadata["provider"], "ollama")
        self.assertTrue(response.model_metadata["local"])
        self.assertIn("format", transport.calls[0]["payload"])

    def test_openai_compatible_valid_output_and_json_only_fallback(self):
        output = {"status": "CLARIFY"}
        transport = QueueTransport([HTTPStatusError(400), compatible_response(output)])
        response = OpenAICompatibleClient(
            base_url="http://localhost:8000/v1", model="local", transport=transport,
        ).generate_structured(prompt="request", response_schema=AGENT_DECISION_JSON_SCHEMA)
        self.assertEqual(response.structured_output, output)
        self.assertEqual(response.model_metadata["structured_output_mode"], "json_object")
        self.assertEqual(len(transport.calls), 2)

    def test_remote_openai_compatible_endpoint_reports_remote(self):
        transport = QueueTransport([compatible_response({"status": "CLARIFY"})])
        client = OpenAICompatibleClient(
            base_url="https://models.example.org/v1", model="remote", transport=transport,
        )
        response = client.generate_structured(
            prompt="request", response_schema=AGENT_DECISION_JSON_SCHEMA
        )
        self.assertFalse(client.is_local)
        self.assertFalse(response.model_metadata["local"])

    def test_cloud_output_and_secret_redaction(self):
        secret = "sk-never-persist-this-value"
        transport = QueueTransport([compatible_response({"status": "CLARIFY"})])
        with patch.dict(os.environ, {"TEST_OPENAI_KEY": secret}):
            client = OpenAIClient(model="cloud", api_key_env="TEST_OPENAI_KEY", transport=transport)
            response = client.generate_structured(
                prompt="request", response_schema=AGENT_DECISION_JSON_SCHEMA
            )
        self.assertEqual(response.model_metadata["provider"], "openai")
        self.assertFalse(response.model_metadata["local"])
        self.assertNotIn(secret, json.dumps(response.model_metadata))
        self.assertNotIn(secret, ProviderConfig("openai", "cloud",
                                               api_key_env="TEST_OPENAI_KEY").to_json())

    def test_missing_api_key_is_typed_and_does_not_call_transport(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(LLMClientError) as caught:
            OpenAIClient(model="cloud", api_key_env="ABSENT_KEY")
        self.assertEqual(caught.exception.code, "MISSING_API_KEY")

    def test_malformed_timeout_and_unavailable_errors_are_bounded(self):
        for failure in (
            LLMClientError("Provider request timed out.", code="PROVIDER_TIMEOUT"),
            LLMClientError("Provider is unavailable.", code="PROVIDER_UNAVAILABLE"),
        ):
            client = OllamaClient(model="local", transport=QueueTransport([failure]))
            with self.subTest(code=failure.code), self.assertRaises(LLMClientError) as caught:
                client.generate_structured(prompt="x", response_schema={})
            self.assertEqual(caught.exception.code, failure.code)
        malformed = OllamaClient(model="local", transport=QueueTransport([
            {"message": {"content": "not-json"}}
        ]))
        with self.assertRaises(LLMClientError) as caught:
            malformed.generate_structured(prompt="x", response_schema={})
        self.assertEqual(caught.exception.code, "MALFORMED_STRUCTURED_OUTPUT")

    def test_default_http_transport_maps_network_timeout_and_model_errors(self):
        failures = (
            (TimeoutError(), "PROVIDER_TIMEOUT"),
            (urllib.error.URLError("offline"), "PROVIDER_UNAVAILABLE"),
            (urllib.error.HTTPError("http://localhost", 404, "missing", {}, None),
             "MODEL_UNAVAILABLE"),
        )
        for failure, code in failures:
            with self.subTest(code=code), patch(
                "urllib.request.urlopen", side_effect=failure
            ), self.assertRaises(LLMClientError) as caught:
                json_http_post(url="http://localhost/api", payload={}, headers={},
                               timeout_seconds=1)
            self.assertEqual(caught.exception.code, code)

    def test_retry_success_and_exhaustion(self):
        instance = network(); good = ollama_response(decision(instance))
        malformed = {"message": {"content": "not-json"}}
        success_client = OllamaClient(
            model="local", transport=QueueTransport([malformed, good])
        )
        success = Orchestrator(RequirementAgent(success_client)).run("one-shot latency", instance)
        self.assertEqual(success.status, "EXECUTE")
        self.assertEqual(success.retry_count, 1)
        failure_client = OllamaClient(
            model="local", transport=QueueTransport([malformed, malformed, malformed])
        )
        failure = Orchestrator(RequirementAgent(failure_client)).run("one-shot latency", instance)
        self.assertEqual(failure.status, "REJECT")
        self.assertEqual(failure.retry_count, 2)
        self.assertEqual(failure.error["code"], "MALFORMED_STRUCTURED_OUTPUT")

    def test_local_and_api_clients_agree_on_the_schedule(self):
        instance = network(); output = decision(instance)
        local_transport = QueueTransport([ollama_response(output)])
        api_transport = QueueTransport([compatible_response(output)])
        reports = [
            Orchestrator(RequirementAgent(OllamaClient(
                model="local", transport=local_transport
            ))).run("one-shot latency", instance),
            Orchestrator(RequirementAgent(OpenAICompatibleClient(
                base_url="http://localhost:8000/v1", model="api", transport=api_transport
            ))).run("one-shot latency", instance),
        ]
        self.assertEqual(reports[0].result.schedule, reports[1].result.schedule)
        self.assertEqual(reports[0].result.max_timeslot_index, 25)
        self.assertEqual(reports[0].result.latency_slots, 26)

    def test_each_provider_gets_the_schema_form_it_can_enforce(self):
        """Ollama enforces the validation schema directly; a strict OpenAI-style
        endpoint rejects it outright, so it must be sent the rewritten subset.
        Sending the same document to both is what silently degrades the API arm
        to free-form JSON."""
        instance = network(); output = decision(instance)
        local_transport = QueueTransport([ollama_response(output)])
        api_transport = QueueTransport([compatible_response(output)])
        Orchestrator(RequirementAgent(OllamaClient(
            model="local", transport=local_transport))).run("one-shot latency", instance)
        Orchestrator(RequirementAgent(OpenAICompatibleClient(
            base_url="http://localhost:8000/v1", model="api", transport=api_transport,
        ))).run("one-shot latency", instance)

        self.assertEqual(local_transport.calls[0]["payload"]["format"],
                         AGENT_DECISION_JSON_SCHEMA)
        native = api_transport.calls[0]["payload"]["response_format"]["json_schema"]
        self.assertTrue(native["strict"])
        self.assertEqual(native["schema"], to_openai_strict(AGENT_DECISION_JSON_SCHEMA))
        self.assertNotEqual(native["schema"], AGENT_DECISION_JSON_SCHEMA)
        self.assertNotIn("$schema", native["schema"])

    def test_cli_report_and_interactive_visualization(self):
        instance = network()
        with tempfile.TemporaryDirectory() as directory:
            network_path = Path(directory) / "network.json"
            output = Path(directory) / "report.json"
            visualization = Path(directory) / "replay.html"
            save_json_topology(instance, network_path)
            code = agent_main([
                "--provider", "mock", "--network", str(network_path),
                "--request", "Schedule one-shot aggregation with minimum latency",
                "--output", str(output), "--visualization-output", str(visualization),
            ])
            self.assertEqual(code, 0)
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(document["report_format"],
                             "agentic_anex.multi_provider_orchestration.v1")
            self.assertEqual(document["runtime"]["provider"], "mock")
            self.assertEqual(document["runtime"]["model_calls"], 1)
            self.assertFalse(document["runtime"]["credentials_persisted"])
            self.assertEqual(document["orchestration"]["result"]["max_timeslot_index"], 25)
            self.assertTrue(visualization.exists())
            self.assertIn("interactive schedule replay",
                          visualization.read_text(encoding="utf-8"))

    def test_cli_has_no_implicit_mock_and_supports_rule_based_execution(self):
        instance = network()
        with tempfile.TemporaryDirectory() as directory:
            network_path = Path(directory) / "network.json"
            report_path = Path(directory) / "rule-report.json"
            replay_path = Path(directory) / "rule-replay.html"
            save_json_topology(instance, network_path)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                missing_code = agent_main([
                    "--network", str(network_path),
                    "--request", "Schedule one-shot aggregation with minimum latency",
                ])
            self.assertEqual(missing_code, 2)
            self.assertIn("MISSING_PROVIDER", stderr.getvalue())
            code = agent_main([
                "--rule-based", "--network", str(network_path),
                "--request", "Schedule one-shot aggregation with minimum latency",
                "--output", str(report_path), "--visualization-output", str(replay_path),
            ])
            self.assertEqual(code, 0)
            document = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(document["runtime"]["provider"], "rule_based")
            self.assertTrue(document["runtime"]["local"])
            self.assertEqual(document["runtime"]["model_calls"], 0)
            self.assertEqual(document["orchestration"]["result"]["max_timeslot_index"], 25)
            self.assertTrue(replay_path.exists())

    def test_cli_preserves_failure_report_when_visualization_cannot_be_created(self):
        instance = network()
        with tempfile.TemporaryDirectory() as directory:
            network_path = Path(directory) / "network.json"
            report_path = Path(directory) / "unsupported.json"
            replay_path = Path(directory) / "must-not-exist.html"
            save_json_topology(instance, network_path)
            code = agent_main([
                "--provider", "mock", "--network", str(network_path),
                "--request", "Optimize energy consumption",
                "--output", str(report_path), "--visualization-output", str(replay_path),
            ])
            self.assertEqual(code, 2)
            document = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(document["orchestration"]["status"], "UNSUPPORTED")
            self.assertEqual(document["visualization"]["status"], "not_created")
            self.assertEqual(document["visualization"]["reason"],
                             "VISUALIZATION_REQUIRES_VALID_SCHEDULE")
            self.assertFalse(replay_path.exists())


if __name__ == "__main__":
    unittest.main()
