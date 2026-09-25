import contextlib
import io
import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

from agentic_anex.models import AnexConfig
from agentic_anex.schemas import ScheduleEntry
from agentic_anex.tools import ValidationMode, run_anex, validate_schedule
from agentic_anex.topology_io import generate_network_instance, save_json_topology
from agentic_anex.visualization import (
    VisualizationArtifact,
    main,
    render_interactive_schedule,
    render_schedule,
    render_schedule_report,
    render_topology,
    save_visualization,
)


def replay_payload(content):
    match = re.search(
        r'<script type="application/json" id="anex-replay-data">(.*?)</script>',
        content, re.DOTALL,
    )
    if not match:
        raise AssertionError("interactive replay payload was not embedded")
    return json.loads(match.group(1))


def baseline():
    network = generate_network_instance(
        node_count=30, x_range=40, y_range=40, communication_range=18,
        working_period=10, active_slots_per_node=2, seed=7,
    )
    result = run_anex(network, AnexConfig(
        working_period=10, channels=2, communication_range=18,
        interference_ratio=1.5, seed=7,
    ))
    return network, result


class VisualizationTests(unittest.TestCase):
    def test_topology_svg_is_deterministic_valid_xml(self):
        network, _ = baseline()
        first = render_topology(network, interference_ratio=1.5)
        second = render_topology(network, interference_ratio=1.5)
        self.assertEqual(first.content, second.content)
        self.assertEqual(first.kind, "topology_svg")
        self.assertEqual(first.metadata["statistics"]["node_count"], 30)
        self.assertEqual(first.trace["input_hash"], second.trace["input_hash"])
        root = ET.fromstring(first.content)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("(sink)", first.content)
        self.assertIn("active slots", first.content)
        self.assertIn('aria-label="Legend"', first.content)

    def test_schedule_timeline_shows_slots_links_and_channels(self):
        network, result = baseline()
        artifact = render_schedule(network, result.schedule, validation=result.validation)
        self.assertEqual(artifact.metadata["max_timeslot_index"], 25)
        self.assertEqual(artifact.metadata["latency_slots"], 26)
        self.assertEqual(artifact.metadata["transmissions"], 29)
        self.assertIn("node 1", artifact.content)
        self.assertIn("channel 1", artifact.content)
        self.assertIn('marker-end="url(#schedule-arrow)"', artifact.content)
        self.assertIn('aria-label="Legend"', artifact.content)
        ET.fromstring(artifact.content)

    def test_validation_witnesses_are_highlighted(self):
        network, result = baseline()
        schedule = list(result.schedule)
        siblings = None
        for left, first in enumerate(schedule):
            for right in range(left + 1, len(schedule)):
                if schedule[right].receiver == first.receiver:
                    siblings = left, right
                    break
            if siblings:
                break
        left, right = siblings
        schedule[right] = replace(
            schedule[right], timeslot=schedule[left].timeslot,
            receiver_active_slot=schedule[left].receiver_active_slot,
        )
        report = validate_schedule(
            network, tuple(schedule), ValidationMode("legacy_neighbor", 2, 1.5)
        )
        self.assertFalse(report.valid)
        artifact = render_schedule(network, tuple(schedule), validation=report)
        self.assertGreater(artifact.metadata["violations_highlighted"], 0)
        self.assertIn("#d90429", artifact.content)

    def test_html_report_embeds_visuals_metrics_and_validation(self):
        network, result = baseline()
        report = render_schedule_report(network, result.schedule, result.validation)
        self.assertEqual(report.kind, "schedule_report_html")
        self.assertIn("<!doctype html>", report.content)
        self.assertIn("Validation: PASS", report.content)
        self.assertIn("latency 26 slots", report.content)
        self.assertGreaterEqual(report.content.count("<svg"), 2)
        self.assertEqual(report.metadata["metrics"]["latency_slots"], 26)

    def test_artifacts_are_json_serializable(self):
        network, result = baseline()
        artifacts = (
            render_topology(network),
            render_schedule(network, result.schedule),
            render_schedule_report(network, result.schedule, result.validation),
            render_interactive_schedule(network, result.schedule, validation=result.validation),
        )
        for artifact in artifacts:
            with self.subTest(kind=artifact.kind):
                self.assertEqual(VisualizationArtifact.from_json(artifact.to_json()), artifact)
                json.dumps(artifact.to_dict())

    def test_save_refuses_to_overwrite_by_default(self):
        network, _ = baseline()
        artifact = render_topology(network)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "topology.svg"
            save_visualization(artifact, output)
            original = output.read_text(encoding="utf-8")
            with self.assertRaises(FileExistsError):
                save_visualization(artifact, output)
            self.assertEqual(output.read_text(encoding="utf-8"), original)

    def test_cli_renders_topology_and_schedule(self):
        network, result = baseline()
        with tempfile.TemporaryDirectory() as directory:
            network_path = Path(directory) / "network.json"
            schedule_path = Path(directory) / "schedule.json"
            topology_output = Path(directory) / "topology.svg"
            schedule_output = Path(directory) / "schedule.svg"
            save_json_topology(network, network_path)
            schedule_path.write_text(json.dumps([entry.to_dict() for entry in result.schedule]),
                                     encoding="utf-8")
            for args, output_path, kind in (
                (["topology", "--network", str(network_path), "--output", str(topology_output)],
                 topology_output, "topology_svg"),
                (["schedule", "--network", str(network_path), "--schedule", str(schedule_path),
                  "--output", str(schedule_output)], schedule_output, "schedule_svg"),
            ):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    main(args)
                self.assertTrue(output_path.exists())
                self.assertEqual(json.loads(stdout.getvalue())["kind"], kind)

    def test_interactive_html_is_deterministic_and_preserves_schedule_frames(self):
        network, result = baseline()
        before_schedule = tuple(result.schedule)
        before_validation = result.validation.to_dict()
        first = render_interactive_schedule(
            network, result.schedule, validation=result.validation,
            slot_duration_ms=750, loop=True,
        )
        second = render_interactive_schedule(
            network, result.schedule, validation=result.validation,
            slot_duration_ms=750, loop=True,
        )
        self.assertEqual(first.content, second.content)
        self.assertEqual(first.kind, "interactive_schedule_html")
        self.assertEqual(first.media_type, "text/html")
        self.assertTrue(first.metadata["self_contained"])
        self.assertEqual(first.metadata["max_timeslot_index"], 25)
        self.assertEqual(first.metadata["latency_slots"], 26)
        payload = replay_payload(first.content)
        self.assertEqual([frame["timeslot"] for frame in payload["frames"]], list(range(26)))
        self.assertEqual(payload["slot_duration_ms"], 750)
        self.assertTrue(any(len(frame["transmissions"]) > 1 for frame in payload["frames"]))
        flattened = [tx for frame in payload["frames"] for tx in frame["transmissions"]]
        expected = [entry.to_dict() for entry in sorted(
            result.schedule, key=lambda item: (item.timeslot, item.sender, item.receiver, item.channel)
        )]
        self.assertEqual(
            [{key: tx[key] for key in expected[0]} for tx in flattened], expected
        )
        self.assertEqual(tuple(result.schedule), before_schedule)
        self.assertEqual(result.validation.to_dict(), before_validation)

    def test_interactive_controls_and_slider_bounds_are_embedded(self):
        network, result = baseline()
        content = render_interactive_schedule(network, result.schedule).content
        for control_id in (
            "play-button", "pause-button", "previous-slot-button", "next-slot-button",
            "restart-button", "timeline-slider", "playback-speed", "loop-toggle",
            "links-toggle", "active-slots-toggle",
        ):
            self.assertIn(f'id="{control_id}"', content)
        self.assertIn('id="timeline-slider" type="range" min="0" max="25"', content)
        self.assertIn("TX ", content)
        self.assertIn("RX ", content)
        self.assertIn("CH ", content)
        self.assertIn(".tx-event{display:none}", content)
        self.assertIn(".tx-event.is-current{display:inline}", content)
        self.assertIn("classList.toggle('is-current',active)", content)
        self.assertIn('markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11"', content)
        self.assertIn("loopEnabled=e.target.checked", content)
        self.assertIn("classList.toggle('overlay-hidden',!e.target.checked)", content)
        self.assertNotIn('src="http', content)
        self.assertNotIn('href="http', content)

    def test_interactive_validation_witness_is_embedded_and_highlighted(self):
        network, result = baseline()
        schedule = list(result.schedule)
        siblings = next(
            (left, right)
            for left, first in enumerate(schedule)
            for right in range(left + 1, len(schedule))
            if schedule[right].receiver == first.receiver
        )
        left, right = siblings
        schedule[right] = replace(
            schedule[right], timeslot=schedule[left].timeslot,
            receiver_active_slot=schedule[left].receiver_active_slot,
        )
        validation = validate_schedule(
            network, tuple(schedule), ValidationMode("legacy_neighbor", 2, 1.5)
        )
        artifact = render_interactive_schedule(network, tuple(schedule), validation=validation)
        payload = replay_payload(artifact.content)
        embedded_codes = {
            warning["code"] for frame in payload["frames"]
            for tx in frame["transmissions"] for warning in tx["violations"]
        }
        self.assertTrue(embedded_codes)
        self.assertTrue(embedded_codes.issubset({item.code for item in validation.violations}))
        self.assertIn('class="tx-event violated"', artifact.content)
        for violation in validation.violations:
            self.assertIn(violation.code, artifact.content)
            self.assertIn(str(violation.timeslots), artifact.content)

    def test_cli_creates_interactive_html(self):
        network, result = baseline()
        with tempfile.TemporaryDirectory() as directory:
            network_path = Path(directory) / "network.json"
            schedule_path = Path(directory) / "schedule.json"
            validation_path = Path(directory) / "validation.json"
            output = Path(directory) / "schedule.html"
            save_json_topology(network, network_path)
            schedule_path.write_text(json.dumps([entry.to_dict() for entry in result.schedule]),
                                     encoding="utf-8")
            validation_path.write_text(result.validation.to_json(), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main(["animate", "--network", str(network_path), "--schedule", str(schedule_path),
                      "--validation", str(validation_path), "--slot-duration-ms", "250", "--loop",
                      "--output", str(output)])
            self.assertEqual(json.loads(stdout.getvalue())["kind"], "interactive_schedule_html")
            self.assertTrue(output.exists())
            payload = replay_payload(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["max_timeslot"], 25)
            self.assertEqual(payload["slot_duration_ms"], 250)
            self.assertTrue(payload["loop"])


if __name__ == "__main__":
    unittest.main()
