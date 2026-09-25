import importlib.util
import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "benchmarks" / "requests_dev.jsonl"
TEST = ROOT / "benchmarks" / "requests_test.jsonl"
SCHEMA = ROOT / "benchmarks" / "schema.json"
EVALUATOR = ROOT / "scripts" / "evaluate_agent.py"


def evaluator_module():
    spec = importlib.util.spec_from_file_location("evaluate_agent", EVALUATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RequestBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evaluator = evaluator_module()
        cls.dev = cls.evaluator.load_jsonl(DEV)
        cls.test = cls.evaluator.load_jsonl(TEST)

    def test_artifacts_are_valid_and_splits_are_separate(self):
        self.evaluator.validate_split(self.dev, "dev")
        self.evaluator.validate_split(self.test, "test")
        dev_templates = {item["template_id"] for item in self.dev}
        test_templates = {item["template_id"] for item in self.test}
        self.assertTrue(dev_templates.isdisjoint(test_templates))
        self.assertTrue({item["request_id"] for item in self.dev}.isdisjoint(
            {item["request_id"] for item in self.test}
        ))
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])

    def test_every_semantic_request_has_multiple_paraphrases(self):
        for split in (self.dev, self.test):
            counts = Counter(item["paraphrase_group_id"] for item in split)
            self.assertTrue(all(count >= 2 for count in counts.values()))

    def test_scope_control_categories_exist_in_both_splits(self):
        for split in (self.dev, self.test):
            categories = {item["category"] for item in split}
            self.assertIn("unsupported_energy", categories)
            self.assertIn("unsupported_digital_twin", categories)
            self.assertIn("missing_information", categories)

    def test_perfect_offline_predictions_score_perfectly(self):
        predictions = [perfect_prediction(item) for item in self.dev]
        metrics = self.evaluator.evaluate(self.dev, predictions)
        for name in (
            "coverage", "field_exact_match", "action_accuracy", "tool_call_validity",
            "task_completion", "schedule_validity", "paraphrase_consistency",
        ):
            self.assertEqual(metrics[name], 1.0, name)
        self.assertEqual(metrics["false_acceptance_count"], 0)
        self.assertEqual(metrics["average_retry_count"], 0)
        self.assertEqual(metrics["overhead"]["model_calls"], len(self.dev))
        self.assertFalse(metrics["evaluation_policy"]["prompt_tuning_supported"])

    def test_false_acceptance_is_counted(self):
        predictions = [perfect_prediction(item) for item in self.dev]
        unsupported_index = next(
            index for index, item in enumerate(self.dev) if item["gold_action"] == "UNSUPPORTED"
        )
        predictions[unsupported_index].update({
            "action": "EXECUTE", "task_completed": True, "schedule_valid": True,
            "validation_certificate": passing_certificate(),
        })
        metrics = self.evaluator.evaluate(self.dev, predictions)
        self.assertEqual(metrics["false_acceptance_count"], 1)
        self.assertLess(metrics["action_accuracy"], 1.0)

    def test_paraphrase_inconsistency_is_detected(self):
        predictions = [perfect_prediction(item) for item in self.test]
        predictions[1]["action"] = "CLARIFY"
        metrics = self.evaluator.evaluate(self.test, predictions)
        self.assertLess(metrics["paraphrase_consistency"], 1.0)
        self.assertTrue(metrics["evaluation_policy"]["frozen_test_set"])


def passing_certificate():
    return {
        "certificate_format": "agentic_anex.validation_certificate.v1",
        "valid": True,
        "violations": [],
    }


def perfect_prediction(item):
    execute = item["gold_action"] == "EXECUTE"
    return {
        "request_id": item["request_id"],
        "action": item["gold_action"],
        "structured_request": item["gold_structured_request"],
        "tool_calls": item["expected_tool_calls"],
        "task_completed": execute,
        "schedule_valid": True if execute else None,
        "validation_certificate": passing_certificate() if execute else None,
        "clarification_fields": item["clarification_fields"],
        "error_code": item["expected_error"],
        "retry_count": 0,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "model_calls": 1,
    }


if __name__ == "__main__":
    unittest.main()
