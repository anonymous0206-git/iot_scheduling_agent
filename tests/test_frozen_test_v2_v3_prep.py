import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from frozen_test_v2 import cli, schemas
from frozen_test_v2.blinding import REMOVED_GROUP_KEYS, blind_benchmark, leaked_keys
from frozen_test_v2.documents import canonical_json
from frozen_test_v2_fixtures import make_benchmark, standard_groups


def run_cli(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(argv)
    return code, json.loads(out.getvalue())


class BlindingTests(unittest.TestCase):
    def setUp(self):
        self.doc = make_benchmark("a", standard_groups("a"))
        for group in self.doc["groups"]:
            group["protocol_category"] = {
                "EXECUTE": "supported_configured", "CLARIFY": "missing_information",
                "REJECT": "invalid_parameter", "UNSUPPORTED": "unsupported_digital_twin_or_sync",
            }[group["proposed_gold_action"]]

    def test_blind_copy_keeps_only_ids_and_texts(self):
        blinded = blind_benchmark(self.doc)
        self.assertTrue(blinded["blinded"])
        self.assertEqual(blinded["batch_id"], self.doc["batch_id"])
        self.assertEqual(len(blinded["groups"]), 4)
        self.assertEqual(blinded["self_check"], {"group_count": 4, "item_count": 8})
        self.assertEqual(leaked_keys(blinded), [])
        self.assertEqual(set(blinded), {"benchmark_version", "batch_id", "generator_role",
                                        "blinded", "groups", "self_check"})
        for original, group in zip(self.doc["groups"], blinded["groups"]):
            self.assertEqual(set(group), {"semantic_group_id", "paraphrases"})
            self.assertEqual(group["semantic_group_id"], original["semantic_group_id"])
            self.assertEqual([p["request_text"] for p in group["paraphrases"]],
                             [p["request_text"] for p in original["paraphrases"]])
            for paraphrase in group["paraphrases"]:
                self.assertEqual(set(paraphrase), {"request_id", "request_text"})
        self.assertTrue(leaked_keys(self.doc))

    def test_malformed_batches_are_rejected(self):
        with self.assertRaises(ValueError):
            blind_benchmark({"groups": "nope"})
        broken = make_benchmark("a", standard_groups("a"))
        del broken["groups"][0]["paraphrases"][0]["request_text"]
        with self.assertRaises(ValueError):
            blind_benchmark(broken)

    def test_cli_blind_writes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "batch.json"
            source.write_text(canonical_json(self.doc), encoding="utf-8")
            target = Path(tmp) / "blind" / "batch_blind.json"
            code, payload = run_cli(["blind", "--benchmark", str(source), "--out", str(target)])
            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["groups"], 4)
            text = target.read_text(encoding="utf-8")
            for key in REMOVED_GROUP_KEYS:
                self.assertNotIn(f'"{key}"', text)
            self.assertEqual(leaked_keys(json.loads(text)), [])
            code, payload = run_cli(["blind", "--benchmark", str(source), "--out", str(target)])
            self.assertEqual(code, 1)
            self.assertEqual(payload["status"], "refused")


class ProtocolCategoryTests(unittest.TestCase):
    def setUp(self):
        self.doc = make_benchmark("a", standard_groups("a"))

    def test_consistent_categories_are_accepted(self):
        mapping = {"EXECUTE": "supported_default", "CLARIFY": "missing_information",
                   "REJECT": "invalid_parameter", "UNSUPPORTED": "unsupported_periodic"}
        for group in self.doc["groups"]:
            group["protocol_category"] = mapping[group["proposed_gold_action"]]
        self.doc["self_check"]["protocol_category_counts"] = {
            "supported_default": 1, "missing_information": 1,
            "invalid_parameter": 1, "unsupported_periodic": 1}
        result = schemas.validate_benchmark(self.doc)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.group_defects, {})
        self.assertEqual(result.warnings, [])

    def test_inconsistent_or_unknown_categories_are_defects(self):
        self.doc["groups"][0]["protocol_category"] = "missing_information"
        self.doc["groups"][1]["protocol_category"] = "not_a_category"
        result = schemas.validate_benchmark(self.doc)
        self.assertTrue(any("implies CLARIFY" in d for d in result.group_defects["syn-a-001"]))
        self.assertTrue(any("not one of" in d for d in result.group_defects["syn-a-002"]))

    def test_declared_category_counts_are_checked(self):
        self.doc["groups"][0]["protocol_category"] = "supported_default"
        self.doc["self_check"]["protocol_category_counts"] = {"supported_default": 2}
        result = schemas.validate_benchmark(self.doc)
        self.assertTrue(any("protocol_category_counts.supported_default" in w
                            for w in result.warnings))


if __name__ == "__main__":
    unittest.main()
