import json
import unittest

from agentic_anex.models import (
    AnexConfig,
    AnexResult,
    ScheduleEntry as LegacyScheduleEntry,
    ValidationReport as LegacyValidationReport,
)
from agentic_anex.schemas import (
    InfeasibleNetworkError,
    NetworkInstance,
    NodeSpec,
    RequirementDecision,
    ScheduleEntry,
    SchedulingRequest,
    SchedulingResult,
    SchemaError,
    UnsupportedRequestError,
    ValidationReport,
    Violation,
    from_json,
    to_json,
)


def network_dict():
    return {
        "name": "three-node-line",
        "working_period": 4,
        "communication_range": 12.5,
        "sink_id": 0,
        "nodes": [
            {"id": 0, "x": 0.0, "y": 0.0, "active_slots": [0, 3], "neighbor_ids": [1]},
            {"id": 1, "x": 5.0, "y": 0.0, "active_slots": [1], "neighbor_ids": [0, 2]},
            {"id": 2, "x": 10.0, "y": 0.0, "active_slots": [2], "neighbor_ids": [1]},
        ],
        "metadata": {"source": "unit-test", "labels": ["paper-1"]},
    }


class SchemaTests(unittest.TestCase):
    def test_network_json_round_trip_without_information_loss(self):
        network = NetworkInstance.from_dict(network_dict())
        restored = NetworkInstance.from_json(network.to_json())
        self.assertEqual(restored, network)
        self.assertEqual(from_json(NetworkInstance, to_json(network)), network)
        self.assertEqual(
            json.loads(network.to_json()),
            json.loads(json.dumps(network.to_dict())),
        )
        self.assertNotIn("Node", network.to_json())

    def test_all_models_round_trip(self):
        network = NetworkInstance.from_dict(network_dict())
        request = SchedulingRequest(network, channels=9, interference_ratio=1.5, seed=7)
        entry = ScheduleEntry(2, 1, 3, 8, 3)
        violation = Violation("EXAMPLE", "example violation", (1, 2), {"slot": 3})
        invalid_report = ValidationReport(False, (violation,), 2, "alpha_expanded")
        valid_report = ValidationReport(True, (), 2, "alpha_expanded")
        result = SchedulingResult((entry,), valid_report, 4, 3, 3, {"alpha": 1.5})
        decision = RequirementDecision("channels", "arbitrary positive count", "user controlled")
        for value in (request, entry, violation, invalid_report, result, decision):
            with self.subTest(schema=type(value).__name__):
                self.assertEqual(type(value).from_dict(value.to_dict()), value)
                self.assertEqual(type(value).from_json(value.to_json()), value)

    def test_full_active_slot_domain_includes_last_slot(self):
        network = NetworkInstance.from_dict(network_dict())
        self.assertIn(network.working_period - 1, network.nodes[0].active_slots)

    def test_schema_errors_are_typed_and_human_readable(self):
        cases = []
        duplicate = network_dict(); duplicate["nodes"][2].update({"id": 1, "neighbor_ids": [0]})
        cases.append((duplicate, "DUPLICATE_NODE_ID"))
        non_contiguous = network_dict(); non_contiguous["nodes"][2]["id"] = 4
        cases.append((non_contiguous, "NON_CONTIGUOUS_NODE_IDS"))
        bad_sink = network_dict(); bad_sink["sink_id"] = 8
        cases.append((bad_sink, "INVALID_SINK_ID"))
        empty_slots = network_dict(); empty_slots["nodes"][1]["active_slots"] = []
        cases.append((empty_slots, "EMPTY_ACTIVE_SLOTS"))
        bad_slot = network_dict(); bad_slot["nodes"][0]["active_slots"] = [4]
        cases.append((bad_slot, "ACTIVE_SLOT_OUT_OF_RANGE"))
        bad_range = network_dict(); bad_range["communication_range"] = 0
        cases.append((bad_range, "INVALID_COMMUNICATION_RANGE"))
        for payload, code in cases:
            with self.subTest(code=code), self.assertRaises(SchemaError) as caught:
                NetworkInstance.from_dict(payload)
            self.assertEqual(caught.exception.code, code)
            self.assertIn(code, str(caught.exception))

    def test_request_field_validation(self):
        network = NetworkInstance.from_dict(network_dict())
        for kwargs, code in (
            ({"channels": 0, "interference_ratio": 1}, "INVALID_CHANNEL_COUNT"),
            ({"channels": 1, "interference_ratio": 0.9}, "INVALID_INTERFERENCE_RATIO"),
        ):
            with self.subTest(code=code), self.assertRaises(SchemaError) as caught:
                SchedulingRequest(network, **kwargs)
            self.assertEqual(caught.exception.code, code)

    def test_unsupported_request_is_not_a_schema_error(self):
        network = NetworkInstance.from_dict(network_dict())
        with self.assertRaises(UnsupportedRequestError) as workload:
            SchedulingRequest(network, 2, 1.0, workload="periodic")
        self.assertEqual(workload.exception.category, "unsupported_request")
        with self.assertRaises(UnsupportedRequestError) as objective:
            SchedulingRequest(network, 2, 1.0, objective="minimize_energy")
        self.assertEqual(objective.exception.code, "UNSUPPORTED_OBJECTIVE")

    def test_disconnected_network_is_distinctly_infeasible(self):
        payload = network_dict()
        payload["nodes"] = [
            {"id": 0, "x": 0, "y": 0, "active_slots": [0], "neighbor_ids": []},
            {"id": 1, "x": 5, "y": 0, "active_slots": [1], "neighbor_ids": []},
        ]
        with self.assertRaises(InfeasibleNetworkError) as caught:
            NetworkInstance.from_dict(payload)
        self.assertEqual(caught.exception.category, "infeasible_network")
        self.assertIn("cannot reach nodes [1]", str(caught.exception))

    def test_legacy_config_migration_adapter(self):
        network = NetworkInstance.from_dict(network_dict())
        legacy = AnexConfig(working_period=4, channels=3, communication_range=12.5,
                            interference_ratio=1.25, seed=9)
        request = SchedulingRequest.from_anex_config(legacy, network)
        self.assertEqual(request.to_anex_config(), legacy)

    def test_legacy_result_migration_adapter(self):
        legacy = AnexResult(
            config=AnexConfig(working_period=4, channels=2, communication_range=10),
            schedule=(LegacyScheduleEntry(1, 0, 3, 1, 3),),
            validation=LegacyValidationReport(True, (), 1),
            legacy_max_timeslot=3,
            elapsed_slots=4,
            max_layer=1,
            node_count=2,
            metadata={"legacy": True},
        )
        result = SchedulingResult.from_anex_result(legacy)
        self.assertEqual(result.latency_slots, 4)
        self.assertEqual(result.max_timeslot_index, 3)
        self.assertEqual(result.schedule[0], ScheduleEntry(1, 0, 3, 1, 3))
        self.assertEqual(result.metadata, {"legacy": True})

    def test_result_rejects_ambiguous_latency(self):
        report = ValidationReport(True, (), 1, "legacy_neighbor")
        with self.assertRaises(SchemaError) as caught:
            SchedulingResult((), report, latency_slots=25, max_timeslot_index=25, node_count=2)
        self.assertEqual(caught.exception.code, "INCONSISTENT_LATENCY")

    def test_invalid_json_has_typed_error(self):
        with self.assertRaises(SchemaError) as caught:
            NodeSpec.from_json("not-json")
        self.assertEqual(caught.exception.code, "INVALID_JSON")


if __name__ == "__main__":
    unittest.main()
