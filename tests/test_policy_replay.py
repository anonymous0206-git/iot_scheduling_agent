import json
import tempfile
import unittest
from pathlib import Path

from agentic_anex.policy_replay import REPLAY_FORMAT, evaluate_v1_scope, replay_files


class PolicyReplayTests(unittest.TestCase):
    def test_v1_replay_reproduces_flat_phrase_behavior(self):
        self.assertFalse(evaluate_v1_scope("Build a Digital Twin.")["supported"])
        self.assertFalse(evaluate_v1_scope("Optimize sensor energy consumption.")["supported"])
        self.assertTrue(evaluate_v1_scope(
            "Stream measurements into a persistent virtual network replica."
        )["supported"])

    def test_locked_24_record_replay_is_retrospective_and_blocks_dt02(self):
        artifact = replay_files(
            Path("benchmarks/requests_test.jsonl"),
            Path("results/phi4_reasoning_test_locked_v1_wsl.jsonl"),
        )
        self.assertEqual(artifact["artifact_format"], REPLAY_FORMAT)
        self.assertIn("retrospective/regression", artifact["classification"])
        self.assertEqual(len(artifact["records"]), 24)
        self.assertFalse(artifact["execution"]["llm_called"])
        self.assertFalse(artifact["execution"]["scientific_tools_called"])
        reasoning = next(row for row in artifact["records"]
                         if row["request_id"] == "test-dt-02"
                         and row["model"] == "phi4-reasoning:14b")
        self.assertEqual(reasoning["locked_action"], "EXECUTE")
        self.assertEqual(reasoning["policy_v1"]["outcome"]["action"], "EXECUTE")
        self.assertEqual(reasoning["policy_v2"]["outcome"]["action"], "UNSUPPORTED")
        self.assertTrue(reasoning["policy_v2"]["outcome"]["blocked_before_model"])
        self.assertEqual(reasoning["policy_v2"]["outcome"]["model_calls"], 0)
        self.assertEqual(reasoning["policy_v2"]["outcome"]["tool_calls"], 0)

    def test_policy_v2_does_not_overblock_locked_supported_cases(self):
        artifact = replay_files(
            Path("benchmarks/requests_test.jsonl"),
            Path("results/phi4_reasoning_test_locked_v1_wsl.jsonl"),
        )
        self.assertEqual(artifact["summary"]["policy_v2"]["supported_overblock_count"], 0)
        for row in artifact["records"]:
            if row["gold_action"] == "EXECUTE":
                self.assertTrue(row["policy_v2"]["scope"]["supported"])

    def test_cli_refuses_to_overwrite(self):
        from scripts.replay_locked_policy import main

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "replay.json"
            argv = [
                "replay_locked_policy.py", "--benchmark", "benchmarks/requests_test.jsonl",
                "--raw", "results/phi4_reasoning_test_locked_v1_wsl.jsonl",
                "--output", str(output),
            ]
            from unittest.mock import patch
            with patch("sys.argv", argv):
                main()
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(document["artifact_format"], REPLAY_FORMAT)
            with patch("sys.argv", argv), self.assertRaises(FileExistsError):
                main()


if __name__ == "__main__":
    unittest.main()
