import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from frozen_test_v2.contract import field_violations

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_topology_catalogue.py"


def load_script():
    spec = importlib.util.spec_from_file_location("build_topology_catalogue", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SETTINGS = dict(sizes=[12, 16], samples=2, area=20, communication_range=10.0,
                working_period=10, active_slots=2, baseline_channels=2, prefix="tiny",
                llm_sample_indices=[0])


class TopologyCatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def test_catalogue_files_and_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cat"
            catalogue = self.script.build_catalogue(output_dir=out, **SETTINGS)
            self.assertEqual(len(catalogue["topologies"]), 4)
            for topology_id, entry in catalogue["topologies"].items():
                self.assertTrue((out / entry["path"]).is_file(), topology_id)
                self.assertTrue((out / entry["baseline_schedule_path"]).is_file(), topology_id)
                self.assertEqual(self.script.sha256_file(out / entry["path"]), entry["sha256"])
                self.assertEqual(entry["working_period"], 10)
                self.assertEqual(entry["communication_range"], 10.0)
                self.assertTrue(entry["baseline"]["valid"], topology_id)
                self.assertEqual(entry["baseline"]["elapsed_latency_slots"],
                                 entry["baseline"]["max_timeslot_index"] + 1)
                self.assertGreaterEqual(entry["max_bfs_layer"], 1)
                network = json.loads((out / entry["path"]).read_text(encoding="utf-8"))
                self.assertEqual(len(network["nodes"]), entry["node_count"])
                self.assertEqual(network["name"], topology_id)
                schedule = json.loads((out / entry["baseline_schedule_path"]).read_text(
                    encoding="utf-8"))
                self.assertEqual(len(schedule["schedule"]), entry["node_count"] - 1)
            written = json.loads((out / "catalogue.json").read_text(encoding="utf-8"))
            self.assertEqual(written["catalogue_format"], self.script.CATALOGUE_FORMAT)
            self.assertEqual(set(written["topologies"]), set(catalogue["topologies"]))
            llm = json.loads((out / "llm_catalogue.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(llm), ["tiny12_seed0", "tiny16_seed0"])
            rows = self.script.summarize(catalogue)
            self.assertEqual([row["node_count"] for row in rows], [12, 16])
            self.assertTrue(all(row["all_baselines_valid"] for row in rows))

    def test_llm_catalogue_is_accepted_by_the_pipeline_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cat"
            self.script.build_catalogue(output_dir=out, **SETTINGS)
            llm = json.loads((out / "llm_catalogue.json").read_text(encoding="utf-8"))
            good = {"topology_id": "tiny12_seed0", "working_period": 10, "communication_range": 10.0}
            self.assertEqual(field_violations(good, catalogue=llm), {})
            bad = {"topology_id": "tiny12_seed0", "working_period": 12, "communication_range": 18.0}
            self.assertEqual(set(field_violations(bad, catalogue=llm)),
                             {"working_period", "communication_range"})
            self.assertIn("topology_id", field_violations({"topology_id": "tiny12_seed1"},
                                                          catalogue=llm))

    def test_generation_is_deterministic_and_write_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.script.build_catalogue(output_dir=Path(tmp) / "a", **SETTINGS)
            second = self.script.build_catalogue(output_dir=Path(tmp) / "b", **SETTINGS)
            for topology_id, entry in first["topologies"].items():
                self.assertEqual(entry["sha256"], second["topologies"][topology_id]["sha256"])
                self.assertEqual(entry["baseline_schedule_sha256"],
                                 second["topologies"][topology_id]["baseline_schedule_sha256"])
            with self.assertRaises(FileExistsError):
                self.script.build_catalogue(output_dir=Path(tmp) / "a", **SETTINGS)

    def test_invalid_settings_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                self.script.build_catalogue(output_dir=Path(tmp) / "x",
                                            **{**SETTINGS, "llm_sample_indices": [5]})
            with self.assertRaises(ValueError):
                self.script.build_catalogue(output_dir=Path(tmp) / "y",
                                            **{**SETTINGS, "sizes": []})


if __name__ == "__main__":
    unittest.main()
