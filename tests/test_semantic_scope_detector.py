"""The semantic-detector comparison must not be able to mispair its inputs.

The measurement is a comparison between two detectors over two request groups
defined elsewhere, in the figure data. Three things would silently corrupt it: a
phrasing group naming a request that is not gold-``UNSUPPORTED``, ledgers whose
regex verdicts disagree (which the regex cannot do on the same texts, so it
means the ledgers came from different requests), and a request the detector
never answered being counted as in scope. These tests are those three, plus the
arithmetic.
"""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_semantic_scope_detector.py"
ANALYZER = ROOT / "scripts" / "analyze_semantic_scope_detector.py"


def load_script(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PromptTests(unittest.TestCase):
    """The prompt is built from the policy, so it cannot drift from the regex."""

    def setUp(self):
        self.runner = load_script(RUNNER, "run_semantic_scope_detector")

    def test_every_taxonomy_category_reaches_the_prompt(self):
        from agentic_anex.scope_policy import CHECKED_TAXONOMY
        prompt = self.runner.prompt_for("Plan one collection on topo50_seed0.")
        for category in CHECKED_TAXONOMY:
            self.assertIn(category, prompt)

    def test_the_prompt_carries_the_rule_the_regex_cannot_express(self):
        prompt = self.runner.prompt_for("anything")
        # The hard negatives are gold EXECUTE precisely because mentioning an
        # out-of-scope concept is not asking for it. A comparison that withheld
        # this would charge the model for a distinction the gold labels make.
        self.assertIn("merely mentions", prompt)
        self.assertIn("IN SCOPE", prompt)

    def test_the_schema_admits_only_taxonomy_categories(self):
        from agentic_anex.scope_policy import CHECKED_TAXONOMY
        schema = self.runner.RESPONSE_SCHEMA
        self.assertEqual(schema["properties"]["categories"]["items"]["enum"],
                         list(CHECKED_TAXONOMY))
        self.assertFalse(schema["additionalProperties"])


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = load_script(ANALYZER, "analyze_semantic_scope_detector")
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledgers = self.root / "ledgers"
        self.ledgers.mkdir()
        # Four requests: two unsupported (one naming, one composing) and two
        # executable, one of which is a hard negative the regex over-blocks.
        self.harness = self.root / "harness.jsonl"
        self.harness.write_text("".join(json.dumps(item) + "\n" for item in [
            {"request_id": "r1", "gold_action": "UNSUPPORTED", "category": "c",
             "user_text": "x", "paraphrase_group_id": "g1"},
            {"request_id": "r2", "gold_action": "UNSUPPORTED", "category": "c",
             "user_text": "x", "paraphrase_group_id": "g2"},
            {"request_id": "r3", "gold_action": "EXECUTE", "category": "c",
             "user_text": "x", "paraphrase_group_id": "g3"},
            {"request_id": "r4", "gold_action": "EXECUTE", "category": "c",
             "user_text": "x", "paraphrase_group_id": "g4"},
        ]), encoding="utf-8")
        self.phrasing = self.root / "phrasing.json"
        self.write_phrasing({"names the capability": ["r1"],
                             "composes it from ordinary words": ["r2"]})

    def tearDown(self):
        self._tmp.cleanup()

    def write_phrasing(self, groups):
        self.phrasing.write_text(json.dumps({
            "request_ids": groups,
            "series": {
                "names the capability": {"caught by the ungated agent": 1.0},
                "composes it from ordinary words": {"caught by the ungated agent": 1.0},
            },
        }), encoding="utf-8")

    def write_ledger(self, seed, rows):
        path = self.ledgers / f"semantic_scope_seed{seed}.jsonl"
        path.write_text("".join(json.dumps({
            "detector_version": "test.v1", "seed": seed, **row}) + "\n"
            for row in rows), encoding="utf-8")

    @staticmethod
    def row(rid, gold, regex_in_scope, semantic_in_scope):
        record = {"request_id": rid, "gold_action": gold, "category": "c",
                  "regex_in_scope": regex_in_scope, "regex_categories": []}
        if semantic_in_scope is not None:
            record["semantic_in_scope"] = semantic_in_scope
            record["semantic_categories"] = []
            record["semantic_evidence"] = "quoted words"
        return record

    def run_analyzer(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), mock.patch("sys.argv", [
                "analyze", "--ledger-dir", str(self.ledgers),
                "--harness", str(self.harness), "--phrasing", str(self.phrasing),
                "--out", str(self.root / "out")]):
            code = self.analyzer.main()
        return code, json.loads(buffer.getvalue())

    def test_recall_and_over_blocking_are_counted_per_group(self):
        # Regex catches the naming one only, and over-blocks r3.
        # The semantic detector catches both and over-blocks nothing.
        rows = [self.row("r1", "UNSUPPORTED", False, False),
                self.row("r2", "UNSUPPORTED", True, False),
                self.row("r3", "EXECUTE", False, True),
                self.row("r4", "EXECUTE", True, True)]
        self.write_ledger(11, rows)
        code, report = self.run_analyzer()
        self.assertEqual(code, 0)
        self.assertEqual(report["regex_gate"]["recall_names"], 1)
        self.assertEqual(report["regex_gate"]["recall_composes"], 0)
        self.assertEqual(report["regex_gate"]["over_blocked_execute"], 1)
        self.assertEqual(report["semantic_detector"]["recall_names"], 1.0)
        self.assertEqual(report["semantic_detector"]["recall_composes"], 1.0)
        self.assertEqual(report["semantic_detector"]["over_blocked_execute"], 0.0)
        # r2 and r3 are decided differently by the two detectors.
        self.assertEqual(report["disagreements"], 2)

    def test_a_seed_that_samples_differently_is_averaged_not_collapsed(self):
        base = [self.row("r1", "UNSUPPORTED", False, False),
                self.row("r3", "EXECUTE", False, True),
                self.row("r4", "EXECUTE", True, True)]
        self.write_ledger(11, base + [self.row("r2", "UNSUPPORTED", True, False)])
        self.write_ledger(12, base + [self.row("r2", "UNSUPPORTED", True, True)])
        code, report = self.run_analyzer()
        self.assertEqual(code, 0)
        self.assertEqual(report["semantic_detector"]["recall_composes"], 0.5)
        summary = json.loads((self.root / "out" / "summary.json").read_text())
        self.assertEqual(summary["semantic_detector"]["recall_composes"]["per_seed"],
                         [1.0, 0.0])

    def test_a_phrasing_group_naming_a_supported_request_is_refused(self):
        self.write_phrasing({"names the capability": ["r1"],
                             "composes it from ordinary words": ["r3"]})
        self.write_ledger(11, [self.row("r1", "UNSUPPORTED", False, False)])
        code, report = self.run_analyzer()
        self.assertEqual(code, 1)
        self.assertIn("not", report["problems"][0])
        self.assertIn("r3", report["problems"][0])

    def test_ledgers_whose_regex_verdicts_disagree_are_refused(self):
        self.write_ledger(11, [self.row("r1", "UNSUPPORTED", False, False)])
        self.write_ledger(12, [self.row("r1", "UNSUPPORTED", True, False)])
        code, report = self.run_analyzer()
        self.assertEqual(code, 1)
        self.assertIn("regex verdict differs", report["problems"][0])

    def test_an_unanswered_request_is_recorded_and_not_counted_as_caught(self):
        rows = [self.row("r1", "UNSUPPORTED", False, None),
                self.row("r2", "UNSUPPORTED", True, False)]
        self.write_ledger(11, rows)
        code, report = self.run_analyzer()
        self.assertEqual(code, 0)
        self.assertEqual(report["semantic_detector"]["recall_names"], 0.0)
        summary = json.loads((self.root / "out" / "summary.json").read_text())
        self.assertEqual(summary["semantic_detector_per_seed"][0]["unanswered_requests"],
                         ["r1"])

    def test_no_ledgers_is_refused_rather_than_reported_as_zero(self):
        code, report = self.run_analyzer()
        self.assertEqual(code, 1)
        self.assertIn("no semantic_scope_seed", report["problems"][0])


if __name__ == "__main__":
    unittest.main()
