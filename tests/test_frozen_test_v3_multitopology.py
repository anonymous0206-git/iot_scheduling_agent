import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from frozen_test_v2 import seal as sealing
from frozen_test_v2.decisions import SealRefusal
from frozen_test_v2.documents import document_from_data, read_jsonl, sha256_file
from frozen_test_v2.reconcile import reconcile
from frozen_test_v2_fixtures import (
    execute_fields,
    loaded,
    make_benchmark,
    make_decisions,
    make_group,
    make_review,
    write_sealing_support_files,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_SCRIPT = ROOT / "scripts" / "build_topology_catalogue.py"
RUNNER_SCRIPT = ROOT / "scripts" / "run_frozen_test_v3_experiments.py"
CATALOGUE_SETTINGS = dict(sizes=[12, 16], samples=1, area=20, communication_range=10.0,
                          working_period=10, active_slots=2, baseline_channels=2,
                          prefix="tiny", llm_sample_indices=[0])
FIRST, SECOND = "tiny12_seed0", "tiny16_seed0"


def load_script(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def tiny_fields(topology_id=FIRST, **overrides):
    return execute_fields(topology_id=topology_id, communication_range=10.0, **overrides)


def tiny_documents(batch_letter):
    prefix = f"syn-{batch_letter}"
    groups = [
        make_group(f"{prefix}-001", "EXECUTE", fields=tiny_fields(),
                   texts=(f"Schedule {FIRST} for batch {batch_letter} with the usual settings.",
                          f"For batch {batch_letter}, plan a default run on {FIRST}.")),
        make_group(f"{prefix}-002", "EXECUTE", fields=tiny_fields(SECOND, channels=3),
                   texts=(f"Batch {batch_letter}: schedule {SECOND} across three channels.",
                          f"Three channels on {SECOND}, batch {batch_letter}, please.")),
    ]
    return make_benchmark(batch_letter, groups)


def tiny_reconciliation(catalogue):
    benchmark_a, benchmark_b = tiny_documents("a"), tiny_documents("b")
    ready = loaded({"benchmark_a": benchmark_a, "review_of_a": make_review(benchmark_a),
                    "benchmark_b": benchmark_b, "review_of_b": make_review(benchmark_b)})
    return reconcile(ready["benchmark_a"], ready["review_of_a"],
                     ready["benchmark_b"], ready["review_of_b"], catalogue=catalogue)


class MultiTopologySealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue_script = load_script(CATALOGUE_SCRIPT, "build_topology_catalogue")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.support = write_sealing_support_files(self.root)
        self.catalogue_dir = self.root / "cat"
        self.catalogue_script.build_catalogue(output_dir=self.catalogue_dir, **CATALOGUE_SETTINGS)
        self.catalogue = json.loads((self.catalogue_dir / "llm_catalogue.json").read_text(
            encoding="utf-8"))
        self.assertEqual(sorted(self.catalogue), [FIRST, SECOND])

    def tearDown(self):
        self._tmp.cleanup()

    def seal_kwargs(self, **overrides):
        kwargs = dict(
            reconciliation=tiny_reconciliation(self.catalogue),
            decisions=document_from_data(make_decisions([]), path="<memory:decisions>"),
            model_metadata=self.support["model_metadata"],
            prompt_files=self.support["prompt_files"],
            policy_version="synthetic-scope-policy.v2",
            output_dir=self.root / "sealed",
            source_commit={"value": "synthetic", "source": "explicit", "dirty": None},
            catalogue_dir=self.catalogue_dir,
        )
        kwargs.update(overrides)
        return kwargs

    def test_seal_hashes_every_catalogue_topology(self):
        result = sealing.seal(**self.seal_kwargs())
        manifest = result.manifest
        self.assertEqual(manifest["topology_count"], 2)
        self.assertEqual(sorted(manifest["topologies"]), [FIRST, SECOND])
        for topology_id, entry in manifest["topologies"].items():
            self.assertEqual(entry["sha256"], sha256_file(Path(entry["path"])))
            self.assertEqual(entry["sha256"], self.catalogue[topology_id]["sha256"])
            self.assertEqual(entry["communication_range"], 10.0)
            self.assertEqual(entry["node_count"], self.catalogue[topology_id]["node_count"])
        self.assertEqual(sorted(manifest["topology_catalogue"]), [FIRST, SECOND])
        gold = read_jsonl(result.paths["gold_jsonl"])
        self.assertEqual({record["topology_id"] for record in gold}, {FIRST, SECOND})
        self.assertTrue(sealing.verify_sealed_directory(result.output_dir)["valid"])

    def test_explicit_files_may_override_catalogue_paths(self):
        moved = self.root / "moved_first.json"
        moved.write_bytes((self.catalogue_dir / self.catalogue[FIRST]["path"]).read_bytes())
        result = sealing.seal(**self.seal_kwargs(topology_files={FIRST: moved}))
        self.assertEqual(result.manifest["topologies"][FIRST]["path"], str(moved))
        self.assertEqual(result.manifest["topology_count"], 2)

    def test_missing_or_altered_topology_file_is_refused(self):
        (self.catalogue_dir / self.catalogue[SECOND]["path"]).unlink()
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**self.seal_kwargs())
        self.assertTrue(any(SECOND in problem and "not found" in problem
                            for problem in ctx.exception.problems))
        self.assertFalse((self.root / "sealed").exists())

    def test_catalogue_hash_drift_is_refused(self):
        target = self.catalogue_dir / self.catalogue[FIRST]["path"]
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**self.seal_kwargs())
        self.assertTrue(any("does not match the catalogue entry" in problem
                            for problem in ctx.exception.problems))

    def test_entry_without_a_path_needs_an_explicit_file(self):
        catalogue = {key: {k: v for k, v in entry.items() if k != "path"}
                     for key, entry in self.catalogue.items()}
        kwargs = self.seal_kwargs(reconciliation=tiny_reconciliation(catalogue))
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**kwargs)
        self.assertTrue(any("no file for topology" in problem
                            for problem in ctx.exception.problems))


class CatalogueRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue_script = load_script(CATALOGUE_SCRIPT, "build_topology_catalogue")
        cls.runner = load_script(RUNNER_SCRIPT, "run_frozen_test_v3_experiments")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.catalogue_dir = self.root / "cat"
        self.catalogue_script.build_catalogue(output_dir=self.catalogue_dir, **CATALOGUE_SETTINGS)
        self.catalogue_path = self.catalogue_dir / "llm_catalogue.json"
        self.catalogue = json.loads(self.catalogue_path.read_text(encoding="utf-8"))
        self.harness = self.root / "harness.jsonl"
        self.harness.write_text("\n".join(json.dumps(item) for item in [
            {"request_id": "ft3-r0001", "paraphrase_group_id": "v3-a-001",
             "topology_id": FIRST, "user_text": f"Schedule {FIRST} with two channels.",
             "gold_action": "EXECUTE", "category": "default_execution",
             "complexity_level": "basic"},
            {"request_id": "ft3-r0002", "paraphrase_group_id": "v3-a-002",
             "topology_id": SECOND, "user_text": f"Schedule {SECOND} with two channels.",
             "gold_action": "EXECUTE", "category": "default_execution",
             "complexity_level": "basic"},
            {"request_id": "ft3-r0003", "paraphrase_group_id": "v3-a-003",
             "topology_id": None, "user_text": "Schedule the usual network.",
             "gold_action": "CLARIFY", "category": "missing_topology",
             "complexity_level": "basic"},
        ]) + "\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_resolver_loads_checks_and_caches(self):
        resolve = self.runner.catalogue_resolver(self.catalogue, catalogue_dir=self.catalogue_dir)
        instance = resolve(FIRST)
        self.assertEqual(instance.name, FIRST)
        self.assertEqual(len(instance.nodes), 12)
        self.assertIs(resolve(FIRST), instance)
        self.assertIsNone(resolve(None))
        with self.assertRaises(self.runner.CatalogueError):
            resolve("not_in_catalogue")

    def test_resolver_refuses_drifted_or_missing_files(self):
        target = self.catalogue_dir / self.catalogue[SECOND]["path"]
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        resolve = self.runner.catalogue_resolver(self.catalogue, catalogue_dir=self.catalogue_dir)
        with self.assertRaises(self.runner.CatalogueError):
            resolve(SECOND)
        target.unlink()
        with self.assertRaises(self.runner.CatalogueError):
            self.runner.catalogue_resolver(
                self.catalogue, catalogue_dir=self.catalogue_dir)(SECOND)

    def test_check_coverage(self):
        items = read_jsonl(self.harness)
        self.assertEqual(self.runner.check_coverage(items, self.catalogue), [])
        self.assertEqual(self.runner.check_coverage(items, {FIRST: self.catalogue[FIRST]}),
                         [SECOND])

    def run_main(self, *argv):
        with mock.patch("sys.argv", ["run_frozen_test_v3_experiments.py", *argv]), \
                contextlib.redirect_stdout(io.StringIO()):
            return self.runner.main()

    def test_end_to_end_rule_based_run_binds_each_topology(self):
        ledger = self.root / "ledger.jsonl"
        code = self.run_main("--benchmark", str(self.harness),
                             "--topology-catalogue", str(self.catalogue_path),
                             "--catalogue-dir", str(self.catalogue_dir),
                             "--raw-output", str(ledger), "--systems", "rule_based")
        self.assertEqual(code, 0)
        records = read_jsonl(ledger)
        self.assertEqual(len(records), 3)
        by_id = {record["request_id"]: record for record in records}
        self.assertEqual(by_id["ft3-r0001"]["topology_id"], FIRST)
        self.assertEqual(by_id["ft3-r0002"]["topology_id"], SECOND)
        self.assertIsNone(by_id["ft3-r0003"]["topology_id"])
        for request_id in ("ft3-r0001", "ft3-r0002"):
            self.assertEqual(by_id[request_id]["action"], "EXECUTE")
            self.assertTrue(by_id[request_id]["validation"]["valid"])
        self.assertEqual(self.run_main("--benchmark", str(self.harness),
                                       "--topology-catalogue", str(self.catalogue_path),
                                       "--catalogue-dir", str(self.catalogue_dir),
                                       "--raw-output", str(ledger), "--systems", "rule_based"), 0)
        self.assertEqual(len(read_jsonl(ledger)), 3)

    def test_missing_catalogue_coverage_refuses_before_running(self):
        partial = self.root / "partial_catalogue.json"
        partial.write_text(json.dumps({FIRST: self.catalogue[FIRST]}), encoding="utf-8")
        ledger = self.root / "unused.jsonl"
        code = self.run_main("--benchmark", str(self.harness),
                             "--topology-catalogue", str(partial),
                             "--catalogue-dir", str(self.catalogue_dir),
                             "--raw-output", str(ledger), "--systems", "rule_based")
        self.assertEqual(code, 1)
        self.assertFalse(ledger.exists())


if __name__ == "__main__":
    unittest.main()
