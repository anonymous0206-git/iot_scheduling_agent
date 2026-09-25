import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_frozen_test_results.py"

GOLD_FIELDS = {
    "topology_id": "topo50_seed0", "workload": "one_shot", "objective": "minimize_latency",
    "channels": 3, "interference_ratio": 1.0, "collision_model": "legacy_neighbor",
    "latency_target_slots": None, "seed": 7, "working_period": 10,
    "communication_range": 20.0,
}


def load_script():
    spec = importlib.util.spec_from_file_location("analyze_frozen_test_results", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def harness_item(request_id, group, action, batch="batch-a", **extra):
    item = {"request_id": request_id, "paraphrase_group_id": group, "gold_action": action,
            "batch_id": batch, "category": "synthetic", "complexity_level": "basic",
            "topology_id": "topo50_seed0", "user_text": f"text for {request_id}",
            "gold_fields": GOLD_FIELDS if action == "EXECUTE" else None}
    item.update(extra)
    return item


def ledger_record(request_id, group, gold, action, **extra):
    record = {"request_id": request_id, "paraphrase_group_id": group, "gold_action": gold,
              "action": action, "system": "synthetic", "model": "none", "seed": 0,
              "parsed_fields": {}, "validation": None, "clarification_fields": [],
              "success": False, "retries": 0, "model_calls": 0, "total_tokens": 0,
              "wall_time_seconds": 1.0, "error_code": None, "failure_category": None}
    record.update(extra)
    return record


def write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.harness_path = self.root / "harness.jsonl"
        self.items = [
            harness_item("r1", "g1", "EXECUTE"),
            harness_item("r2", "g1", "EXECUTE"),
            harness_item("r3", "g2", "UNSUPPORTED", batch="batch-b"),
            harness_item("r4", "g3", "CLARIFY", batch="batch-b"),
        ]
        write_jsonl(self.harness_path, self.items)
        valid = {"valid": True, "violations": []}
        self.records = [
            # correct EXECUTE with a valid schedule and every field parsed correctly
            ledger_record("r1", "g1", "EXECUTE", "EXECUTE", success=True, validation=valid,
                          parsed_fields=dict(GOLD_FIELDS)),
            # EXECUTE answered REJECT, and one field parsed wrongly
            ledger_record("r2", "g1", "EXECUTE", "REJECT",
                          parsed_fields={**GOLD_FIELDS, "channels": 2}),
            # out-of-scope request accepted: a false acceptance without a certificate
            ledger_record("r3", "g2", "UNSUPPORTED", "EXECUTE", success=True),
            # CLARIFY answered CLARIFY but without naming a field
            ledger_record("r4", "g3", "CLARIFY", "CLARIFY"),
        ]
        self.ledger_path = self.root / "arm.jsonl"
        write_jsonl(self.ledger_path, self.records)
        self.harness = {item["request_id"]: item for item in self.items}

    def tearDown(self):
        self._tmp.cleanup()

    def test_core_metrics(self):
        arm = self.script.analyse_arm("arm", self.records, self.harness)
        # r1 and r4 match their gold action; r2 and r3 do not
        self.assertEqual(arm["action_accuracy"], {"correct": 2, "items": 4, "rate": 0.5})
        self.assertEqual(arm["per_gold_action"]["EXECUTE"]["correct"], 1)
        self.assertEqual(arm["confusion_gold_by_predicted"]["EXECUTE"],
                         {"EXECUTE": 1, "CLARIFY": 0, "REJECT": 1, "UNSUPPORTED": 0})
        # r1 completes; r3 has the wrong action; r4 is CLARIFY without a clarification field
        self.assertEqual(arm["task_completion"]["completed"], 1)
        self.assertEqual(arm["false_acceptance"]["count"], 1)
        self.assertEqual(arm["false_acceptance"]["request_ids"], ["r3"])
        self.assertEqual(arm["schedule_validity_on_gold_execute"],
                         {"valid": 1, "items": 2, "rate": 0.5})
        self.assertEqual(arm["paraphrase_consistency"]["consistent_groups"], 2)
        self.assertEqual(arm["paraphrase_consistency"]["inconsistent_groups"], ["g1"])
        self.assertEqual(arm["per_batch"]["batch-a"], {"correct": 1, "items": 2, "rate": 0.5})
        self.assertEqual(sorted(w["request_id"] for w in arm["wrong_items"]), ["r2", "r3"])

    def test_field_exact_match_counts_only_parsed_contract_fields(self):
        match = self.script.analyse_arm("arm", self.records, self.harness)["field_exact_match"]
        # seven parsed fields per EXECUTE item; r1 all correct, r2 wrong on channels
        self.assertEqual(match["total"], 14)
        self.assertEqual(match["matched"], 13)
        self.assertEqual(match["per_field"]["channels"], {"matched": 1, "total": 2, "rate": 0.5})
        self.assertEqual(match["bound_fields_excluded"]["total"], 6)
        self.assertEqual(match["bound_fields_excluded"]["matched"], 6)

    def test_failure_taxonomy_separates_schedule_and_infrastructure(self):
        records = list(self.records)
        records.append(ledger_record("r5", "g4", "EXECUTE", "REJECT",
                                     error_code="VALIDATION_CERTIFICATE_FAILED"))
        records.append(ledger_record("r6", "g4", "EXECUTE", "REJECT",
                                     error_code="PROVIDER_TIMEOUT"))
        harness = dict(self.harness)
        harness["r5"] = harness_item("r5", "g4", "EXECUTE")
        harness["r6"] = harness_item("r6", "g4", "EXECUTE")
        taxonomy = self.script.analyse_arm("arm", records, harness)["failure_taxonomy"]
        self.assertEqual(taxonomy["schedule"], 1)
        self.assertEqual(taxonomy["infrastructure"], 1)
        self.assertEqual(taxonomy["semantic"], 2)

    def test_unknown_request_ids_are_refused(self):
        records = self.records + [ledger_record("rX", "gX", "EXECUTE", "EXECUTE")]
        with self.assertRaises(self.script.AnalysisError):
            self.script.analyse_arm("arm", records, self.harness)

    def test_paired_difference_is_deterministic(self):
        better = [dict(r, action=r["gold_action"]) for r in self.records]
        first = self.script.paired_difference(self.records, better, 200, 0)
        second = self.script.paired_difference(self.records, better, 200, 0)
        self.assertEqual(first, second)
        self.assertEqual(first["pairs"], 4)
        # two of the four items go from wrong to correct
        self.assertEqual(first["mean_difference"], 0.5)

    def test_paired_difference_reports_its_resample_unit(self):
        better = [dict(r, action=r["gold_action"]) for r in self.records]
        by_request = self.script.paired_difference(self.records, better, 200, 0)
        by_group = self.script.paired_difference(self.records, better, 200, 0,
                                                 cluster_by_group=True)
        self.assertEqual(by_request["resample_unit"], "request")
        self.assertEqual(by_request["resample_units"], 4)
        self.assertEqual(by_group["resample_unit"], "paraphrase_group")
        # g1 holds r1 and r2; g2 and g3 hold one request each
        self.assertEqual(by_group["resample_units"], 3)
        # clustering changes only the interval, never the point estimate
        self.assertEqual(by_group["mean_difference"], by_request["mean_difference"])

    def test_clustering_widens_the_interval_when_a_group_moves_together(self):
        """Two wordings of one intent are one draw, so the interval must widen.

        Both groups here are internally consistent and disagree with each
        other, which is the case item-level resampling reads as four
        independent observations and group-level resampling as two.
        """
        groups = [f"g{index}" for index in range(12)]
        base, better = [], []
        for index, group in enumerate(groups):
            for wording in ("a", "b"):
                request = f"{group}{wording}"
                base.append(ledger_record(request, group, "EXECUTE", "REJECT"))
                # half the groups flip both wordings to correct, half stay wrong
                action = "EXECUTE" if index % 2 == 0 else "REJECT"
                better.append(ledger_record(request, group, "EXECUTE", action))
        by_request = self.script.paired_difference(base, better, 4000, 0)
        by_group = self.script.paired_difference(base, better, 4000, 0, cluster_by_group=True)
        self.assertEqual(by_request["mean_difference"], 0.5)
        width = lambda r: r["ci95"][1] - r["ci95"][0]
        self.assertGreater(width(by_group), width(by_request))

    def test_cli_defaults_to_group_resampling_and_reports_both(self):
        out = self.root / "analysis"
        second = self.root / "better.jsonl"
        write_jsonl(second, [dict(r, action=r["gold_action"]) for r in self.records])
        argv = ["analyze_frozen_test_results.py", "--harness", str(self.harness_path),
                "--ledger", f"arm={self.ledger_path}", "--ledger", f"better={second}",
                "--baseline", "arm", "--bootstrap-samples", "200",
                "--output-dir", str(out)]
        with mock.patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.script.main(), 0)
        report = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        comparison = report["paired_comparisons"]["better minus arm"]
        self.assertEqual(comparison["resample_unit"], "paraphrase_group")
        self.assertIn("ci95_by_request", comparison)
        markdown = (out / "summary.md").read_text(encoding="utf-8")
        self.assertIn("resampling by paraphrase_group", markdown)
        self.assertIn("95% CI by request", markdown)

    def test_repeats_of_one_arm_report_a_mean_and_a_range(self):
        worse = [dict(r, action="REJECT") for r in self.records]
        first = self.script.analyse_arm("arm", self.records, self.harness)
        second = self.script.analyse_arm("arm", worse, self.harness)
        merged = self.script.aggregate_repeats("arm", [first, second])
        self.assertEqual(merged["repeat_count"], 2)
        self.assertEqual(merged["action_accuracy"]["correct_repeats"], [2, 0])
        self.assertEqual(merged["action_accuracy"]["correct_min"], 0)
        self.assertEqual(merged["action_accuracy"]["correct_max"], 2)
        # the point value the table prints becomes the mean of the repeats
        self.assertEqual(merged["action_accuracy"]["correct"], 1)

    def test_a_single_repeat_is_left_exactly_as_it_was(self):
        """A one-run campaign must analyse identically to before."""
        only = self.script.analyse_arm("arm", self.records, self.harness)
        self.assertEqual(self.script.aggregate_repeats("arm", [only]), only)
        self.assertNotIn("repeat_count", self.script.aggregate_repeats("arm", [only]))

    def test_an_item_scores_the_fraction_of_repeats_it_survived(self):
        """An item that flips between repeats is partial evidence, not a coin flip."""
        right = [dict(r, action=r["gold_action"]) for r in self.records]
        mixed = self.script.paired_difference([self.records, right], [right, right],
                                              200, 0)
        both_right = self.script.paired_difference([right, right], [right, right],
                                                   200, 0)
        self.assertEqual(both_right["mean_difference"], 0.0)
        # r2 and r3 are wrong in one of the two baseline repeats, so each
        # contributes half a point of difference over the four items
        self.assertAlmostEqual(mixed["mean_difference"], 0.25)
        self.assertEqual(mixed["repeats"], [2, 2])

    def test_a_flat_ledger_still_works_as_one_repeat(self):
        right = [dict(r, action=r["gold_action"]) for r in self.records]
        flat = self.script.paired_difference(self.records, right, 200, 0)
        wrapped = self.script.paired_difference([self.records], [right], 200, 0)
        self.assertEqual(flat["mean_difference"], wrapped["mean_difference"])
        self.assertEqual(flat["repeats"], [1, 1])

    def test_a_provider_outage_is_infrastructure_not_a_refusal(self):
        """Leaving HTTP_PROVIDER_ERROR out of this set once cost us a campaign."""
        records = [ledger_record("r1", "g1", "EXECUTE", "REJECT",
                                 error_code="HTTP_PROVIDER_ERROR"),
                   ledger_record("r2", "g1", "EXECUTE", "REJECT",
                                 error_code="MODEL_UNAVAILABLE"),
                   ledger_record("r3", "g2", "UNSUPPORTED", "REJECT")]
        harness = {"r1": harness_item("r1", "g1", "EXECUTE"),
                   "r2": harness_item("r2", "g1", "EXECUTE"),
                   "r3": harness_item("r3", "g2", "UNSUPPORTED")}
        arm = self.script.analyse_arm("arm", records, harness)
        self.assertEqual(arm["failure_taxonomy"]["infrastructure"], 2)
        self.assertEqual(arm["failure_taxonomy"]["semantic"], 1)
        self.assertEqual(arm["failure_taxonomy"]["infrastructure_request_ids"],
                         ["r1", "r2"])

    def test_cli_writes_once_and_renders_markdown(self):
        out = self.root / "analysis"
        argv = ["analyze_frozen_test_results.py", "--harness", str(self.harness_path),
                "--ledger", f"arm={self.ledger_path}", "--output-dir", str(out)]
        with mock.patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.script.main(), 0)
        report = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertTrue(report["no_language_model_or_scheduler_invoked"])
        self.assertEqual(report["harness"]["items"], 4)
        markdown = (out / "summary.md").read_text(encoding="utf-8")
        self.assertIn("Action accuracy", markdown)
        self.assertIn("Field exact match on EXECUTE", markdown)
        with mock.patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.script.main(), 1)


if __name__ == "__main__":
    unittest.main()
