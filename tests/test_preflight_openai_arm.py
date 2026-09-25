import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "preflight_openai_arm.py"

SECRET = "sk-do-not-print-me-0123456789"


def load_script():
    spec = importlib.util.spec_from_file_location("preflight_openai_arm", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()

    def run_main(self, *argv, env=None):
        out = io.StringIO()
        with mock.patch("sys.argv", ["preflight_openai_arm.py", *argv]), \
                mock.patch.dict("os.environ", env or {}, clear=True), \
                contextlib.redirect_stdout(out):
            code = self.script.main()
        return code, out.getvalue()

    def test_refuses_and_explains_when_the_key_is_not_set(self):
        code, raw = self.run_main("--model", "some-model", env={})
        payload = json.loads(raw)
        self.assertEqual(code, 1)
        self.assertFalse(payload["api_key_set"])
        self.assertEqual(payload["api_key_length"], 0)
        self.assertIn("~/.profile", payload["problems"][0])

    def test_never_prints_the_key(self):
        probe = {"ok": True, "structured_output_mode": "json_schema"}
        with mock.patch.object(self.script, "probe", return_value=probe):
            code, raw = self.run_main("--model", "some-model",
                                      env={"OPENAI_API_KEY": SECRET})
        self.assertEqual(code, 0)
        self.assertNotIn(SECRET, raw)
        payload = json.loads(raw)
        self.assertTrue(payload["api_key_set"])
        self.assertEqual(payload["api_key_length"], len(SECRET))

    def test_reports_a_json_object_fallback_as_not_strict(self):
        probe = {"ok": True, "structured_output_mode": "json_object",
                 "strict_json_schema_supported": False}
        with mock.patch.object(self.script, "probe", return_value=probe):
            code, raw = self.run_main("--model", "some-model",
                                      env={"OPENAI_API_KEY": SECRET})
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(raw)["probe"]["strict_json_schema_supported"])

    def test_a_failed_probe_is_a_nonzero_exit(self):
        probe = {"ok": False, "stage": "generate_structured", "error": "400 temperature"}
        with mock.patch.object(self.script, "probe", return_value=probe):
            code, raw = self.run_main("--model", "some-model",
                                      env={"OPENAI_API_KEY": SECRET})
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(raw)["probe"]["stage"], "generate_structured")

    def test_probe_reports_client_construction_failure_without_raising(self):
        from agentic_anex.llm_clients.base import LLMClientError
        with mock.patch.object(self.script, "create_llm_client",
                               side_effect=LLMClientError("no key", code="MISSING_API_KEY")):
            result = self.script.probe(self.script.ProviderConfig(
                provider="openai", model="m", api_key_env="OPENAI_API_KEY"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "client_construction")
        self.assertEqual(result["code"], "MISSING_API_KEY")

    def test_model_listing_filters_and_survives_an_http_error(self):
        import urllib.error
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.HTTPError("u", 401, "no", {}, None)):
            self.assertEqual(self.script.list_models("https://x/v1", SECRET, None, 5),
                             "HTTP 401 listing models")

        payload = json.dumps({"data": [{"id": "gpt-x"}, {"id": "other"}]}).encode()
        response = mock.MagicMock()
        response.read.return_value = payload
        response.__enter__.return_value = response
        with mock.patch("urllib.request.urlopen", return_value=response):
            self.assertEqual(self.script.list_models("https://x/v1", SECRET, "gpt", 5),
                             ["gpt-x"])

    def test_openai_compatible_requires_a_base_url(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_main("--provider", "openai_compatible", "--model", "m",
                          env={"OPENAI_API_KEY": SECRET})


if __name__ == "__main__":
    unittest.main()
