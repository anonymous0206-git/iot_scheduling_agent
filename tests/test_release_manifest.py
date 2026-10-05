"""The release manifest must not be able to explain away a change silently.

A lock is never edited, so every lock older than the pipeline disagrees with it,
and the manifest is what distinguishes an expected disagreement from an
unexplained one. That only holds if the manifest cannot be written while its
declarations and the tree disagree --- in either direction. These tests are that
property, plus the checks the verifier owes a reader: a released file that no
longer matches, and a lock that has been rewritten behind the manifest.
"""

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
BUILD = ROOT / "scripts" / "build_release_manifest.py"
VERIFY = ROOT / "scripts" / "verify_release_manifest.py"


def load_script(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.build = load_script(BUILD, "build_release_manifest")
        self.verify = load_script(VERIFY, "verify_release_manifest")
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        # One file that moved on since the lock, one that did not.
        (self.root / "src" / "pipeline.py").write_text("repaired\n", encoding="utf-8")
        (self.root / "src" / "stable.py").write_text("unchanged\n", encoding="utf-8")
        self.lock = self.root / "lock_v1.json"
        self.lock.write_text(json.dumps({
            "lock_format": "agentic_anex.evaluation_lock.v3",
            "status": "SEALED",
            "locked_at": "2026-09-14",
            "sha256": {
                "src/pipeline.py": digest("original\n"),
                "src/stable.py": digest("unchanged\n"),
            },
        }, indent=2), encoding="utf-8")
        self.out = self.root / "release_manifest.json"
        self.declaration = {
            "src/pipeline.py": {
                "revision": "2026-09-21, the repair",
                "reason": "The repair of Section 5.5.",
                "superseded_by": None,
            },
        }

    def tearDown(self):
        self._tmp.cleanup()

    @contextlib.contextmanager
    def patched(self, divergences=None, include=("src/*.py", "lock_v1.json")):
        divergences = self.declaration if divergences is None else divergences
        with mock.patch.object(self.build, "LOCK_CHAIN", ("lock_v1.json",)), \
             mock.patch.object(self.build, "DIVERGENCES", divergences), \
             mock.patch.object(self.build.sys.modules["build_supplementary"],
                               "INCLUDE", include):
            yield

    def built(self, **kwargs):
        with self.patched(**kwargs):
            return self.build.build(self.root, self.out)

    def write(self, manifest):
        self.out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")

    def verified(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), \
             mock.patch("sys.argv", ["verify", "--manifest", str(self.out),
                                     "--root", str(self.root)]):
            code = self.verify.main()
        return code, json.loads(buffer.getvalue())

    # -- building -----------------------------------------------------------

    def test_declared_divergence_is_recorded_with_both_hashes(self):
        manifest = self.built()
        entry = manifest["divergences_from_the_lock_chain"]["src/pipeline.py"]
        self.assertEqual(entry["state"], "changed")
        self.assertEqual(entry["current_sha256"], digest("repaired\n"))
        self.assertEqual(entry["diverges_from"]["lock_v1.json"]["locked_sha256"],
                         digest("original\n"))
        self.assertEqual(entry["diverges_from"]["lock_v1.json"]["lock_issued"],
                         "2026-09-14")
        self.assertEqual(manifest["files_pinned_by_this_manifest_alone"],
                         ["src/pipeline.py"])
        # The unchanged file is pinned but is not a divergence.
        self.assertIn("src/stable.py", manifest["sha256"])
        self.assertNotIn("src/stable.py", manifest["divergences_from_the_lock_chain"])

    def test_an_undeclared_divergence_refuses_the_build(self):
        with self.assertRaises(self.build.ManifestError) as caught:
            self.built(divergences={})
        self.assertIn("src/pipeline.py", str(caught.exception))
        self.assertIn("no divergence is declared", str(caught.exception))

    def test_a_declaration_that_is_no_longer_true_refuses_the_build(self):
        stale = dict(self.declaration)
        stale["src/stable.py"] = {"revision": "never", "reason": "stale",
                                  "superseded_by": None}
        with self.assertRaises(self.build.ManifestError) as caught:
            self.built(divergences=stale)
        self.assertIn("src/stable.py", str(caught.exception))
        self.assertIn("stale declaration", str(caught.exception))

    def test_a_superseding_lock_that_does_not_pin_the_bytes_refuses_the_build(self):
        wrong = {"src/pipeline.py": {**self.declaration["src/pipeline.py"],
                                     "superseded_by": "lock_v1.json"}}
        with self.assertRaises(self.build.ManifestError) as caught:
            self.built(divergences=wrong)
        self.assertIn("pins its current bytes", str(caught.exception))

    def test_a_missing_file_is_declared_as_absent(self):
        (self.root / "src" / "pipeline.py").unlink()
        manifest = self.built()
        entry = manifest["divergences_from_the_lock_chain"]["src/pipeline.py"]
        self.assertEqual(entry["state"], "absent")
        self.assertIsNone(entry["current_sha256"])
        self.assertFalse(entry["released"])

    def test_the_manifest_does_not_pin_itself(self):
        self.write(self.built())
        manifest = self.built()
        self.assertEqual(manifest["self"], "release_manifest.json")
        self.assertNotIn("release_manifest.json", manifest["sha256"])

    # -- verifying ----------------------------------------------------------

    def test_a_clean_release_verifies(self):
        self.write(self.built())
        code, report = self.verified()
        self.assertEqual(code, 0)
        self.assertTrue(report["valid"])
        self.assertEqual(report["released_files_that_do_not_match"], [])
        self.assertEqual(report["undeclared_divergences"], [])

    def test_a_released_file_that_changed_fails_verification(self):
        self.write(self.built())
        (self.root / "src" / "stable.py").write_text("tampered\n", encoding="utf-8")
        code, report = self.verified()
        self.assertEqual(code, 1)
        self.assertFalse(report["valid"])
        self.assertEqual([failure["path"] for failure
                          in report["released_files_that_do_not_match"]],
                         ["src/stable.py"])

    def test_a_lock_edited_behind_the_manifest_fails_verification(self):
        self.write(self.built())
        lock = json.loads(self.lock.read_text(encoding="utf-8"))
        # The thing a lock must never do: move to agree with the tree.
        lock["sha256"]["src/pipeline.py"] = digest("repaired\n")
        self.lock.write_text(json.dumps(lock, indent=2), encoding="utf-8")
        code, report = self.verified()
        self.assertEqual(code, 1)
        self.assertEqual([failure["lock"] for failure
                          in report["locks_that_have_been_edited"]],
                         ["lock_v1.json"])

    def test_an_undeclared_divergence_fails_verification(self):
        self.write(self.built())
        manifest = json.loads(self.out.read_text(encoding="utf-8"))
        del manifest["divergences_from_the_lock_chain"]["src/pipeline.py"]
        self.write(manifest)
        code, report = self.verified()
        self.assertEqual(code, 1)
        self.assertEqual([entry["path"] for entry
                          in report["undeclared_divergences"]],
                         ["src/pipeline.py"])

    def test_a_declaration_without_a_divergence_fails_verification(self):
        self.write(self.built())
        manifest = json.loads(self.out.read_text(encoding="utf-8"))
        manifest["divergences_from_the_lock_chain"]["src/stable.py"] = {
            "state": "changed", "current_sha256": digest("unchanged\n"),
            "released": True, "diverges_from": {}, "revision": "never",
            "reason": "stale", "superseded_by": None}
        self.write(manifest)
        code, report = self.verified()
        self.assertEqual(code, 1)
        self.assertEqual(report["declarations_no_longer_real"], ["src/stable.py"])


class ReleasedArtefactTests(unittest.TestCase):
    """The manifest this repository actually ships has to verify."""

    def test_the_shipped_release_manifest_verifies(self):
        manifest = ROOT / "benchmarks" / "release_manifest_v5.json"
        if not manifest.is_file():
            self.skipTest("no release manifest in this checkout")
        verify = load_script(VERIFY, "verify_release_manifest")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), \
             mock.patch("sys.argv", ["verify", "--manifest", str(manifest)]):
            code = verify.main()
        report = json.loads(buffer.getvalue())
        self.assertTrue(report["valid"], report)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
