import contextlib
import importlib.util
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render_frozen_test_v3_prompts.py"


def load_script():
    spec = importlib.util.spec_from_file_location("render_frozen_test_v3_prompts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RenderPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()
        cls.rendered = cls.script.render_all(ROOT)

    def test_every_deliverable_is_rendered_without_placeholders(self):
        self.assertEqual(sorted(self.rendered), [
            "frozen_test_v3_generator_A.txt", "frozen_test_v3_generator_B.txt",
            "frozen_test_v3_reviewer_batch_A.txt", "frozen_test_v3_reviewer_batch_B.txt",
            "frozen_test_v3_specification.txt"])
        for name, content in self.rendered.items():
            self.assertEqual(self.script.PLACEHOLDER.findall(content), [], name)
            self.assertTrue(content.endswith("\n"), name)

    def test_generator_prompts_carry_their_own_role(self):
        first = self.rendered["frozen_test_v3_generator_A.txt"]
        second = self.rendered["frozen_test_v3_generator_B.txt"]
        self.assertIn("You are Frontier Benchmark Generator A.", first)
        self.assertIn("frontier-model-a", first)
        self.assertIn("v3-a-001-p1", first)
        self.assertNotIn("frontier-model-b", first)
        self.assertIn("You are Frontier Benchmark Generator B.", second)
        self.assertIn("frontier-model-b", second)
        self.assertNotIn("frontier-model-a", second)
        # The two prompts differ only in the role substitution.
        self.assertEqual(first.replace("Generator A", "Generator B").replace("-a-", "-b-")
                         .replace("frontier-model-a", "frontier-model-b"), second)

    def test_reviewer_prompts_target_one_batch_and_embed_the_specification(self):
        for role in ("A", "B"):
            reviewer = self.rendered[f"frozen_test_v3_reviewer_batch_{role}.txt"]
            self.assertIn(f"blind Batch {role}", reviewer)
            self.assertIn(f"frontier-model-{role.lower()}", reviewer)
            self.assertIn("independent benchmark adjudicator", reviewer)
            self.assertIn(self.rendered["frozen_test_v3_specification.txt"].rstrip(),
                          reviewer)

    def test_specification_holds_sections_one_to_four_only(self):
        specification = self.rendered["frozen_test_v3_specification.txt"]
        for heading in ("1. PAPER-1 SCIENTIFIC SCOPE", "2. ACTION LABELS",
                        "3. AVAILABLE TOPOLOGIES", "4. VALID CONFIGURATION CONTRACT"):
            self.assertIn(heading, specification)
        for heading in ("5. GENERATION TASK", "6. OUTPUT SCHEMA"):
            self.assertNotIn(heading, specification)
        self.assertIn("interference_ratio", specification)
        self.assertIn("legacy30_seed7", specification)
        self.assertIn("topo300_seed0", specification)
        self.assertNotIn("protocol_category_counts", specification)

    def test_render_rejects_leftover_placeholders_and_broken_templates(self):
        with self.assertRaises(self.script.RenderError):
            self.script.render("keep {BATCH} unsubstituted", {"{ROLE}": "A"})
        self.assertEqual(self.script.render("plain {json: 1}", {}), "plain {json: 1}")
        with self.assertRaises(self.script.RenderError):
            self.script.extract_specification("no markers here")

    def test_cli_writes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "delivered"
            argv = ["render_frozen_test_v3_prompts.py", "--output-dir", str(out),
                    "--project-root", str(ROOT)]
            stdout = io.StringIO()
            with mock.patch("sys.argv", argv), contextlib.redirect_stdout(stdout):
                self.assertEqual(self.script.main(), 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "rendered")
            self.assertEqual(sorted(payload["files"]), sorted(self.rendered))
            for name, content in self.rendered.items():
                self.assertEqual((out / name).read_text(encoding="utf-8"), content)
            with mock.patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.script.main(), 1)


if __name__ == "__main__":
    unittest.main()
