import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentic_anex.models import AnexConfig
from agentic_anex.schemas import InfeasibleNetworkError, SchemaError
from agentic_anex.topology_io import generate_network_instance, save_json_topology
from agentic_anex.tools import (
    TRACE_RECORDS,
    ValidationMode,
    explain_violations,
    inspect_network,
    main,
    measure_schedule,
    run_anex,
    validate_schedule,
)


def baseline():
    network = generate_network_instance(
        node_count=30, x_range=40, y_range=40, communication_range=18,
        working_period=10, active_slots_per_node=2, seed=7,
    )
    config = AnexConfig(
        working_period=10, channels=2, communication_range=18,
        interference_ratio=1.5, seed=7,
    )
    return network, config


class ScientificToolTests(unittest.TestCase):
    def setUp(self):
        TRACE_RECORDS.clear()

    def assert_json_serializable(self, value):
        restored = type(value).from_json(value.to_json())
        self.assertEqual(restored, value)
        json.dumps(value.to_dict())

    def test_inspect_network_returns_statistics_and_trace(self):
        network, _ = baseline()
        result = inspect_network(network)
        self.assertEqual(result.statistics["node_count"], 30)
        self.assertTrue(result.connected_to_sink)
        self.assertEqual(result.trace["tool_name"], "inspect_network")
        self.assertEqual(result.trace["status"], "success")
        self.assert_json_serializable(result)

    def test_run_anex_preserves_baseline_and_includes_certificate(self):
        network, config = baseline()
        result = run_anex(network, config)
        self.assertTrue(result.validation.valid, result.validation.violations)
        self.assertEqual(result.max_timeslot_index, 25)
        self.assertEqual(result.latency_slots, 26)
        self.assertEqual(result.validation_certificate["certificate_format"],
                         "agentic_anex.validation_certificate.v1")
        self.assertEqual(result.trace["tool_name"], "run_anex")
        self.assert_json_serializable(result)

    def test_validate_measure_and_explain_are_json_serializable(self):
        network, config = baseline()
        run = run_anex(network, config)
        report = validate_schedule(network, run.schedule, ValidationMode(
            "legacy_neighbor", channels=2, interference_ratio=1.5))
        metrics = measure_schedule(network, run.schedule)
        explanations = explain_violations(report)
        self.assertTrue(report.valid)
        self.assertEqual(metrics.latency_slots, 26)
        self.assertEqual(metrics.scheduled_transmissions, 29)
        self.assertTrue(explanations.valid)
        self.assertEqual(explanations.explanations, ())
        for value in (report, metrics, explanations):
            self.assert_json_serializable(value)

    def test_each_successful_call_generates_stable_input_hash(self):
        network, _ = baseline()
        first = inspect_network(network)
        second = inspect_network(network)
        self.assertEqual(first.trace["input_hash"], second.trace["input_hash"])
        self.assertEqual(len(TRACE_RECORDS), 2)
        self.assertTrue(all(record.start_time and record.end_time for record in TRACE_RECORDS))

    def test_invalid_network_cannot_reach_legacy_runner(self):
        _, config = baseline()
        with patch("agentic_anex.tools.network_instance_to_legacy_nodes") as converter:
            with self.assertRaises(SchemaError) as caught:
                run_anex({"nodes": []}, config)
        converter.assert_not_called()
        self.assertEqual(caught.exception.trace["status"], "domain_failure")
        self.assertEqual(TRACE_RECORDS[-1].error_type, "SchemaError")

    def test_config_mismatch_is_domain_failure(self):
        network, _ = baseline()
        with self.assertRaises(SchemaError):
            run_anex(network, AnexConfig(
                working_period=9, channels=2, communication_range=18,
                interference_ratio=1.5,
            ))
        self.assertEqual(TRACE_RECORDS[-1].status, "domain_failure")

    def test_no_progress_guard_returns_domain_failure(self):
        network, config = baseline()
        with patch("agentic_anex.tools.anex_module.dynamic_schedule", return_value=None):
            with self.assertRaises(InfeasibleNetworkError) as caught:
                run_anex(network, config)
        self.assertEqual(caught.exception.code, "ANEX_NO_PROGRESS")
        self.assertEqual(caught.exception.trace["status"], "domain_failure")

    def test_internal_exception_is_distinguished_in_trace(self):
        network, _ = baseline()
        with patch("agentic_anex.tools.topology_statistics", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                inspect_network(network)
        self.assertEqual(TRACE_RECORDS[-1].status, "internal_exception")
        self.assertEqual(TRACE_RECORDS[-1].error_type, "RuntimeError")

    def test_cli_inspect_and_run(self):
        network, config = baseline()
        with tempfile.TemporaryDirectory() as directory:
            network_path = Path(directory) / "network.json"
            config_path = Path(directory) / "config.json"
            save_json_topology(network, network_path)
            config_path.write_text(json.dumps(as_config_dict(config)), encoding="utf-8")
            for arguments, expected_tool in (
                (["inspect", "--network", str(network_path)], "inspect_network"),
                (["run", "--network", str(network_path), "--config", str(config_path)], "run_anex"),
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    main(arguments)
                payload = json.loads(output.getvalue())
                self.assertEqual(payload["trace"]["tool_name"], expected_tool)

    def test_cli_validate_measure_and_explain(self):
        network, config = baseline()
        result = run_anex(network, config)
        with tempfile.TemporaryDirectory() as directory:
            network_path = Path(directory) / "network.json"
            schedule_path = Path(directory) / "schedule.json"
            report_path = Path(directory) / "report.json"
            save_json_topology(network, network_path)
            schedule_path.write_text(json.dumps([entry.to_dict() for entry in result.schedule]),
                                     encoding="utf-8")
            report_path.write_text(result.validation.to_json(), encoding="utf-8")
            commands = (
                (["validate", "--network", str(network_path), "--schedule", str(schedule_path),
                  "--channels", "2"], "validate_schedule"),
                (["measure", "--network", str(network_path), "--schedule", str(schedule_path)],
                 "measure_schedule"),
                (["explain", "--report", str(report_path)], "explain_violations"),
            )
            for arguments, expected_tool in commands:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    main(arguments)
                self.assertEqual(json.loads(output.getvalue())["trace"]["tool_name"], expected_tool)


def as_config_dict(config):
    return {
        "working_period": config.working_period,
        "channels": config.channels,
        "communication_range": config.communication_range,
        "interference_ratio": config.interference_ratio,
        "seed": config.seed,
    }


if __name__ == "__main__":
    unittest.main()
