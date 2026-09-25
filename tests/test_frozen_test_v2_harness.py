import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from frozen_test_v2 import harness
from frozen_test_v2 import seal as sealing
from frozen_test_v2.documents import document_from_data, read_jsonl, sha256_text
from frozen_test_v2.reconcile import reconcile
from frozen_test_v2_fixtures import (
    TOPOLOGY_ID,
    execute_fields,
    loaded,
    make_benchmark,
    make_decisions,
    make_group,
    make_review,
    reject_group,
    write_sealing_support_files,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_frozen_test_v2_harness.py"


def gold_record(request_id, text, action, **extra):
    record = {
        "request_id": request_id,
        "source_request_id": f"src-{request_id}",
        "semantic_group_id": "syn-x-001",
        "batch_id": "synthetic-model-x",
        "paraphrase_index": 1,
        "gold_action": action,
        "gold_fields": None,
        "invalid_fields": None,
        "topology_id": None,
        "difficulty": "easy",
        "capability_category": "synthetic_case",
        "reconciliation_class": "FULL_AGREEMENT",
        "decision_source": "dual_agreement",
        "paraphrase_equivalence_source": "reviewer",
        "request_text_sha256": sha256_text(text),
    }
    record.update(extra)
    return record


def topology_groups(batch_letter):
    prefix = f"syn-{batch_letter}"
    tag = f"experiment {batch_letter.upper()}"
    return [
        make_group(f"{prefix}-001", "EXECUTE", fields=execute_fields(channels=3),
                   texts=(f"Schedule {TOPOLOGY_ID} with three channels for {tag}, please.",
                          f"For {tag}, please plan a three-channel run on {TOPOLOGY_ID}.")),
        make_group(f"{prefix}-002", "CLARIFY", fields=None, difficulty="medium",
                   texts=(f"Schedule the {tag} run with three channels and report the latency.",
                          f"Three channels for {tag}, report the latency; schedule it now.")),
        reject_group(f"{prefix}-003",
                     texts=(f"Schedule {TOPOLOGY_ID} with zero channels for {tag}.",
                            f"For {tag}, use no channels at all on {TOPOLOGY_ID}.")),
        make_group(f"{prefix}-004", "UNSUPPORTED", fields=None, difficulty="hard",
                   texts=(f"Build a digital twin of {TOPOLOGY_ID} for {tag} and emulate it.",
                          f"For {tag}, emulate {TOPOLOGY_ID} inside a digital twin.")),
    ]


class BindTopologyTests(unittest.TestCase):
    def test_whole_token_binding(self):
        self.assertEqual(harness.bind_topology(f"Run {TOPOLOGY_ID} now."), TOPOLOGY_ID)
        self.assertEqual(harness.bind_topology(f"Run ({TOPOLOGY_ID}) now."), TOPOLOGY_ID)
        self.assertIsNone(harness.bind_topology("Run legacy30_seed8 now."))
        self.assertIsNone(harness.bind_topology("Run legacy30_seed70 now."))
        self.assertIsNone(harness.bind_topology("Run the usual topology now."))

    def test_two_catalogue_topologies_in_one_text_bind_to_none(self):
        catalogue = {"topo_a": {}, "topo_b": {}}
        self.assertEqual(harness.bind_topologies("Use topo_a or topo_b.", catalogue),
                         ["topo_a", "topo_b"])
        self.assertIsNone(harness.bind_topology("Use topo_a or topo_b.", catalogue))
        self.assertEqual(harness.bind_topology("Use topo_a only.", catalogue), "topo_a")

    def test_ambiguous_selection_is_unbound_and_noted(self):
        catalogue = {"topo_a": {"working_period": 10, "communication_range": 20.0},
                     "topo_b": {"working_period": 10, "communication_range": 20.0}}
        text = "Schedule either topo_a or topo_b, whichever the deployment uses."
        requests = [{"request_id": "ft3-r0001", "request_text": text}]
        gold = [gold_record("ft3-r0001", text, "CLARIFY")]
        export = harness.build_harness_items(requests, gold, catalogue=catalogue)
        item = export.items[0]
        self.assertIsNone(item["topology_id"])
        self.assertIn("ambiguous", item["topology_binding_note"])
        self.assertEqual(export.summary["requests_naming_multiple_topologies"], ["ft3-r0001"])
        self.assertEqual(export.summary["topology_bound"], 0)


class BuildHarnessItemsTests(unittest.TestCase):
    def test_items_carry_runner_fields_and_binding(self):
        texts = {
            "ft2-r0001": f"Schedule {TOPOLOGY_ID} with three channels.",
            "ft2-r0002": "Schedule the run with three channels.",
            "ft2-r0003": "Run the scheduler on topology legacy50_seed3.",
        }
        requests = [{"request_id": rid, "request_text": text} for rid, text in texts.items()]
        gold = [
            gold_record("ft2-r0001", texts["ft2-r0001"], "EXECUTE",
                        gold_fields=execute_fields(channels=3), topology_id=TOPOLOGY_ID,
                        difficulty="hard"),
            gold_record("ft2-r0002", texts["ft2-r0002"], "CLARIFY", difficulty="medium"),
            gold_record("ft2-r0003", texts["ft2-r0003"], "REJECT",
                        gold_fields={"topology_id": "legacy50_seed3"},
                        invalid_fields={"topology_id": {"observed": "legacy50_seed3",
                                                        "reason": "unknown"}},
                        topology_id="legacy50_seed3"),
        ]
        export = harness.build_harness_items(requests, gold)
        by_id = {item["request_id"]: item for item in export.items}
        self.assertEqual(by_id["ft2-r0001"]["topology_id"], TOPOLOGY_ID)
        self.assertEqual(by_id["ft2-r0001"]["complexity_level"], "advanced")
        self.assertEqual(by_id["ft2-r0001"]["gold_action"], "EXECUTE")
        self.assertEqual(by_id["ft2-r0001"]["paraphrase_group_id"], "syn-x-001")
        self.assertEqual(by_id["ft2-r0001"]["category"], "synthetic_case")
        self.assertIsNone(by_id["ft2-r0002"]["topology_id"])
        self.assertEqual(by_id["ft2-r0002"]["complexity_level"], "intermediate")
        self.assertIsNone(by_id["ft2-r0003"]["topology_id"])
        self.assertIn("legacy50_seed3", by_id["ft2-r0003"]["topology_binding_note"])
        self.assertEqual(export.summary["requests_naming_uncatalogued_topology"], ["ft2-r0003"])
        self.assertEqual(export.summary["topology_bound"], 1)
        self.assertEqual(export.summary["per_action"],
                         {"EXECUTE": 1, "CLARIFY": 1, "REJECT": 1, "UNSUPPORTED": 0})
        for item in export.items:
            for key in ("request_id", "paraphrase_group_id", "topology_id", "user_text",
                        "gold_action", "category", "complexity_level"):
                self.assertIn(key, item)

    def test_text_hash_mismatch_and_coverage_errors(self):
        text = f"Schedule {TOPOLOGY_ID} now."
        requests = [{"request_id": "ft2-r0001", "request_text": text}]
        tampered = [gold_record("ft2-r0001", text + " tampered", "CLARIFY")]
        with self.assertRaises(harness.HarnessExportError):
            harness.build_harness_items(requests, tampered)
        with self.assertRaises(harness.HarnessExportError):
            harness.build_harness_items(requests, [gold_record("ft2-r0009", text, "CLARIFY")])
        with self.assertRaises(harness.HarnessExportError):
            harness.build_harness_items(requests + requests,
                                        [gold_record("ft2-r0001", text, "CLARIFY")])


class HarnessScriptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        support = write_sealing_support_files(self.root)
        benchmark_a = make_benchmark("a", topology_groups("a"))
        benchmark_b = make_benchmark("b", topology_groups("b"))
        docs = loaded({
            "benchmark_a": benchmark_a, "review_of_a": make_review(benchmark_a),
            "benchmark_b": benchmark_b, "review_of_b": make_review(benchmark_b),
        })
        reconciliation = reconcile(docs["benchmark_a"], docs["review_of_a"],
                                   docs["benchmark_b"], docs["review_of_b"])
        self.sealed = sealing.seal(
            reconciliation=reconciliation,
            decisions=document_from_data(make_decisions([]), path="<memory:decisions>"),
            model_metadata=support["model_metadata"],
            prompt_files=support["prompt_files"],
            topology_files=support["topology_files"],
            policy_version="synthetic-scope-policy.v2",
            output_dir=self.root / "sealed",
            source_commit={"value": "synthetic", "source": "explicit", "dirty": None},
        ).output_dir
        spec = importlib.util.spec_from_file_location("export_frozen_test_v2_harness", SCRIPT)
        self.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.script)

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, *argv):
        with mock.patch("sys.argv", ["export_frozen_test_v2_harness.py", *argv]), \
                contextlib.redirect_stdout(io.StringIO()):
            return self.script.main()

    def test_export_writes_harness_and_manifest_once(self):
        output = self.root / "harness" / "frozen_test_v2_harness.jsonl"
        code = self.run_script("--sealed-dir", str(self.sealed), "--output", str(output))
        self.assertEqual(code, 0)
        items = read_jsonl(output)
        self.assertEqual(len(items), 16)
        bound = [item for item in items if item["topology_id"] == TOPOLOGY_ID]
        self.assertEqual(len(bound), 12)
        self.assertTrue(all(item["topology_id"] is None for item in items
                            if item["gold_action"] == "CLARIFY"))
        manifest = json.loads(output.with_name(output.name + ".manifest.json").read_text(
            encoding="utf-8"))
        self.assertEqual(manifest["output"]["records"], 16)
        self.assertTrue(manifest["evaluator_side_only"])
        self.assertEqual(manifest["summary"]["per_action"],
                         {"EXECUTE": 4, "CLARIFY": 4, "REJECT": 4, "UNSUPPORTED": 4})
        self.assertEqual(self.run_script("--sealed-dir", str(self.sealed),
                                         "--output", str(output)), 1)

    def test_export_refuses_a_tampered_sealed_directory(self):
        requests_path = self.sealed / sealing.SEALED_FILENAMES["requests_jsonl"]
        requests_path.write_text(requests_path.read_text(encoding="utf-8").replace(
            "channels", "channel"), encoding="utf-8")
        output = self.root / "harness.jsonl"
        self.assertEqual(self.run_script("--sealed-dir", str(self.sealed),
                                         "--output", str(output)), 1)
        self.assertFalse(output.exists())

    def test_harness_items_are_accepted_by_the_experiment_runner(self):
        from agentic_anex.experiments import SystemRunOutput, load_experiment_records, run_experiment_matrix

        output = self.root / "harness.jsonl"
        self.assertEqual(self.run_script("--sealed-dir", str(self.sealed),
                                         "--output", str(output)), 0)
        items = read_jsonl(output)

        class EchoSystem:
            system_name = "synthetic_echo"
            model_name = "none"

            def run(self, item, topology, seed):
                return SystemRunOutput(parsed_fields={}, action=item["gold_action"],
                                       success=item["gold_action"] == "EXECUTE")

        ledger = self.root / "ledger.jsonl"
        summary = run_experiment_matrix(items, [EchoSystem()], (0,), ledger,
                                        topology_resolver=lambda topology_id: None)
        self.assertEqual(summary.get("written"), 16)
        records = load_experiment_records(ledger)
        self.assertEqual(len(records), 16)
        self.assertTrue(all(record.action == record.gold_action for record in records))
        self.assertEqual({record.complexity_level for record in records},
                         {"basic", "intermediate", "advanced"})


if __name__ == "__main__":
    unittest.main()
