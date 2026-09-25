import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_SCRIPT = ROOT / "scripts" / "build_topology_catalogue.py"
EXPERIMENT_SCRIPT = ROOT / "scripts" / "run_topology_scaling_experiment.py"


def load_script(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CATALOGUE_SETTINGS = dict(sizes=[12, 16], samples=3, area=20, communication_range=10.0,
                          working_period=10, active_slots=2, baseline_channels=2,
                          prefix="tiny", llm_sample_indices=[0])


class TopologyScalingExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue_script = load_script(CATALOGUE_SCRIPT, "build_topology_catalogue")
        cls.experiment = load_script(EXPERIMENT_SCRIPT, "run_topology_scaling_experiment")

    def build_catalogue(self, directory):
        self.catalogue_script.build_catalogue(output_dir=directory, **CATALOGUE_SETTINGS)
        return directory / "catalogue.json"

    def test_rows_summary_and_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = self.build_catalogue(Path(tmp) / "cat")
            experiment = self.experiment.run_experiment(catalogue_path=catalogue,
                                                        channels=[1, 2, 3],
                                                        bootstrap_samples=200)
            self.assertEqual(len(experiment["rows"]), 2 * 3 * 3)
            self.assertTrue(all(row["valid"] for row in experiment["rows"]))
            self.assertTrue(all(row["used_channels"] <= row["channels"]
                                for row in experiment["rows"]))
            self.assertEqual([(row["node_count"], row["channels"]) for row in experiment["summary"]],
                             [(12, 1), (12, 2), (12, 3), (16, 1), (16, 2), (16, 3)])
            self.assertTrue(all(row["topologies"] == 3 for row in experiment["summary"]))
            comparisons = experiment["paired_bootstrap"]
            self.assertEqual({(c["node_count"], c["channels"]) for c in comparisons},
                             {(12, 1), (12, 3), (16, 1), (16, 3)})
            for comparison in comparisons:
                self.assertEqual(comparison["pairs"], 3)
                self.assertLessEqual(comparison["ci95"][0], comparison["ci95"][1])
                self.assertEqual(comparison["topologies_improved"] + comparison["topologies_unchanged"]
                                 + comparison["topologies_worse"], 3)
            manifest = self.experiment.write_outputs(experiment, Path(tmp) / "out")
            out = Path(tmp) / "out"
            for name in ("runs.csv", "summary.csv", "paired_bootstrap.json", "manifest.json"):
                self.assertTrue((out / name).is_file(), name)
            self.assertEqual(manifest["runs"], 18)
            self.assertTrue(manifest["all_valid"])
            self.assertTrue(manifest["no_language_model_involved"])
            with (out / "runs.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 18)
            self.assertEqual(rows[0]["topology_id"], "tiny12_seed0")
            self.assertEqual(json.loads((out / "manifest.json").read_text())["settings"]["channels"],
                             [1, 2, 3])
            with self.assertRaises(FileExistsError):
                self.experiment.write_outputs(experiment, out)

    def test_results_are_deterministic_and_hash_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = self.build_catalogue(Path(tmp) / "cat")
            first = self.experiment.run_experiment(catalogue_path=catalogue, channels=[1, 2],
                                                   bootstrap_samples=100)
            second = self.experiment.run_experiment(catalogue_path=catalogue, channels=[1, 2],
                                                    bootstrap_samples=100)
            strip = lambda rows: [{k: v for k, v in row.items()
                                   if k not in ("anex_seconds", "validate_seconds")}
                                  for row in rows]
            self.assertEqual(strip(first["rows"]), strip(second["rows"]))
            self.assertEqual(first["paired_bootstrap"], second["paired_bootstrap"])
            topology = Path(tmp) / "cat" / "tiny12_seed0.json"
            topology.write_text(topology.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                self.experiment.run_experiment(catalogue_path=catalogue, channels=[1, 2],
                                               bootstrap_samples=10)

    def test_invalid_channel_settings_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = self.build_catalogue(Path(tmp) / "cat")
            with self.assertRaises(ValueError):
                self.experiment.run_experiment(catalogue_path=catalogue, channels=[0, 2])
            with self.assertRaises(ValueError):
                self.experiment.run_experiment(catalogue_path=catalogue, channels=[1, 3],
                                               reference_channels=2)


if __name__ == "__main__":
    unittest.main()
