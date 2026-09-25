import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from frozen_test_v2 import cli, contract
from frozen_test_v2 import seal as sealing
from frozen_test_v2.decisions import SealRefusal, apply_decisions
from frozen_test_v2.documents import canonical_json, document_from_data, read_jsonl
from frozen_test_v2.reconcile import DEFECTIVE_ITEM, FULL_AGREEMENT, reconcile
from frozen_test_v2_fixtures import (
    execute_fields,
    keep_decision,
    loaded,
    make_decisions,
    make_review,
    standard_documents,
    write_sealing_support_files,
)

RATIO_FIELDS = dict(interference_ratio=1.5, collision_model="interference_range")


def build(documents, profile=None):
    ready = loaded(documents)
    return reconcile(ready["benchmark_a"], ready["review_of_a"],
                     ready["benchmark_b"], ready["review_of_b"], profile=profile)


def documents_with_ratio_group():
    documents = standard_documents()
    group = documents["benchmark_a"]["groups"][0]
    group["proposed_gold_fields"] = execute_fields(**RATIO_FIELDS)
    documents["review_of_a"] = make_review(documents["benchmark_a"])
    return documents


def run_cli(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(argv)
    return code, json.loads(out.getvalue())


class ProfileTests(unittest.TestCase):
    def test_profiles_are_registered(self):
        self.assertIs(contract.get_profile(None), contract.DEFAULT_CONTRACT)
        self.assertIs(contract.get_profile("frozen-test-v2"), contract.CONTRACT_V2)
        self.assertIs(contract.get_profile(contract.CONTRACT_V3), contract.CONTRACT_V3)
        self.assertEqual(contract.DEFAULT_CONTRACT.version, "frozen-test-v3")
        self.assertIsNone(contract.CONTRACT_V2.interference_ratio_fixed)
        self.assertEqual(contract.CONTRACT_V3.interference_ratio_fixed, 1.0)
        with self.assertRaises(ValueError):
            contract.get_profile("frozen-test-v9")

    def test_v3_fixes_interference_ratio_at_one(self):
        fields = execute_fields(**RATIO_FIELDS)
        self.assertIn("interference_ratio", contract.field_violations(fields))
        self.assertIn("interference_ratio",
                      contract.field_violations(fields, profile="frozen-test-v3"))
        self.assertEqual(contract.field_violations(fields, profile="frozen-test-v2"), {})
        for ratio in (1, 1.0):
            self.assertEqual(contract.field_violations(execute_fields(interference_ratio=ratio)),
                             {})
        for profile in ("frozen-test-v2", "frozen-test-v3"):
            self.assertIn("interference_ratio",
                          contract.field_violations({"interference_ratio": 0.5}, profile=profile))
        self.assertTrue(contract.execute_configuration_problems(fields))
        self.assertEqual(contract.execute_configuration_problems(fields, profile="frozen-test-v2"),
                         [])
        self.assertEqual(contract.execute_configuration_problems(
            execute_fields(interference_ratio=1.0, collision_model="interference_range")), [])

    def test_ratio_above_one_is_a_confirmed_invalid_field_under_v3(self):
        invalid = {"interference_ratio": {"observed": 2.0, "reason": "not 1.0"}}
        self.assertEqual(contract.unconfirmed_invalid_fields(execute_fields(), invalid), [])
        self.assertEqual(contract.unconfirmed_invalid_fields(execute_fields(), invalid,
                                                             profile="frozen-test-v2"),
                         ["interference_ratio"])


class ProfileReconciliationTests(unittest.TestCase):
    def test_v2_profile_accepts_a_ratio_above_one(self):
        result = build(documents_with_ratio_group(), profile="frozen-test-v2")
        self.assertEqual(result.group("syn-a-001").classification, FULL_AGREEMENT)
        self.assertEqual(result.contract_version, "frozen-test-v2")
        self.assertEqual(result.worksheet()["contract_version"], "frozen-test-v2")

    def test_v3_profile_marks_a_ratio_above_one_defective(self):
        result = build(documents_with_ratio_group())
        group = result.group("syn-a-001")
        self.assertEqual(group.classification, DEFECTIVE_ITEM)
        self.assertTrue(any("interference_ratio" in defect for defect in group.structural_defects))
        self.assertTrue(any("interference_ratio" in defect for defect in group.reviewer_defects))
        self.assertEqual(result.contract_version, "frozen-test-v3")
        self.assertEqual(result.worksheet()["contract_version"], "frozen-test-v3")

    def test_decisions_follow_the_reconciliation_profile(self):
        documents = documents_with_ratio_group()
        v3 = build(documents)
        decision = keep_decision("syn-a-001", "EXECUTE", fields=execute_fields(**RATIO_FIELDS))
        with self.assertRaises(SealRefusal) as ctx:
            apply_decisions(v3, make_decisions([decision]))
        self.assertTrue(any("interference_ratio" in problem
                            for problem in ctx.exception.problems))
        v2 = build(documents, profile="frozen-test-v2")
        final = apply_decisions(v2, make_decisions([]))
        self.assertEqual(len(final.groups), 8)
        self.assertEqual(final.quotas_observed["EXECUTE"], 2)


class ProfileSealAndCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.support = write_sealing_support_files(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def seal_with(self, reconciliation, out_name):
        return sealing.seal(
            reconciliation=reconciliation,
            decisions=document_from_data(make_decisions([]), path="<memory:decisions>"),
            model_metadata=self.support["model_metadata"],
            prompt_files=self.support["prompt_files"],
            topology_files=self.support["topology_files"],
            policy_version="synthetic-scope-policy.v2",
            output_dir=self.root / out_name,
            source_commit={"value": "synthetic", "source": "explicit", "dirty": None},
        )

    def test_seal_records_the_contract_version_and_id_prefix(self):
        self.assertEqual(sealing.sealed_id_prefix("frozen-test-v2"), "ft2")
        self.assertEqual(sealing.sealed_id_prefix("frozen-test-v3"), "ft3")
        result = self.seal_with(build(standard_documents()), "sealed_v3")
        self.assertEqual(result.manifest["contract_version"], "frozen-test-v3")
        self.assertEqual(result.manifest["benchmark_version"], "frozen-test-v3")
        requests = read_jsonl(result.paths["requests_jsonl"])
        self.assertTrue(all(record["request_id"].startswith("ft3-r") for record in requests))
        self.assertTrue(sealing.verify_sealed_directory(result.output_dir)["valid"])
        legacy = self.seal_with(build(standard_documents(), profile="frozen-test-v2"),
                                "sealed_v2")
        self.assertEqual(legacy.manifest["contract_version"], "frozen-test-v2")
        self.assertTrue(all(record["request_id"].startswith("ft2-r")
                            for record in read_jsonl(legacy.paths["requests_jsonl"])))

    def test_cli_contract_flag_selects_the_profile(self):
        documents = documents_with_ratio_group()
        paths = {}
        for key, doc in documents.items():
            path = self.root / f"{key}.json"
            path.write_text(canonical_json(doc), encoding="utf-8")
            paths[key] = path
        common = ["--batch-a", str(paths["benchmark_a"]),
                  "--review-of-a", str(paths["review_of_a"]),
                  "--batch-b", str(paths["benchmark_b"]),
                  "--review-of-b", str(paths["review_of_b"])]
        code, payload = run_cli(["validate", *common])
        self.assertEqual(code, 0)
        self.assertEqual(payload["summary"]["requires_human_decision"], 1)
        code, payload = run_cli(["validate", *common, "--contract", "frozen-test-v2"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["summary"]["requires_human_decision"], 0)
        with self.assertRaises(SystemExit):
            run_cli(["validate", *common, "--contract", "frozen-test-v9"])


if __name__ == "__main__":
    unittest.main()
