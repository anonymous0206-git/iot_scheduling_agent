"""The device check has to fail loudly, because the failure it guards is silent.

When Ollama's GPU discovery times out the server does not error: it reports no
VRAM and serves on CPU at a fraction of the token rate, so every answer is
still correct and only the timings are ruined. These tests pin the one
behaviour that matters --- a CPU-served model makes the preflight exit
non-zero --- and the provenance fields the paper has to quote.
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
SCRIPT = ROOT / "scripts" / "preflight_ollama_arm.py"

GPU_ENTRY = {
    "name": "phi4:14b", "model": "phi4:14b", "size": 10_000_000_000,
    "size_vram": 10_000_000_000, "digest": "ac896e5b", "context_length": 4096,
    "details": {"parameter_size": "14.7B", "quantization_level": "Q4_K_M"},
}
CPU_ENTRY = {**GPU_ENTRY, "size_vram": 0}
SPLIT_ENTRY = {**GPU_ENTRY, "size_vram": 6_000_000_000}


def load_script():
    spec = importlib.util.spec_from_file_location("preflight_ollama_arm", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DescribeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def describe_with(self, entry):
        def fake_get(host, path, timeout):
            if path == "/api/version":
                return {"version": "0.34.0"}
            return {"models": [entry] if entry else []}
        with mock.patch.object(self.script, "_get", fake_get):
            return self.script.describe("http://h", "phi4:14b", 5)

    def test_a_fully_resident_model_reads_as_gpu(self):
        report = self.describe_with(GPU_ENTRY)
        self.assertEqual(report["serving_device"], "gpu")
        self.assertEqual(report["vram_fraction"], 1.0)

    def test_a_model_with_no_vram_reads_as_cpu(self):
        report = self.describe_with(CPU_ENTRY)
        self.assertEqual(report["serving_device"], "cpu")
        self.assertEqual(report["vram_fraction"], 0.0)

    def test_a_partly_offloaded_model_is_neither(self):
        """A split load is not a GPU run and must not be reported as one."""
        report = self.describe_with(SPLIT_ENTRY)
        self.assertEqual(report["serving_device"], "split")
        self.assertEqual(report["vram_fraction"], 0.6)

    def test_the_provenance_the_paper_has_to_quote_is_captured(self):
        report = self.describe_with(GPU_ENTRY)
        # a tag is mutable; these are what identify the run
        self.assertEqual(report["digest"], "ac896e5b")
        self.assertEqual(report["quantization_level"], "Q4_K_M")
        self.assertEqual(report["parameter_size"], "14.7B")
        self.assertEqual(report["server_version"], "0.34.0")
        self.assertEqual(report["context_length"], 4096)

    def test_a_model_that_will_not_load_is_an_error_not_a_verdict(self):
        with mock.patch.object(self.script, "_get",
                               lambda host, path, timeout: {"models": []}
                               if path == "/api/ps" else {"version": "0.34.0"}), \
                mock.patch.object(self.script, "_post", lambda *a, **k: {}):
            with self.assertRaises(self.script.PreflightError):
                self.script.describe("http://h", "phi4:14b", 5)


class ExitStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_main(self, report, *extra):
        argv = ["preflight_ollama_arm.py", "--model", "phi4:14b", *extra]
        out = io.StringIO()
        with mock.patch.object(self.script, "describe", lambda *a, **k: dict(report)), \
                mock.patch("sys.argv", argv), contextlib.redirect_stdout(out):
            code = self.script.main()
        return code, json.loads(out.getvalue())

    def base(self, device, fraction):
        return {"serving_device": device, "vram_fraction": fraction, "model": "phi4:14b",
                "size_bytes": 10_000_000_000}

    def test_gpu_passes(self):
        code, payload = self.run_main(self.base("gpu", 1.0))
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "ready")

    def test_cpu_fails(self):
        code, payload = self.run_main(self.base("cpu", 0.0))
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "refused")
        self.assertIn("not comparable", payload["problems"][0])

    def test_split_fails_too(self):
        code, _ = self.run_main(self.base("split", 0.6))
        self.assertEqual(code, 1)

    def test_allow_cpu_passes_but_says_so(self):
        """A deliberate CPU run must stay distinguishable from an accidental one."""
        code, payload = self.run_main(self.base("cpu", 0.0), "--allow-cpu")
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "ready")
        self.assertIn("do not compare these timings", payload["warning"])

    def test_the_report_is_written_where_it_can_be_kept_with_the_ledger(self):
        out = self.root / "run.device.json"
        code, _ = self.run_main(self.base("gpu", 1.0), "--json-out", str(out))
        self.assertEqual(code, 0)
        saved = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(saved["serving_device"], "gpu")


if __name__ == "__main__":
    unittest.main()
