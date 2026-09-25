import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render_results_tables.py"


def load_script():
    spec = importlib.util.spec_from_file_location("render_results_tables", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def arm(correct=60, execute=20, clarify=6, reject=8, unsupported=26, calls=140,
        wall=1.5, false_acceptance=30):
    return {
        "action_accuracy": {"correct": correct, "items": 144,
                            "rate": round(correct / 144, 4)},
        "per_gold_action": {
            "EXECUTE": {"correct": execute, "items": 44},
            "CLARIFY": {"correct": clarify, "items": 12},
            "REJECT": {"correct": reject, "items": 16},
            "UNSUPPORTED": {"correct": unsupported, "items": 72},
        },
        "task_completion": {"completed": correct, "items": 144,
                            "rate": round(correct / 144, 4)},
        "field_exact_match": {"rate": 0.5491},
        "false_acceptance": {"count": false_acceptance,
                             "rate": round(false_acceptance / 144, 4)},
        "paraphrase_consistency": {"consistent_groups": 45, "groups": 72},
        "overhead": {"retries": 25, "model_calls": calls, "total_tokens": 114949,
                     "mean_wall_seconds": wall},
    }


class RenderTablesTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.summary = self.root / "summary.json"
        self.summary.write_text(json.dumps({
            "arms": {"rule_based": arm(54), "phi4_gated": arm(61),
                     "gpt55_gated": arm(122)},
            "paired_comparisons": {
                "phi4_gated minus rule_based": {
                    "mean_difference": 0.0486, "ci95": [-0.0417, 0.1389], "pairs": 144},
                "gpt55_gated minus rule_based": {
                    "mean_difference": 0.4722, "ci95": [0.3819, 0.5625], "pairs": 144},
            },
        }), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def run_main(self, *argv):
        out = io.StringIO()
        with mock.patch("sys.argv", ["render_results_tables.py", *argv]), \
                contextlib.redirect_stdout(out):
            code = self.script.main()
        return code, json.loads(out.getvalue())

    def render(self, *extra):
        out = self.root / "tables.tex"
        code, payload = self.run_main("--summary", str(self.summary), "--out", str(out),
                                      *extra)
        return code, payload, out.read_text(encoding="utf-8") if out.exists() else ""

    def test_labels_fix_both_the_order_and_the_headings(self):
        code, payload, text = self.render(
            "--label", "gpt55_gated=GPT", "--label", "rule_based=Rule")
        self.assertEqual(code, 0)
        self.assertEqual(payload["arms"], ["gpt55_gated", "rule_based"])
        header = [line for line in text.splitlines() if line.startswith("Arm &")][0]
        self.assertEqual(header, r"Arm & GPT & Rule \\")

    def test_numbers_come_from_the_summary_not_from_recomputation(self):
        # The table reports counts out of 144 and lets the caption carry the
        # denominator; a rate in parentheses beside every count cost a column
        # of width the 8-page budget needed elsewhere.
        _, _, text = self.render("--label", "gpt55_gated=GPT")
        self.assertIn(r"Action accuracy & 122 \\", text)
        self.assertIn("20/44", text)
        self.assertIn("0.549", text)

    def test_the_comparison_table_is_unabridged_only(self):
        # Every number in it is also stated in the main-results prose, so the
        # submission cites it and prints it only in the unabridged build.
        _, _, text = self.render("--label", "gpt55_gated=GPT",
                                 "--label", "rule_based=Rule")
        body = text[text.index(r"\label{tab:results-ci}"):]
        self.assertIn(r"\iffull", text[:text.index(r"\label{tab:results-ci}")])
        self.assertTrue(body.rstrip().endswith(r"\fi"), body[-40:])

    def test_an_interval_excluding_zero_is_emphasised(self):
        _, _, text = self.render("--label", "gpt55_gated=GPT",
                                 "--label", "rule_based=Rule",
                                 "--label", "phi4_gated=Phi4")
        self.assertIn(r"\textbf{[+0.3819, +0.5625]}", text)
        self.assertIn("[-0.0417, +0.1389]", text)
        self.assertNotIn(r"\textbf{[-0.0417", text)

    def test_arm_names_are_substituted_into_comparison_labels(self):
        _, _, text = self.render("--label", "gpt55_gated=GPT", "--label", "rule_based=Rule",
                                 "--label", "phi4_gated=Phi4")
        self.assertIn("GPT minus Rule", text)
        self.assertNotIn("gpt55\\_gated minus", text)

    def test_underscores_in_an_unlabelled_arm_are_escaped(self):
        _, _, text = self.render()
        self.assertIn(r"rule\_based", text)
        self.assertNotIn("rule_based &", text)

    def test_the_fragment_says_it_is_generated(self):
        _, _, text = self.render()
        self.assertTrue(text.startswith("% Generated by"))
        self.assertIn("summary.json", text)

    def test_an_unknown_arm_is_refused(self):
        code, payload, _ = self.render("--label", "nope=Nope")
        self.assertEqual(code, 1)
        self.assertIn("no arm named", payload["problems"][0])

    def test_a_malformed_label_is_rejected(self):
        code, payload, text = self.render("--label", "justaname")
        self.assertEqual(code, 1)
        self.assertIn("expected ARM=Label", payload["problems"][0])
        self.assertEqual(text, "", "nothing is written when the arguments are rejected")

    def test_a_summary_without_comparisons_renders_only_the_main_table(self):
        self.summary.write_text(json.dumps({"arms": {"rule_based": arm(54)}}),
                                encoding="utf-8")
        code, payload, text = self.render()
        self.assertEqual(code, 0)
        self.assertEqual(payload["comparisons"], 0)
        self.assertIn(r"\begin{table*}", text)
        self.assertNotIn(r"95\% CI", text)



class CaptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def test_caption_names_the_unit_the_analyser_resampled(self):
        grouped = {"a minus b": {"mean_difference": 0.1, "ci95": [0.0, 0.2], "pairs": 144,
                                 "bootstrap_samples": 10000,
                                 "resample_unit": "paraphrase_group", "resample_units": 72}}
        caption = self.script.comparison_caption(grouped)
        self.assertIn("72 paraphrase groups", caption)
        self.assertIn("10{,}000", caption)
        # The reason for clustering lives in the statistics subsection, not in
        # every caption that reports a clustered interval.
        self.assertNotIn("independent draws", caption)

    def test_caption_follows_the_summary_when_it_resampled_requests(self):
        by_request = {"a minus b": {"mean_difference": 0.1, "ci95": [0.0, 0.2], "pairs": 144,
                                    "bootstrap_samples": 10000,
                                    "resample_unit": "request", "resample_units": 144}}
        caption = self.script.comparison_caption(by_request)
        self.assertIn("144 requests", caption)
        self.assertNotIn("paraphrase", caption)

if __name__ == "__main__":
    unittest.main()
