import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render_holdout_table.py"


def load_script():
    spec = importlib.util.spec_from_file_location("render_holdout_table", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def arm(correct, false_acceptance, joint):
    return {
        "action_accuracy": {"correct": correct, "items": 72,
                            "rate": round(correct / 72, 4)},
        "false_acceptance": {"count": false_acceptance, "items": 72,
                             "rate": round(false_acceptance / 72, 4)},
        "joint_intent_success": {"completed": joint, "items": 24,
                                 "rate": round(joint / 24, 4)},
    }


def summary(arms, comparisons=None):
    return {"arms": arms, "paired_comparisons": comparisons or {}}


class HoldoutTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def main_summary(self):
        return summary({
            "rule_based": arm(36, 24, 0),
            "phi4_gated": arm(29, 15, 7),
            "phi4_no_gate": arm(26, 17, 13),
            "gpt55_gated": arm(52, 4, 8),
            "gpt55_no_gate": arm(58, 4, 15),
        })

    def ablations(self):
        return {
            "phi4": summary({}, {"phi4_no_gate minus phi4_gated": {
                "mean_difference": -0.0417, "ci95": [-0.1667, 0.0833]}}),
            "gpt": summary({}, {"gpt55_no_gate minus gpt55_gated": {
                "mean_difference": 0.0787, "ci95": [-0.0139, 0.1852]}}),
        }

    def test_renders_every_metric_and_the_contrast(self):
        out = self.script.render(self.main_summary(), self.ablations())
        self.assertIn(r"\label{tab:holdout}", out)
        self.assertIn("36 (0.500)", out)          # rule action accuracy
        self.assertIn("24 (0.333)", out)          # rule false acceptance
        self.assertIn("0/24", out)                # rule joint intent success
        self.assertIn("$-0.0417$", out)           # the 14B contrast
        self.assertIn("$+0.0787$", out)           # the frontier contrast
        self.assertIn("[$-0.167$, $+0.083$]", out)

    def test_enforcing_arms_and_the_baseline_carry_no_contrast(self):
        out = self.script.render(self.main_summary(), self.ablations())
        rows = {line.split("&")[0].strip(): line
                for line in out.splitlines() if "&" in line}
        for label in ("Rule", "Phi4", "GPT"):
            self.assertTrue(rows[label].rstrip(r" \\").rstrip().endswith("---"),
                            f"{label} should have no ablation contrast")

    def test_an_arm_absent_from_the_summary_is_skipped(self):
        report = summary({"rule_based": arm(36, 24, 0)})
        out = self.script.render(report, {})
        self.assertIn("Rule", out)
        self.assertNotIn("Phi4", out)

    def test_a_missing_contrast_prints_a_dash_rather_than_failing(self):
        # A family summary that does not carry the contrast must not be invented.
        out = self.script.render(self.main_summary(), {"phi4": summary({}, {})})
        self.assertIn("Phi4-ng", out)
        self.assertNotIn("$-0.0417$", out)

    def test_cli_writes_the_fragment_with_its_source(self):
        main_path = self.root / "main.json"
        phi_path = self.root / "phi4.json"
        out_path = self.root / "generated" / "holdout_table.tex"
        main_path.write_text(json.dumps(self.main_summary()), encoding="utf-8")
        phi_path.write_text(json.dumps(self.ablations()["phi4"]), encoding="utf-8")
        argv = ["render_holdout_table.py", "--summary", str(main_path),
                "--ablation", f"phi4={phi_path}", "--out", str(out_path)]
        with mock.patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.script.main(), 0)
        text = out_path.read_text(encoding="utf-8")
        self.assertIn("Do not edit", text)
        self.assertIn(str(main_path), text)
        self.assertIn("$-0.0417$", text)

    def test_cli_refuses_an_ablation_without_a_family(self):
        main_path = self.root / "main.json"
        main_path.write_text(json.dumps(self.main_summary()), encoding="utf-8")
        argv = ["render_holdout_table.py", "--summary", str(main_path),
                "--ablation", "no-equals-sign",
                "--out", str(self.root / "out.tex")]
        with mock.patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.script.main(), 1)

    def test_no_stray_escapes_reach_the_latex(self):
        # A raw string holding \' would emit a backslash into the caption.
        out = self.script.render(self.main_summary(), self.ablations())
        self.assertNotIn(r"\'", out)


if __name__ == "__main__":
    unittest.main()
