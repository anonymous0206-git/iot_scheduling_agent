import json
import tempfile
import unittest
from pathlib import Path

from frozen_test_v2 import contract, documents, schemas
from frozen_test_v2_fixtures import (
    exclude_decision,
    execute_fields,
    keep_decision,
    make_benchmark,
    make_decisions,
    make_review,
    make_review_entry,
    standard_groups,
)


class ContractTests(unittest.TestCase):
    def test_values_equal_keeps_booleans_distinct(self):
        self.assertFalse(contract.values_equal(True, 1))
        self.assertFalse(contract.values_equal(1, True))
        self.assertTrue(contract.values_equal(18, 18.0))
        self.assertTrue(contract.values_equal({"a": None, "b": [1, 2.0]},
                                              {"a": None, "b": [1.0, 2]}))
        self.assertFalse(contract.values_equal({"a": 1}, {"a": 1, "b": 2}))

    def test_field_violations_follow_the_contract(self):
        violations = contract.field_violations(execute_fields(
            channels=0, interference_ratio=0.5, collision_model="sinr",
            latency_target_slots=2.5, seed=-1, working_period=12, communication_range=25.0))
        self.assertEqual(set(violations), {
            "channels", "interference_ratio", "collision_model", "latency_target_slots",
            "seed", "working_period", "communication_range",
        })
        self.assertEqual(contract.field_violations(execute_fields()), {})
        self.assertIn("topology_id", contract.field_violations({"topology_id": "legacy50_seed3"}))
        self.assertIn("channels", contract.field_violations({"channels": True}))
        self.assertIn("interference_ratio",
                      contract.field_violations({"interference_ratio": float("nan")}))
        self.assertIn("latency_target_slots",
                      contract.field_violations({"latency_target_slots": True}))
        self.assertEqual(contract.field_violations({"latency_target_slots": None, "seed": 0}), {})

    def test_execute_configuration_requires_completeness(self):
        problems = contract.execute_configuration_problems({"topology_id": "legacy30_seed7"})
        self.assertTrue(any("missing field channels" in problem for problem in problems))
        self.assertEqual(contract.execute_configuration_problems(execute_fields()), [])
        self.assertTrue(contract.execute_configuration_problems(None))
        self.assertTrue(any("unknown fields" in problem for problem in
                            contract.execute_configuration_problems(execute_fields(extra=1))))

    def test_unconfirmed_invalid_fields(self):
        claimed = {"channels": {"observed": 3, "reason": "claimed invalid"}}
        self.assertEqual(contract.unconfirmed_invalid_fields(execute_fields(), claimed),
                         ["channels"])
        real = {"channels": {"observed": 0, "reason": "zero"}}
        self.assertEqual(contract.unconfirmed_invalid_fields(execute_fields(channels=0), real),
                         [])
        contradiction = {"channels": {"observed": {"simultaneous": [2, 3]},
                                      "reason": "contradiction"}}
        self.assertEqual(contract.unconfirmed_invalid_fields(
            {"topology_id": "legacy30_seed7"}, contradiction), [])
        foreign = {"colour": {"observed": "red", "reason": "not a field"}}
        self.assertEqual(contract.unconfirmed_invalid_fields({}, foreign), ["colour"])


class DocumentTests(unittest.TestCase):
    def test_strict_parse_rejects_leading_prose(self):
        with self.assertRaises(documents.DocumentFormatError):
            documents.parse_json_payload("Some prose first.\n{\"a\": 1}\n")

    def test_tolerant_parse_records_the_defect(self):
        value, payload, defects = documents.parse_json_payload(
            "I wrote this first.\n{\"a\": {\"b\": [1, 2]}}\n", tolerate_leading_prose=True)
        self.assertEqual(value, {"a": {"b": [1, 2]}})
        self.assertEqual(payload, '{"a": {"b": [1, 2]}}')
        self.assertEqual(len(defects), 1)
        self.assertEqual(defects[0].kind, "leading_prose")
        self.assertEqual(defects[0].byte_offset, len("I wrote this first.\n"))

    def test_clean_json_has_no_defects(self):
        value, payload, defects = documents.parse_json_payload('{"a": 1}',
                                                              tolerate_leading_prose=True)
        self.assertEqual(value, {"a": 1})
        self.assertEqual(defects, ())

    def test_trailing_content_is_refused(self):
        with self.assertRaises(documents.DocumentFormatError):
            documents.parse_json_payload("prose\n{\"a\": 1}\nmore prose",
                                         tolerate_leading_prose=True)

    def test_load_json_document_hashes_the_raw_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.json"
            raw = "Leading prose.\n{\"k\": [1, 2, 3]}\n".encode("utf-8")
            path.write_bytes(raw)
            with self.assertRaises(documents.DocumentFormatError) as ctx:
                documents.load_json_document(path)
            self.assertIn("tolerate_leading_prose", str(ctx.exception))
            loaded = documents.load_json_document(path, tolerate_leading_prose=True)
        self.assertEqual(loaded.data, {"k": [1, 2, 3]})
        self.assertEqual(loaded.sha256, documents.sha256_bytes(raw))
        self.assertEqual(loaded.payload_sha256, documents.sha256_text('{"k": [1, 2, 3]}'))
        self.assertNotEqual(loaded.sha256, loaded.payload_sha256)
        self.assertEqual(loaded.to_manifest_entry()["source_defects"][0]["kind"],
                         "leading_prose")

    def test_missing_file_is_a_format_error(self):
        with self.assertRaises(documents.DocumentFormatError):
            documents.load_json_document(Path("/nonexistent/frozen_test_v2.json"))

    def test_document_from_data_is_deterministic(self):
        first = documents.document_from_data({"b": 1, "a": [1, 2]})
        second = documents.document_from_data({"a": [1, 2], "b": 1})
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.defects, ())

    def test_jsonl_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            documents.write_jsonl(path, [{"b": 1, "a": "x"}, {"a": "y", "b": 2}])
            self.assertEqual(documents.read_jsonl(path), [{"a": "x", "b": 1}, {"a": "y", "b": 2}])
            with self.assertRaises(FileExistsError):
                documents.write_jsonl(path, [])


class BenchmarkSchemaTests(unittest.TestCase):
    def setUp(self):
        self.doc = make_benchmark("a", standard_groups("a"))

    def test_valid_benchmark_has_no_errors_or_defects(self):
        result = schemas.validate_benchmark(self.doc)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.group_defects, {})
        self.assertTrue(result.ok)

    def test_missing_second_paraphrase_is_a_group_defect(self):
        del self.doc["groups"][0]["paraphrases"][1]
        self.doc["self_check"]["item_count"] -= 1
        result = schemas.validate_benchmark(self.doc)
        self.assertEqual(result.errors, [])
        self.assertTrue(any("exactly 2 paraphrases" in defect
                            for defect in result.group_defects["syn-a-001"]))

    def test_duplicate_request_id_is_fatal(self):
        self.doc["groups"][1]["paraphrases"][0]["request_id"] = "syn-a-001-p1"
        result = schemas.validate_benchmark(self.doc)
        self.assertTrue(any("duplicate request_id" in error for error in result.errors))

    def test_foreign_request_id_is_a_defect(self):
        self.doc["groups"][1]["paraphrases"][0]["request_id"] = "other-p1"
        result = schemas.validate_benchmark(self.doc)
        self.assertTrue(any("does not belong" in defect
                            for defect in result.group_defects["syn-a-002"]))

    def test_execute_gold_with_boolean_channels_is_a_defect(self):
        self.doc["groups"][0]["proposed_gold_fields"]["channels"] = True
        result = schemas.validate_benchmark(self.doc)
        self.assertTrue(any("channels" in defect for defect in result.group_defects["syn-a-001"]))

    def test_execute_gold_inconsistent_with_topology_is_a_defect(self):
        self.doc["groups"][0]["proposed_gold_fields"]["working_period"] = 12
        result = schemas.validate_benchmark(self.doc)
        self.assertTrue(any("working_period" in defect
                            for defect in result.group_defects["syn-a-001"]))

    def test_incomplete_execute_gold_is_a_defect(self):
        self.doc["groups"][0]["proposed_gold_fields"] = {}
        result = schemas.validate_benchmark(self.doc)
        self.assertTrue(any("missing field" in defect
                            for defect in result.group_defects["syn-a-001"]))

    def test_reject_gold_unconfirmed_by_contract_is_a_defect(self):
        group = self.doc["groups"][2]
        group["proposed_gold_fields"]["channels"] = 3
        group["invalid_fields"] = {"channels": {"observed": 3, "reason": "claimed"}}
        result = schemas.validate_benchmark(self.doc)
        self.assertTrue(any("confirmed by the configuration contract" in defect
                            for defect in result.group_defects["syn-a-003"]))

    def test_reject_without_invalid_fields_is_a_defect(self):
        del self.doc["groups"][2]["invalid_fields"]
        result = schemas.validate_benchmark(self.doc)
        self.assertTrue(any("enumerate invalid_fields" in defect
                            for defect in result.group_defects["syn-a-003"]))

    def test_clarify_with_invalid_fields_is_a_defect(self):
        self.doc["groups"][1]["invalid_fields"] = {"channels": {"observed": 0, "reason": "x"}}
        result = schemas.validate_benchmark(self.doc)
        self.assertTrue(any("must not carry invalid_fields" in defect
                            for defect in result.group_defects["syn-a-002"]))

    def test_duplicate_text_across_groups_flags_both_groups(self):
        text = self.doc["groups"][0]["paraphrases"][0]["request_text"]
        self.doc["groups"][3]["paraphrases"][1]["request_text"] = text.upper()
        result = schemas.validate_benchmark(self.doc)
        self.assertIn("syn-a-001", result.group_defects)
        self.assertIn("syn-a-004", result.group_defects)

    def test_self_check_mismatch_is_a_warning(self):
        self.doc["self_check"]["execute_groups"] = 5
        result = schemas.validate_benchmark(self.doc)
        self.assertEqual(result.errors, [])
        self.assertTrue(any("self_check.execute_groups" in warning
                            for warning in result.warnings))

    def test_invalid_enumerations_are_defects(self):
        group = self.doc["groups"][1]
        group["difficulty"] = "trivial"
        group["ambiguity_risk"] = "unknown"
        group["proposed_gold_action"] = "MAYBE"
        defects = schemas.validate_benchmark(self.doc).group_defects["syn-a-002"]
        for token in ("difficulty", "ambiguity_risk", "proposed_gold_action"):
            self.assertTrue(any(token in defect for defect in defects), token)

    def test_non_object_documents_are_fatal(self):
        self.assertTrue(schemas.validate_benchmark([]).errors)
        self.assertTrue(schemas.validate_benchmark({"groups": []}).errors)


class ReviewSchemaTests(unittest.TestCase):
    def setUp(self):
        self.benchmark = make_benchmark("a", standard_groups("a"))
        self.review = make_review(self.benchmark)

    def test_valid_review_passes(self):
        result = schemas.validate_review(self.review, self.benchmark)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.entry_defects, {})
        self.assertEqual(result.missing_reviews, [])

    def test_batch_mismatch_is_fatal(self):
        self.review["reviewed_batch"] = "someone-else"
        result = schemas.validate_review(self.review, self.benchmark)
        self.assertTrue(any("reviewed_batch" in error for error in result.errors))

    def test_unknown_group_is_fatal(self):
        self.review["reviews"].append(make_review_entry({
            "semantic_group_id": "syn-a-999", "proposed_gold_action": "CLARIFY",
            "proposed_gold_fields": None}))
        result = schemas.validate_review(self.review, self.benchmark)
        self.assertTrue(any("unknown group syn-a-999" in error for error in result.errors))

    def test_missing_review_is_recorded(self):
        review = make_review(self.benchmark, drop=("syn-a-002",))
        result = schemas.validate_review(review, self.benchmark)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.missing_reviews, ["syn-a-002"])

    def test_entry_defects_are_collected(self):
        entry = self.review["reviews"][1]
        entry["adjudicated_action"] = "MAYBE"
        entry["paraphrase_equivalent"] = "yes"
        entry["item_quality"] = "meh"
        entry["reason"] = ""
        result = schemas.validate_review(self.review, self.benchmark)
        self.assertEqual(len(result.entry_defects["syn-a-002"]), 4)

    def test_reviewer_execute_fields_must_be_complete(self):
        self.review["reviews"][0]["adjudicated_fields"] = {"channels": 3}
        result = schemas.validate_review(self.review, self.benchmark)
        self.assertTrue(any("reviewer EXECUTE fields" in defect
                            for defect in result.entry_defects["syn-a-001"]))


class DecisionsSchemaTests(unittest.TestCase):
    def test_valid_document(self):
        doc = make_decisions([
            keep_decision("syn-a-001", "EXECUTE", fields=execute_fields()),
            exclude_decision("syn-a-002"),
        ])
        self.assertEqual(schemas.validate_decisions(doc), [])

    def test_rationale_is_required(self):
        doc = make_decisions([keep_decision("syn-a-001", "EXECUTE", fields=execute_fields(),
                                            rationale="")])
        self.assertTrue(any("rationale" in error for error in schemas.validate_decisions(doc)))

    def test_overrides_require_keep_with_edits(self):
        doc = make_decisions([keep_decision("syn-a-001", "EXECUTE", fields=execute_fields(),
                                            overrides={"syn-a-001-p1": "new text"})])
        self.assertTrue(any("keep_with_edits" in error
                            for error in schemas.validate_decisions(doc)))

    def test_quotas_require_a_rationale(self):
        doc = make_decisions([], quotas={"EXECUTE": 1, "CLARIFY": 1, "REJECT": 1,
                                         "UNSUPPORTED": 1})
        doc["quota_rationale"] = ""
        self.assertTrue(any("quota_rationale" in error
                            for error in schemas.validate_decisions(doc)))
        doc["quota_rationale"] = "fine"
        doc["quotas"] = {"EXECUTE": 1}
        self.assertTrue(any("quotas must map" in error
                            for error in schemas.validate_decisions(doc)))

    def test_duplicate_and_invalid_resolutions(self):
        doc = make_decisions([exclude_decision("syn-a-001"), exclude_decision("syn-a-001")])
        self.assertTrue(any("duplicate decision" in error
                            for error in schemas.validate_decisions(doc)))
        doc = make_decisions([{"semantic_group_id": "syn-a-001", "resolution": "maybe",
                               "rationale": "x"}])
        self.assertTrue(any("resolution" in error for error in schemas.validate_decisions(doc)))

    def test_kept_decisions_need_action_and_equivalence(self):
        decision = keep_decision("syn-a-001", "EXECUTE", fields=execute_fields())
        del decision["final_action"]
        decision["paraphrase_equivalent"] = None
        errors = schemas.validate_decisions(make_decisions([decision]))
        self.assertTrue(any("final_action" in error for error in errors))
        self.assertTrue(any("paraphrase_equivalent" in error for error in errors))

    def test_top_level_metadata_is_required(self):
        doc = make_decisions([], decided_by="")
        self.assertTrue(any("decided_by" in error for error in schemas.validate_decisions(doc)))
        self.assertTrue(schemas.validate_decisions([]))


class ModelMetadataSchemaTests(unittest.TestCase):
    def test_valid_and_invalid_metadata(self):
        valid = {"model_a": {"model_id": "a"}, "model_b": {"model_id": "b", "provider": "x"}}
        self.assertEqual(schemas.validate_model_metadata(valid), [])
        self.assertTrue(schemas.validate_model_metadata({"model_a": {"model_id": "a"}}))
        self.assertTrue(schemas.validate_model_metadata({"model_a": {"model_id": ""},
                                                        "model_b": {"model_id": "b"}}))
        self.assertTrue(schemas.validate_model_metadata("nope"))


if __name__ == "__main__":
    unittest.main()
