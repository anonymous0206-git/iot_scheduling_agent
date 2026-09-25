import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reissue_evaluation_lock.py"


def load_script():
    spec = importlib.util.spec_from_file_location("reissue_evaluation_lock", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ReissueLockTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        self.tracked = self.root / "src" / "pipeline.py"
        self.tracked.write_text("original\n", encoding="utf-8")
        self.stable = self.root / "src" / "stable.py"
        self.stable.write_text("unchanged\n", encoding="utf-8")
        self.base = self.root / "lock_v1.json"
        self.base.write_text(json.dumps({
            "lock_format": "agentic_anex.evaluation_lock.v3",
            "status": "OLD_STATUS",
            "locked_at": "2026-09-14",
            "runtime": {"temperature": 0.0, "seeds": [0]},
            "sha256": {
                "src/pipeline.py": self.digest("original\n"),
                "src/stable.py": self.digest("unchanged\n"),
            },
        }, indent=2), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def digest(text):
        return hashlib.sha256(text.encode()).hexdigest()

    def run_main(self, *argv):
        out = io.StringIO()
        with mock.patch("sys.argv", ["reissue_evaluation_lock.py", *argv]), \
                contextlib.redirect_stdout(out):
            code = self.script.main()
        return code, json.loads(out.getvalue())

    def base_args(self, out_name="lock_v2.json"):
        return ["--base", str(self.base), "--out", str(self.root / out_name),
                "--status", "NEW_STATUS", "--root", str(self.root)]

    def test_records_what_changed_and_what_did_not(self):
        self.tracked.write_text("repaired\n", encoding="utf-8")
        code, payload = self.run_main(*self.base_args(), "--rationale", "fixed a defect")
        self.assertEqual(code, 0)
        self.assertEqual(payload["changed_files"], ["src/pipeline.py"])
        self.assertEqual(payload["unchanged_file_count"], 1)

        lock = json.loads((self.root / "lock_v2.json").read_text(encoding="utf-8"))
        revision = lock["pipeline_revision"]
        self.assertEqual(revision["rationale"], "fixed a defect")
        self.assertEqual(revision["changed_files"]["src/pipeline.py"]["was"],
                         self.digest("original\n"))
        self.assertEqual(revision["changed_files"]["src/pipeline.py"]["now"],
                         self.digest("repaired\n"))
        self.assertEqual(lock["sha256"]["src/stable.py"], self.digest("unchanged\n"))
        self.assertEqual(lock["status"], "NEW_STATUS")

    def test_pins_the_base_lock_by_its_own_hash(self):
        self.tracked.write_text("repaired\n", encoding="utf-8")
        self.run_main(*self.base_args(), "--rationale", "fixed a defect")
        lock = json.loads((self.root / "lock_v2.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["revision_of"]["sha256"],
                         hashlib.sha256(self.base.read_bytes()).hexdigest())
        self.assertEqual(lock["revision_of"]["locked_at"], "2026-09-14")
        self.assertTrue(lock["pipeline_revision"][
            "results_produced_under_the_base_lock_remain_valid_for_that_lock"])

    def test_refuses_without_a_rationale(self):
        self.tracked.write_text("repaired\n", encoding="utf-8")
        code, payload = self.run_main(*self.base_args())
        self.assertEqual(code, 1)
        self.assertIn("written rationale", payload["problems"][0])
        self.assertFalse((self.root / "lock_v2.json").exists())

    def test_refuses_when_nothing_changed(self):
        code, payload = self.run_main(*self.base_args(), "--rationale", "no reason")
        self.assertEqual(code, 1)
        self.assertIn("no covered file changed", payload["problems"][0])

    def test_can_bring_a_previously_uncovered_file_under_the_lock(self):
        """A lock that omits a file cannot detect a change to it, so extending
        coverage has to be possible without any covered file changing."""
        newcomer = self.root / "src" / "client.py"
        newcomer.write_text("new module\n", encoding="utf-8")
        code, payload = self.run_main(*self.base_args(), "--rationale", "widen coverage",
                                      "--add", "src/client.py")
        self.assertEqual(code, 0)
        self.assertEqual(payload["newly_covered_files"], ["src/client.py"])
        self.assertEqual(payload["changed_files"], [])
        lock = json.loads((self.root / "lock_v2.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["sha256"]["src/client.py"], self.digest("new module\n"))
        self.assertEqual(lock["pipeline_revision"]["unchanged_file_count"], 2)

    def test_refuses_to_add_a_file_the_base_lock_already_covers(self):
        code, payload = self.run_main(*self.base_args(), "--rationale", "x",
                                      "--add", "src/stable.py")
        self.assertEqual(code, 1)
        self.assertIn("already covered", payload["problems"][0])

    def test_refuses_to_add_a_file_that_does_not_exist(self):
        code, payload = self.run_main(*self.base_args(), "--rationale", "x",
                                      "--add", "src/nope.py")
        self.assertEqual(code, 1)
        self.assertIn("does not exist", payload["problems"][0])

    def test_refuses_when_a_covered_file_is_missing(self):
        self.tracked.unlink()
        code, payload = self.run_main(*self.base_args(), "--rationale", "x")
        self.assertEqual(code, 1)
        self.assertIn("missing", payload["problems"][0])

    def test_refuses_to_overwrite_an_existing_lock(self):
        self.tracked.write_text("repaired\n", encoding="utf-8")
        (self.root / "lock_v2.json").write_text("{}", encoding="utf-8")
        code, payload = self.run_main(*self.base_args(), "--rationale", "x")
        self.assertEqual(code, 1)
        self.assertIn("refusing to overwrite", payload["problems"][0])

    def test_runtime_overrides_merge_into_the_base_runtime(self):
        self.tracked.write_text("repaired\n", encoding="utf-8")
        overrides = self.root / "runtime.json"
        overrides.write_text(json.dumps({"seeds": [1], "note": "added"}), encoding="utf-8")
        self.run_main(*self.base_args(), "--rationale", "x",
                      "--runtime-json", str(overrides))
        lock = json.loads((self.root / "lock_v2.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["runtime"]["seeds"], [1])
        self.assertEqual(lock["runtime"]["note"], "added")
        self.assertEqual(lock["runtime"]["temperature"], 0.0, "unrelated fields survive")

    def test_rationale_can_come_from_a_file(self):
        self.tracked.write_text("repaired\n", encoding="utf-8")
        note = self.root / "why.txt"
        note.write_text("  a long written explanation  \n", encoding="utf-8")
        self.run_main(*self.base_args(), "--rationale-file", str(note))
        lock = json.loads((self.root / "lock_v2.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["pipeline_revision"]["rationale"],
                         "a long written explanation")


if __name__ == "__main__":
    unittest.main()
