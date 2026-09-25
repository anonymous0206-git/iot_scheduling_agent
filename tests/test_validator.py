import contextlib
import copy
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from agentic_anex.schemas import NetworkInstance, NodeSpec, ScheduleEntry
from agentic_anex.topology_io import network_instance_to_legacy_nodes
from agentic_anex.validator import (
    CHECKED_CONSTRAINTS,
    VALIDATOR_VERSION,
    export_validation_certificate,
    validate_schedule,
    validation_certificate,
)


def fixture():
    # Two simultaneous links are outside communication-neighbor interference,
    # but inside a 1.5x geometric interference radius.
    coordinates = ((0, 0), (0, 5), (14, 5), (14, 0), (7, 0))
    communication_range = 10
    neighbors = {index: [] for index in range(len(coordinates))}
    for left, (lx, ly) in enumerate(coordinates):
        for right in range(left + 1, len(coordinates)):
            rx, ry = coordinates[right]
            if ((lx - rx) ** 2 + (ly - ry) ** 2) ** 0.5 <= communication_range:
                neighbors[left].append(right)
                neighbors[right].append(left)
    network = NetworkInstance(
        nodes=tuple(NodeSpec(i, x, y, (0, 1, 2), tuple(neighbors[i]))
                    for i, (x, y) in enumerate(coordinates)),
        sink_id=0,
        working_period=3,
        communication_range=communication_range,
        name="validator-fixture",
    )
    schedule = (
        ScheduleEntry(1, 0, 0, 1, 0),
        ScheduleEntry(2, 3, 0, 1, 0),
        ScheduleEntry(3, 4, 1, 1, 1),
        ScheduleEntry(4, 0, 2, 1, 2),
    )
    return network, schedule


def codes(report):
    return {item.code for item in report.violations}


class IndependentValidatorTests(unittest.TestCase):
    def assert_detected(self, expected_code, network, schedule, **kwargs):
        network_before = network.to_json()
        schedule_before = tuple(schedule)
        report = validate_schedule(network, schedule, channels=2, **kwargs)
        self.assertFalse(report.valid)
        self.assertIn(expected_code, codes(report))
        witness = next(item for item in report.violations if item.code == expected_code)
        self.assertTrue(witness.nodes or witness.links or witness.timeslots)
        self.assertEqual(network.to_json(), network_before)
        self.assertEqual(tuple(schedule), schedule_before)
        return report

    def test_known_valid_schedule_passes_legacy_neighbor(self):
        network, schedule = fixture()
        report = validate_schedule(network, schedule, channels=2)
        self.assertTrue(report.valid, report.violations)
        self.assertEqual(report.validator_version, VALIDATOR_VERSION)
        self.assertEqual(report.checked_constraints, CHECKED_CONSTRAINTS)
        self.assertEqual(report.collision_model, "legacy_neighbor")

    def test_missing_transmission(self):
        network, schedule = fixture()
        self.assert_detected("MISSING_TRANSMISSION", network, schedule[:-1])

    def test_duplicate_transmission(self):
        network, schedule = fixture()
        self.assert_detected("DUPLICATE_TRANSMISSION", network, schedule + (schedule[0],))

    def test_unknown_sender(self):
        network, schedule = fixture()
        corrupted = schedule + (ScheduleEntry(99, 0, 0, 1, 0),)
        self.assert_detected("UNKNOWN_SENDER", network, corrupted)

    def test_sink_transmission(self):
        network, schedule = fixture()
        corrupted = schedule + (ScheduleEntry(0, 1, 0, 1, 0),)
        self.assert_detected("SINK_TRANSMISSION", network, corrupted)

    def test_unknown_receiver(self):
        network, schedule = fixture()
        corrupted = (replace(schedule[0], receiver=99),) + schedule[1:]
        self.assert_detected("UNKNOWN_RECEIVER", network, corrupted)

    def test_non_neighbor_link(self):
        network, schedule = fixture()
        corrupted = (replace(schedule[0], receiver=3),) + schedule[1:]
        self.assert_detected("NON_NEIGHBOR_LINK", network, corrupted)

    def test_invalid_channel(self):
        network, schedule = fixture()
        corrupted = (replace(schedule[0], channel=3),) + schedule[1:]
        self.assert_detected("INVALID_CHANNEL", network, corrupted)

    def test_active_slot_field_mismatch(self):
        network, schedule = fixture()
        corrupted = (replace(schedule[0], receiver_active_slot=2),) + schedule[1:]
        self.assert_detected("ACTIVE_SLOT_FIELD_MISMATCH", network, corrupted)

    def test_inactive_receiver(self):
        network, schedule = fixture()
        nodes = list(network.nodes)
        nodes[0] = replace(nodes[0], active_slots=(0, 2))
        restricted = replace(network, nodes=tuple(nodes))
        corrupted = (replace(schedule[0], timeslot=1, channel=2, receiver_active_slot=1),) + schedule[1:]
        self.assert_detected("INACTIVE_RECEIVER", restricted, corrupted)

    def test_parent_cycle(self):
        network, schedule = fixture()
        corrupted = (
            schedule[0],
            replace(schedule[1], receiver=4),
            schedule[2],
            replace(schedule[3], receiver=2),
        )
        self.assert_detected("PARENT_CYCLE", network, corrupted)

    def test_precedence_violation(self):
        network, schedule = fixture()
        corrupted = schedule[:1] + (replace(schedule[1], timeslot=1, receiver_active_slot=1),) + schedule[2:]
        self.assert_detected("PRECEDENCE_VIOLATION", network, corrupted)

    def test_primary_collision(self):
        network, schedule = fixture()
        # Nodes 1 and 4 both target sink zero.
        corrupted = schedule[:3] + (replace(schedule[3], timeslot=0, receiver_active_slot=0),)
        self.assert_detected("PRIMARY_COLLISION", network, corrupted)

    def test_secondary_collision(self):
        network, schedule = fixture()
        report = self.assert_detected(
            "SECONDARY_COLLISION", network, schedule,
            collision_model="interference_range", interference_ratio=1.5,
        )
        item = next(v for v in report.violations if v.code == "SECONDARY_COLLISION")
        self.assertEqual(len(item.links), 2)
        self.assertEqual(item.timeslots, (0,))

    def test_half_duplex_violation(self):
        network, schedule = fixture()
        corrupted = schedule[:2] + (replace(schedule[2], timeslot=0, receiver_active_slot=0),) + schedule[3:]
        self.assert_detected("HALF_DUPLEX_VIOLATION", network, corrupted)

    def test_collision_models_disagree_explicitly(self):
        network, schedule = fixture()
        legacy = validate_schedule(network, schedule, channels=2, collision_model="legacy_neighbor")
        ranged = validate_schedule(network, schedule, channels=2, interference_ratio=1.5,
                                   collision_model="interference_range")
        self.assertTrue(legacy.valid)
        self.assertFalse(ranged.valid)
        self.assertEqual(codes(ranged), {"SECONDARY_COLLISION"})
        self.assertEqual(ranged.violations[0].details["collision_model"], "interference_range")

    def test_structured_validator_can_disagree_with_print_only_edas(self):
        import EDAS_validation

        network, schedule = fixture()
        nodes = list(network.nodes)
        nodes[0] = replace(nodes[0], active_slots=(0, 2))
        restricted = replace(network, nodes=tuple(nodes))
        corrupted = (replace(schedule[0], timeslot=1, channel=2, receiver_active_slot=1),) + schedule[1:]
        report = validate_schedule(restricted, corrupted, channels=2)
        self.assertIn("INACTIVE_RECEIVER", codes(report))

        legacy_nodes = network_instance_to_legacy_nodes(restricted)
        for entry in corrupted:
            node = legacy_nodes[entry.sender]
            node.parentID, node.timeslot, node.channel = entry.receiver, entry.timeslot, entry.channel
            legacy_nodes[entry.receiver].childrenIDs.append(entry.sender)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            returned = EDAS_validation.schedule_validation(legacy_nodes)
        self.assertIsNone(returned)
        self.assertEqual(output.getvalue(), "")
        self.assertFalse(report.valid)

    def test_machine_readable_certificate_export(self):
        network, schedule = fixture()
        report = validate_schedule(network, schedule, channels=2)
        payload = validation_certificate(report)
        self.assertEqual(payload["certificate_format"], "agentic_anex.validation_certificate.v1")
        self.assertEqual(payload["validator_version"], VALIDATOR_VERSION)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "validation-certificate.json"
            export_validation_certificate(report, path)
            restored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(restored, json.loads(json.dumps(payload)))


if __name__ == "__main__":
    unittest.main()
