import contextlib
import importlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_scope_gate_ablation.py"

UNSUPPORTED_TEXT = "Build a Digital Twin of topo50_seed0 and emulate the collection inside it."


def load_script():
    spec = importlib.util.spec_from_file_location("run_scope_gate_ablation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScopeGateAblationTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_gate_itself_is_unchanged_by_any_mode(self):
        """Only the gate's authority moves between arms; the detector is one detector."""
        from agentic_anex.scope_policy import evaluate_scope_policy
        real = evaluate_scope_policy(UNSUPPORTED_TEXT)
        self.assertFalse(real.supported)
        self.assertTrue(real.violations)
        self.assertEqual(real.policy_version, "paper1-scope-policy.v2")

    def test_each_mode_has_its_own_arm_name(self):
        from agentic_anex.experiments import SCOPE_MODE_SYSTEM_NAMES
        self.assertEqual(self.script.ABLATION_SYSTEM_NAME, "llm_agent_no_scope_gate")
        self.assertEqual(self.script.ADVISORY_SYSTEM_NAME, "llm_agent_advisory_scope_gate")
        self.assertEqual(len(set(SCOPE_MODE_SYSTEM_NAMES.values())), 3)
        self.assertNotIn("llm_agent", (self.script.ABLATION_SYSTEM_NAME,
                                       self.script.ADVISORY_SYSTEM_NAME))

    def test_the_primary_arm_cannot_be_run_from_this_script(self):
        """A runner that can produce the production arm can mislabel one."""
        ledger = self.root / "primary.jsonl"
        with self.assertRaises(SystemExit):
            self.run_main(*self.base_args(ledger), "--confirm-ablation",
                          "--scope-mode", "enforcing")

    def run_main(self, *argv):
        out = io.StringIO()
        with mock.patch("sys.argv", ["run_scope_gate_ablation.py", *argv]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = self.script.main()
        return code, json.loads(out.getvalue())

    def base_args(self, ledger):
        catalogue = self.root / "catalogue.json"
        catalogue.write_text(json.dumps({"topo50_seed0": {"path": "x.json"}}), encoding="utf-8")
        benchmark = self.root / "benchmark.jsonl"
        benchmark.write_text("", encoding="utf-8")
        return ["--benchmark", str(benchmark), "--topology-catalogue", str(catalogue),
                "--raw-output", str(ledger), "--provider", "ollama", "--model", "phi4:14b"]

    def test_runner_refuses_without_confirmation(self):
        ledger = self.root / "ablation.jsonl"
        code, payload = self.run_main(*self.base_args(ledger))
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "refused")
        self.assertTrue(any("--confirm-ablation" in p for p in payload["problems"]))
        self.assertFalse(ledger.exists())

    def test_runner_refuses_to_append_into_an_existing_ledger(self):
        ledger = self.root / "existing.jsonl"
        ledger.write_text("{}\n", encoding="utf-8")
        code, payload = self.run_main(*self.base_args(ledger), "--confirm-ablation")
        self.assertEqual(code, 1)
        self.assertTrue(any("existing ledger" in p for p in payload["problems"]))

    def test_advisory_mode_is_refused_without_confirmation_too(self):
        ledger = self.root / "advisory.jsonl"
        code, payload = self.run_main(*self.base_args(ledger), "--scope-mode", "advisory")
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "refused")
        self.assertFalse(ledger.exists())


if __name__ == "__main__":
    unittest.main()
