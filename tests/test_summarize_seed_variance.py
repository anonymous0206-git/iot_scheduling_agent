import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "summarize_seed_variance.py"

GOLD = {"r1": "EXECUTE", "r2": "CLARIFY", "r3": "REJECT", "r4": "UNSUPPORTED"}


def load_script():
    spec = importlib.util.spec_from_file_location("summarize_seed_variance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SeedVarianceTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.harness = self.write_jsonl("harness.jsonl", [
            {"request_id": rid, "gold_action": gold} for rid, gold in GOLD.items()])

    def tearDown(self):
        self._tmp.cleanup()

    def write_jsonl(self, name, rows):
        path = self.root / name
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                        encoding="utf-8")
        return path

    def repeat(self, name, actions, seed=0):
        return self.write_jsonl(name, [{"request_id": rid, "action": action, "seed": seed}
                                       for rid, action in actions.items()])

    def harness_map(self):
        return {item["request_id"]: item
                for item in self.script.load_jsonl(self.harness)}

    def test_identical_repeats_have_no_spread_and_full_stability(self):
        perfect = dict(GOLD)
        ledgers = [self.repeat("a.jsonl", perfect, seed=0),
                   self.repeat("b.jsonl", perfect, seed=1)]
        arm = self.script.analyse_arm("phi4", [str(p) for p in ledgers], self.harness_map())
        self.assertEqual(arm["accuracy_mean"], 1.0)
        self.assertEqual(arm["accuracy_range"], 0.0)
        self.assertEqual(arm["accuracy_stdev"], 0.0)
        self.assertEqual(arm["stable_items"], 4)
        self.assertEqual(arm["unstable_items"], [])
        self.assertEqual(arm["majority_accuracy"], 1.0)

    def test_a_flipping_item_is_reported_with_its_per_repeat_actions(self):
        first = dict(GOLD)
        second = {**GOLD, "r4": "REJECT"}
        arm = self.script.analyse_arm("phi4", [
            str(self.repeat("a.jsonl", first, seed=0)),
            str(self.repeat("b.jsonl", second, seed=1))], self.harness_map())
        self.assertEqual(arm["stable_items"], 3)
        self.assertEqual(arm["accuracy_min"], 0.75)
        self.assertEqual(arm["accuracy_max"], 1.0)
        self.assertEqual(arm["accuracy_range"], 0.25)
        self.assertEqual(arm["unstable_items"], [
            {"request_id": "r4", "gold_action": "UNSUPPORTED",
             "actions": ["UNSUPPORTED", "REJECT"]}])
        self.assertEqual(arm["unstable_per_gold_action"], {"UNSUPPORTED": 1})
        # two repeats that disagree have no majority, so r4 cannot be counted
        self.assertEqual(arm["majority_correct"], 3)

    def test_majority_rescues_an_item_two_of_three_repeats_get_right(self):
        arm = self.script.analyse_arm("phi4", [
            str(self.repeat("a.jsonl", dict(GOLD), seed=0)),
            str(self.repeat("b.jsonl", {**GOLD, "r4": "REJECT"}, seed=1)),
            str(self.repeat("c.jsonl", dict(GOLD), seed=2))], self.harness_map())
        self.assertEqual(arm["repeats"], 3)
        self.assertEqual(arm["majority_correct"], 4)
        self.assertAlmostEqual(arm["accuracy_mean"], (1.0 + 0.75 + 1.0) / 3, places=4)

    def test_three_way_disagreement_has_no_majority(self):
        arm = self.script.analyse_arm("phi4", [
            str(self.repeat("a.jsonl", dict(GOLD), seed=0)),
            str(self.repeat("b.jsonl", {**GOLD, "r4": "REJECT"}, seed=1)),
            str(self.repeat("c.jsonl", {**GOLD, "r4": "EXECUTE"}, seed=2))], self.harness_map())
        self.assertEqual(arm["majority_correct"], 3)
        self.assertEqual(arm["stable_items"], 3)

    def test_refuses_a_ledger_that_holds_several_seeds(self):
        mixed = self.write_jsonl("mixed.jsonl", [
            {"request_id": "r1", "action": "EXECUTE", "seed": 0},
            {"request_id": "r1", "action": "EXECUTE", "seed": 1}])
        with self.assertRaises(self.script.VarianceError) as caught:
            self.script.analyse_arm("phi4", [str(mixed), str(mixed)], self.harness_map())
        self.assertIn("one repeat per ledger", str(caught.exception))

    def test_refuses_repeats_that_cover_different_items(self):
        short = self.repeat("short.jsonl", {k: v for k, v in GOLD.items() if k != "r4"})
        with self.assertRaises(self.script.VarianceError) as caught:
            self.script.analyse_arm("phi4", [str(self.repeat("a.jsonl", dict(GOLD))),
                                             str(short)], self.harness_map())
        self.assertIn("do not cover the same items", str(caught.exception))

    def test_comparison_calls_a_small_gap_noise(self):
        arms = {"a": {"accuracy_mean": 0.50, "accuracy_range": 0.04},
                "b": {"accuracy_mean": 0.52, "accuracy_range": 0.01}}
        result = self.script.compare(arms)["b minus a"]
        self.assertEqual(result["mean_difference"], 0.02)
        self.assertEqual(result["noise_floor"], 0.04)
        self.assertEqual(result["verdict"], "within the noise floor")

    def test_comparison_calls_a_large_gap_real(self):
        arms = {"a": {"accuracy_mean": 0.40, "accuracy_range": 0.01},
                "b": {"accuracy_mean": 0.55, "accuracy_range": 0.02}}
        self.assertEqual(self.script.compare(arms)["b minus a"]["verdict"],
                         "exceeds the noise floor")

    def run_main(self, *argv):
        out = io.StringIO()
        with mock.patch("sys.argv", ["summarize_seed_variance.py", *argv]), \
                contextlib.redirect_stdout(out):
            code = self.script.main()
        return code, json.loads(out.getvalue())

    def test_cli_writes_once_and_refuses_the_second_time(self):
        argv = ["--harness", str(self.harness),
                "--arm", "phi4={},{}".format(self.repeat("a.jsonl", dict(GOLD), seed=0),
                                             self.repeat("b.jsonl", dict(GOLD), seed=1)),
                "--output-dir", str(self.root / "out")]
        code, payload = self.run_main(*argv)
        self.assertEqual(code, 0)
        self.assertTrue(payload["no_language_model_or_scheduler_invoked"])
        written = (self.root / "out" / "seed_variance.md").read_text(encoding="utf-8")
        self.assertIn("mean accuracy", written)
        code, payload = self.run_main(*argv)
        self.assertEqual(code, 1)
        self.assertIn("refusing to overwrite", payload["problems"][0])

    def test_cli_rejects_an_arm_with_a_single_repeat(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_main("--harness", str(self.harness),
                          "--arm", "phi4={}".format(self.repeat("a.jsonl", dict(GOLD))))


if __name__ == "__main__":
    unittest.main()
