import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path

import frozen_test_v2
from frozen_test_v2 import reconcile as rc
from frozen_test_v2.documents import load_json_document
from frozen_test_v2_fixtures import (
    loaded,
    make_review,
    make_review_entry,
    standard_documents,
)


def build(documents):
    ready = loaded(documents)
    return rc.reconcile(ready["benchmark_a"], ready["review_of_a"],
                        ready["benchmark_b"], ready["review_of_b"])


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.docs = standard_documents()

    def group_a(self, index):
        return self.docs["benchmark_a"]["groups"][index]

    def override_review_a(self, **entries):
        self.docs["review_of_a"] = make_review(self.docs["benchmark_a"], entries)

    def test_identical_records_are_full_agreement(self):
        result = build(self.docs)
        self.assertEqual({group.classification for group in result.all_groups()},
                         {rc.FULL_AGREEMENT})
        summary = result.summary()
        self.assertEqual(summary["groups"], 8)
        self.assertEqual(summary["requests"], 16)
        self.assertEqual(summary["requires_human_decision"], 0)
        self.assertEqual(summary["by_classification"][rc.FULL_AGREEMENT], 8)
        self.assertEqual(summary["per_batch"]["synthetic-model-a"]["declared_counts"],
                         {"EXECUTE": 1, "CLARIFY": 1, "REJECT": 1, "UNSUPPORTED": 1})

    def test_action_disagreement(self):
        group = self.group_a(0)
        self.override_review_a(**{"syn-a-001": make_review_entry(
            group, action="REJECT", fields={"topology_id": "legacy30_seed7"})})
        reconciled = build(self.docs).group("syn-a-001")
        self.assertEqual(reconciled.classification, rc.ACTION_DISAGREEMENT)
        self.assertTrue(reconciled.requires_human_decision)
        self.assertTrue(any("action disagreement" in signal for signal in reconciled.signals))

    def test_field_disagreement_on_execute_channels(self):
        group = self.group_a(0)
        fields = copy.deepcopy(group["proposed_gold_fields"])
        fields["channels"] = 4
        self.override_review_a(**{"syn-a-001": make_review_entry(group, fields=fields)})
        reconciled = build(self.docs).group("syn-a-001")
        self.assertEqual(reconciled.classification, rc.FIELD_DISAGREEMENT)
        self.assertEqual(reconciled.field_differences,
                         [{"field": "channels", "generator": 3, "reviewer": 4}])

    def test_numeric_representation_is_not_a_disagreement(self):
        group = self.group_a(0)
        fields = copy.deepcopy(group["proposed_gold_fields"])
        fields["communication_range"] = 18
        fields["interference_ratio"] = 1
        self.override_review_a(**{"syn-a-001": make_review_entry(group, fields=fields)})
        self.assertEqual(build(self.docs).group("syn-a-001").classification, rc.FULL_AGREEMENT)

    def test_paraphrase_mismatch(self):
        group = self.group_a(1)
        self.override_review_a(**{"syn-a-002": make_review_entry(
            group, paraphrase_equivalent=False)})
        reconciled = build(self.docs).group("syn-a-002")
        self.assertEqual(reconciled.classification, rc.PARAPHRASE_MISMATCH)
        self.assertTrue(any("not equivalent" in signal for signal in reconciled.signals))

    def test_reviewer_revise_is_a_defective_item(self):
        group = self.group_a(3)
        self.override_review_a(**{"syn-a-004": make_review_entry(group, item_quality="revise")})
        reconciled = build(self.docs).group("syn-a-004")
        self.assertEqual(reconciled.classification, rc.DEFECTIVE_ITEM)
        self.assertIn("reviewer item_quality=revise", reconciled.signals)

    def test_reviewer_exclude_outranks_action_disagreement(self):
        group = self.group_a(0)
        self.override_review_a(**{"syn-a-001": make_review_entry(
            group, action="UNSUPPORTED", fields=None, item_quality="exclude")})
        self.assertEqual(build(self.docs).group("syn-a-001").classification, rc.DEFECTIVE_ITEM)

    def test_action_disagreement_outranks_paraphrase_mismatch(self):
        group = self.group_a(0)
        self.override_review_a(**{"syn-a-001": make_review_entry(
            group, action="UNSUPPORTED", fields=None, paraphrase_equivalent=False)})
        reconciled = build(self.docs).group("syn-a-001")
        self.assertEqual(reconciled.classification, rc.ACTION_DISAGREEMENT)
        self.assertTrue(any("not equivalent" in signal for signal in reconciled.signals))

    def test_paraphrase_mismatch_outranks_field_disagreement(self):
        group = self.group_a(0)
        fields = copy.deepcopy(group["proposed_gold_fields"])
        fields["channels"] = 4
        self.override_review_a(**{"syn-a-001": make_review_entry(
            group, fields=fields, paraphrase_equivalent=False)})
        reconciled = build(self.docs).group("syn-a-001")
        self.assertEqual(reconciled.classification, rc.PARAPHRASE_MISMATCH)
        self.assertEqual(len(reconciled.field_differences), 1)

    def test_missing_review_is_a_defective_item(self):
        self.docs["review_of_a"] = make_review(self.docs["benchmark_a"], drop=("syn-a-002",))
        result = build(self.docs)
        reconciled = result.group("syn-a-002")
        self.assertEqual(reconciled.classification, rc.DEFECTIVE_ITEM)
        self.assertIsNone(reconciled.reviewer)
        self.assertIn("no reviewer record for this group", reconciled.signals)
        self.assertIn("unreviewed group syn-a-002", result.batches[0].warnings)

    def test_structural_defect_outranks_action_disagreement(self):
        group = self.group_a(0)
        del group["paraphrases"][1]
        self.docs["benchmark_a"]["self_check"]["item_count"] -= 1
        self.override_review_a(**{"syn-a-001": make_review_entry(
            group, action="UNSUPPORTED", fields=None)})
        reconciled = build(self.docs).group("syn-a-001")
        self.assertEqual(reconciled.classification, rc.DEFECTIVE_ITEM)
        self.assertTrue(reconciled.structural_defects)

    def test_malformed_reviewer_record_is_a_defective_item(self):
        group = self.group_a(1)
        entry = make_review_entry(group)
        entry["paraphrase_equivalent"] = "true"
        self.override_review_a(**{"syn-a-002": entry})
        reconciled = build(self.docs).group("syn-a-002")
        self.assertEqual(reconciled.classification, rc.DEFECTIVE_ITEM)
        self.assertTrue(reconciled.reviewer_defects)

    def test_reject_partial_reviewer_fields_agree(self):
        group = self.group_a(2)
        self.override_review_a(**{"syn-a-003": make_review_entry(
            group, fields={"topology_id": "legacy30_seed7", "channels": 0})})
        reconciled = build(self.docs).group("syn-a-003")
        self.assertEqual(reconciled.classification, rc.FULL_AGREEMENT)
        self.assertTrue(any("did not enumerate invalid_fields" in signal
                            for signal in reconciled.signals))

    def test_reject_invalid_field_set_mismatch(self):
        group = self.group_a(2)
        self.override_review_a(**{"syn-a-003": make_review_entry(group, fields={
            "topology_id": "legacy30_seed7", "channels": 0,
            "invalid_fields": {"seed": {"observed": -1, "reason": "negative"}},
        })})
        reconciled = build(self.docs).group("syn-a-003")
        self.assertEqual(reconciled.classification, rc.FIELD_DISAGREEMENT)
        self.assertEqual(reconciled.field_differences[0]["field"], "invalid_fields")

    def test_reject_explicit_value_mismatch(self):
        group = self.group_a(2)
        self.override_review_a(**{"syn-a-003": make_review_entry(
            group, fields={"topology_id": "legacy30_seed7", "channels": 1})})
        reconciled = build(self.docs).group("syn-a-003")
        self.assertEqual(reconciled.classification, rc.FIELD_DISAGREEMENT)
        self.assertEqual(reconciled.field_differences,
                         [{"field": "channels", "generator": 0, "reviewer": 1}])

    def test_cross_batch_duplicate_text_is_defective(self):
        text = self.group_a(0)["paraphrases"][0]["request_text"]
        self.docs["benchmark_b"]["groups"][0]["paraphrases"][0]["request_text"] = text
        result = build(self.docs)
        self.assertEqual(result.group("syn-a-001").classification, rc.DEFECTIVE_ITEM)
        self.assertEqual(result.group("syn-b-001").classification, rc.DEFECTIVE_ITEM)
        self.assertTrue(result.group("syn-b-001").requires_human_decision)

    def test_group_id_collision_across_batches_is_fatal(self):
        group = self.docs["benchmark_b"]["groups"][0]
        group["semantic_group_id"] = "syn-a-001"
        for index, paraphrase in enumerate(group["paraphrases"], start=1):
            paraphrase["request_id"] = f"syn-a-001-p{index}"
        self.docs["review_of_b"] = make_review(self.docs["benchmark_b"])
        with self.assertRaises(rc.ReconciliationError) as ctx:
            build(self.docs)
        self.assertIn("syn-a-001", ctx.exception.problems)

    def test_same_batch_id_is_fatal(self):
        self.docs["benchmark_b"]["batch_id"] = self.docs["benchmark_a"]["batch_id"]
        self.docs["review_of_b"]["reviewed_batch"] = self.docs["benchmark_a"]["batch_id"]
        with self.assertRaises(rc.ReconciliationError):
            build(self.docs)

    def test_schema_errors_are_fatal(self):
        self.docs["review_of_a"]["reviewed_batch"] = "wrong"
        with self.assertRaises(rc.ReconciliationError) as ctx:
            build(self.docs)
        self.assertTrue(any("reviewed_batch" in problem for problem in ctx.exception.problems))

    def test_generator_ambiguity_risk_is_a_signal_only(self):
        self.group_a(1)["ambiguity_risk"] = "medium"
        reconciled = build(self.docs).group("syn-a-002")
        self.assertEqual(reconciled.classification, rc.FULL_AGREEMENT)
        self.assertIn("generator ambiguity_risk=medium", reconciled.signals)


class WorksheetTests(unittest.TestCase):
    def setUp(self):
        docs = standard_documents()
        group = docs["benchmark_a"]["groups"][0]
        docs["review_of_a"] = make_review(docs["benchmark_a"], {
            "syn-a-001": make_review_entry(group, paraphrase_equivalent=False)})
        self.reconciliation = build(docs)

    def test_worksheet_never_prefills_decisions(self):
        template = self.reconciliation.decisions_template()
        self.assertEqual([entry["semantic_group_id"] for entry in template["decisions"]],
                         ["syn-a-001"])
        entry = template["decisions"][0]
        for key in ("resolution", "final_action", "final_fields", "final_invalid_fields",
                    "paraphrase_equivalent"):
            self.assertIsNone(entry[key], key)
        self.assertEqual(entry["rationale"], "")
        self.assertEqual(entry["context"]["classification"], rc.PARAPHRASE_MISMATCH)
        worksheet = self.reconciliation.worksheet()
        self.assertFalse(worksheet["adjudication_policy"]["automatic_resolution"])
        self.assertEqual(worksheet["summary"]["requires_human_decision"], 1)
        self.assertEqual(len(worksheet["groups"]), 8)
        self.assertIn("synthetic-model-a", worksheet["inputs"])

    def test_markdown_lists_groups_requiring_decisions(self):
        text = self.reconciliation.markdown()
        self.assertIn("### syn-a-001 (synthetic-model-a) - PARAPHRASE_MISMATCH", text)
        self.assertIn("## Groups in full agreement", text)
        self.assertIn("| syn-b-001 | synthetic-model-b | EXECUTE |", text)
        self.assertIn("reviewer judged the paraphrases not equivalent", text)

    def test_source_defects_surface_in_batch_warnings(self):
        docs = standard_documents()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch_a.json"
            path.write_text("Here is my batch.\n" + json.dumps(docs["benchmark_a"]),
                            encoding="utf-8")
            ready = loaded(docs)
            benchmark_a = load_json_document(path, tolerate_leading_prose=True)
            result = rc.reconcile(benchmark_a, ready["review_of_a"],
                                  ready["benchmark_b"], ready["review_of_b"])
        worksheet = result.worksheet()
        warnings = worksheet["batch_warnings"]["synthetic-model-a"]
        self.assertTrue(any("leading_prose" in warning for warning in warnings))
        entry = worksheet["inputs"]["synthetic-model-a"]["benchmark"]
        self.assertEqual(entry["source_defects"][0]["kind"], "leading_prose")
        self.assertEqual({group.classification for group in result.all_groups()},
                         {rc.FULL_AGREEMENT})


class BoundaryTests(unittest.TestCase):
    def test_package_never_imports_agentic_anex_or_network_modules(self):
        package_dir = Path(frozen_test_v2.__file__).parent
        forbidden = {"agentic_anex", "urllib", "http", "socket", "requests", "httpx",
                     "ollama", "openai"}
        offenders = []
        for source in sorted(package_dir.glob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                offenders.extend(f"{source.name}: {name}" for name in names
                                 if name.split(".")[0] in forbidden)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
