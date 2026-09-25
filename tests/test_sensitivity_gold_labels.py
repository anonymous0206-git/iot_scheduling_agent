"""Tests for the gold-label sensitivity re-scoring.

The script's whole claim is that it changes the labels and nothing else, so
these tests check the two ways that claim can fail: a variant that alters a
record it was not asked to alter, and a selection of contested items that no
longer matches the benchmark it was written against.
"""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sensitivity_gold_labels.py"

CHANNEL_IDS = ("ft3-r0004", "ft3-r0112", "ft3-r0113", "ft3-r0121")
RANGE_IDS = ("ft3-r0033", "ft3-r0106", "ft3-r0130", "ft3-r0141")


def load_script():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        spec = importlib.util.spec_from_file_location("sensitivity_gold_labels", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(ROOT / "scripts"))


def harness_item(request_id, category, action="REJECT"):
    return {"request_id": request_id, "paraphrase_group_id": f"g-{request_id}",
            "gold_action": action, "category": category, "batch_id": "batch-a",
            "user_text": f"text for {request_id}", "gold_fields": None}


def contested_harness(**overrides):
    items = [harness_item(rid, "contradictory_channel_specification"
                          if rid in CHANNEL_IDS[:2] else "prose_parameter_channel_conflict")
             for rid in CHANNEL_IDS]
    items += [harness_item(rid, "communication_range_mismatch"
                           if rid in RANGE_IDS[:2] else "catalogue_range_mismatch")
              for rid in RANGE_IDS]
    items.append(harness_item("ft3-r0500", "synthetic", "EXECUTE"))
    for item in items:
        if item["request_id"] in overrides:
            item.update(overrides[item["request_id"]])
    return items


def record(request_id, gold, action):
    return {"request_id": request_id, "paraphrase_group_id": f"g-{request_id}",
            "gold_action": gold, "action": action, "system": "synthetic", "model": "none",
            "parsed_fields": {}, "validation": None, "clarification_fields": [],
            "success": False, "retries": 0, "model_calls": 0, "wall_time_seconds": 1.0,
            "error_code": None, "failure_category": None}


class ContestedSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def test_selects_the_eight_contested_items_by_category(self):
        found = self.script.contested_ids(contested_harness())
        self.assertEqual(found["channel_conflict"], sorted(CHANNEL_IDS))
        self.assertEqual(found["range_mismatch"], sorted(RANGE_IDS))

    def test_refuses_when_a_category_no_longer_holds_the_expected_items(self):
        items = contested_harness()
        items[0]["category"] = "something_else"
        with self.assertRaises(self.script.SensitivityError):
            self.script.contested_ids(items)

    def test_refuses_when_a_contested_item_is_not_gold_reject(self):
        found = contested_harness(**{"ft3-r0033": {"gold_action": "CLARIFY"}})
        with self.assertRaises(self.script.SensitivityError):
            self.script.contested_ids(found)


class VariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def setUp(self):
        self.repeats = [[record("ft3-r0004", "REJECT", "CLARIFY"),
                         record("ft3-r0033", "REJECT", "EXECUTE"),
                         record("ft3-r0500", "EXECUTE", "EXECUTE")]]

    def test_relabelling_touches_only_the_named_records(self):
        out = self.script.apply_variant(self.repeats, {"ft3-r0004": "CLARIFY"}, [])
        by_id = {r["request_id"]: r for r in out[0]}
        self.assertEqual(by_id["ft3-r0004"]["gold_action"], "CLARIFY")
        self.assertEqual(by_id["ft3-r0033"]["gold_action"], "REJECT")
        self.assertEqual(by_id["ft3-r0500"]["gold_action"], "EXECUTE")

    def test_the_source_records_are_not_mutated(self):
        self.script.apply_variant(self.repeats, {"ft3-r0004": "CLARIFY"}, ["ft3-r0033"])
        self.assertEqual(self.repeats[0][0]["gold_action"], "REJECT")
        self.assertEqual(len(self.repeats[0]), 3)

    def test_dropping_removes_the_item_from_every_repeat(self):
        repeats = self.repeats + [list(self.repeats[0])]
        out = self.script.apply_variant(repeats, {}, ["ft3-r0033"])
        for records in out:
            self.assertNotIn("ft3-r0033", [r["request_id"] for r in records])
            self.assertEqual(len(records), 2)

    def test_empty_variant_is_the_published_labelling(self):
        out = self.script.apply_variant(self.repeats, {}, [])
        self.assertEqual(out, self.repeats)


class EndToEndTests(unittest.TestCase):
    """One arm, one repeat, labels changed by hand: the arithmetic is checkable."""

    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        harness = contested_harness()
        self.harness_path = self.root / "harness.jsonl"
        self.harness_path.write_text(
            "\n".join(json.dumps(item) for item in harness) + "\n", encoding="utf-8")
        # The arm clarifies the channel conflicts, executes the range mismatches
        # and gets the one supported request right: 1 of 9 under the published
        # labels, 5 of 9 if the channel conflicts are CLARIFY.
        records = [record(rid, "REJECT", "CLARIFY") for rid in CHANNEL_IDS]
        records += [record(rid, "REJECT", "EXECUTE") for rid in RANGE_IDS]
        records.append(record("ft3-r0500", "EXECUTE", "EXECUTE"))
        self.ledger_path = self.root / "arm.jsonl"
        self.ledger_path.write_text(
            "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        self.analysis_path = self.root / "analysis.json"
        self.analysis_path.write_text(json.dumps({
            "harness": {"path": str(self.harness_path)},
            "ledgers": {"arm": [str(self.ledger_path)]}}), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, *extra):
        argv = ["sensitivity_gold_labels.py", "--analysis", str(self.analysis_path),
                "--bootstrap-samples", "50", *extra]
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
            status = self.script.main()
        return status, out.getvalue()

    def test_variants_move_the_accuracy_in_the_direction_the_labels_imply(self):
        directory = self.root / "out"
        status, _ = self.run_script("--output-dir", str(directory))
        self.assertEqual(status, 0)
        report = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        variants = {v["label"]: v["arms"]["arm"] for v in report["variants"]}
        self.assertEqual(variants["published"]["items"], 9)
        self.assertAlmostEqual(variants["published"]["action_accuracy"], 1 / 9, places=4)
        self.assertAlmostEqual(variants["channel=CLARIFY"]["action_accuracy"], 5 / 9, places=4)
        self.assertEqual(variants["range dropped"]["items"], 5)
        self.assertAlmostEqual(variants["range dropped"]["action_accuracy"], 1 / 5, places=4)
        self.assertEqual(variants["all 4 groups dropped"]["items"], 1)
        self.assertAlmostEqual(variants["all 4 groups dropped"]["action_accuracy"], 1.0)

    def test_refuses_to_overwrite_an_existing_summary(self):
        directory = self.root / "out"
        directory.mkdir()
        (directory / "summary.json").write_text("{}", encoding="utf-8")
        status, printed = self.run_script("--output-dir", str(directory))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(printed)["status"], "refused")

    def test_reports_no_model_or_scheduler_was_invoked(self):
        directory = self.root / "out"
        self.run_script("--output-dir", str(directory))
        report = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        self.assertTrue(report["no_language_model_or_scheduler_invoked"])
        self.assertEqual(sorted(report["contested_items"]),
                         ["channel_conflict", "range_mismatch"])


if __name__ == "__main__":
    unittest.main()
