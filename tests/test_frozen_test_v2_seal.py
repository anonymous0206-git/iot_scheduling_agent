import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from frozen_test_v2 import cli
from frozen_test_v2 import seal as sealing
from frozen_test_v2.decisions import SealRefusal
from frozen_test_v2.documents import canonical_json, document_from_data, read_jsonl, sha256_file, sha256_text
from frozen_test_v2.reconcile import reconcile
from frozen_test_v2_fixtures import (
    TOPOLOGY_ID,
    exclude_decision,
    execute_fields,
    keep_decision,
    loaded,
    make_decisions,
    make_review,
    make_review_entry,
    standard_documents,
    write_sealing_support_files,
)

NEW_TEXT = "A freshly rewritten second wording of the same synthetic request."


def build(documents):
    ready = loaded(documents)
    return reconcile(ready["benchmark_a"], ready["review_of_a"],
                     ready["benchmark_b"], ready["review_of_b"])


def with_paraphrase_mismatch(documents, group_id="syn-a-001"):
    group = next(g for g in documents["benchmark_a"]["groups"]
                 if g["semantic_group_id"] == group_id)
    documents["review_of_a"] = make_review(documents["benchmark_a"], {
        group_id: make_review_entry(group, paraphrase_equivalent=False)})
    return group


def run_cli(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(argv)
    return code, json.loads(out.getvalue())


class SealTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.support = write_sealing_support_files(self.root)
        self.source_commit = {"value": "synthetic-commit-0001", "source": "explicit",
                              "dirty": None}

    def tearDown(self):
        self._tmp.cleanup()

    def seal_kwargs(self, reconciliation, decisions_doc, out_name="sealed", **overrides):
        kwargs = dict(
            reconciliation=reconciliation,
            decisions=document_from_data(decisions_doc, path="<memory:decisions>"),
            model_metadata=self.support["model_metadata"],
            prompt_files=self.support["prompt_files"],
            topology_files=self.support["topology_files"],
            policy_version="synthetic-scope-policy.v2",
            output_dir=self.root / out_name,
            source_commit=self.source_commit,
        )
        kwargs.update(overrides)
        return kwargs

    def test_full_agreement_seals_without_decisions(self):
        result = sealing.seal(**self.seal_kwargs(build(standard_documents()), make_decisions([])))
        for path in result.paths.values():
            self.assertTrue(path.is_file(), path)
        requests = read_jsonl(result.paths["requests_jsonl"])
        gold = read_jsonl(result.paths["gold_jsonl"])
        self.assertEqual(len(requests), 16)
        self.assertEqual(len(gold), 16)
        self.assertEqual(result.manifest["counts"]["per_action"],
                         {"EXECUTE": 2, "CLARIFY": 2, "REJECT": 2, "UNSUPPORTED": 2})
        self.assertEqual(result.manifest["quotas"]["source"], "generator_self_check")
        self.assertTrue(sealing.verify_sealed_directory(result.output_dir)["valid"])
        execute_gold = next(record for record in gold if record["gold_action"] == "EXECUTE")
        self.assertEqual(execute_gold["gold_fields"]["topology_id"], TOPOLOGY_ID)
        self.assertEqual(execute_gold["decision_source"], "dual_agreement")
        reject_gold = next(record for record in gold if record["gold_action"] == "REJECT")
        self.assertIn("channels", reject_gold["invalid_fields"])

    def test_refuses_unresolved_disagreement(self):
        docs = standard_documents()
        with_paraphrase_mismatch(docs)
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**self.seal_kwargs(build(docs), make_decisions([])))
        self.assertTrue(any("unresolved PARAPHRASE_MISMATCH for syn-a-001" in problem
                            for problem in ctx.exception.problems))
        self.assertFalse((self.root / "sealed").exists())

    def test_refuses_quota_mismatch_without_declared_quotas(self):
        decisions = make_decisions([exclude_decision("syn-a-001")])
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**self.seal_kwargs(build(standard_documents()), decisions))
        self.assertTrue(any("quota mismatch for EXECUTE" in problem
                            for problem in ctx.exception.problems))

    def test_exclusion_with_declared_quotas_seals(self):
        decisions = make_decisions([exclude_decision("syn-a-001")], quotas={
            "EXECUTE": 1, "CLARIFY": 2, "REJECT": 2, "UNSUPPORTED": 2})
        result = sealing.seal(**self.seal_kwargs(build(standard_documents()), decisions))
        gold = read_jsonl(result.paths["gold_jsonl"])
        self.assertEqual(len(gold), 14)
        self.assertNotIn("syn-a-001", {record["semantic_group_id"] for record in gold})
        excluded = result.manifest["human_decisions"]["excluded_groups"]
        self.assertEqual(excluded[0]["semantic_group_id"], "syn-a-001")
        self.assertEqual(result.manifest["quotas"]["source"], "human_decisions.quotas")

    def test_refuses_to_overwrite_an_existing_sealed_benchmark(self):
        reconciliation = build(standard_documents())
        sealing.seal(**self.seal_kwargs(reconciliation, make_decisions([])))
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**self.seal_kwargs(reconciliation, make_decisions([])))
        self.assertIn("refusing to overwrite", ctx.exception.problems[0])
        other = self.root / "other"
        other.mkdir()
        (other / sealing.MANIFEST_FILENAME).write_text("{}", encoding="utf-8")
        with self.assertRaises(SealRefusal):
            sealing.seal(**self.seal_kwargs(reconciliation, make_decisions([]),
                                            out_name="other"))
        self.assertEqual((other / sealing.MANIFEST_FILENAME).read_text(encoding="utf-8"), "{}")

    def test_sealed_requests_carry_no_gold_leakage(self):
        docs = standard_documents()
        result = sealing.seal(**self.seal_kwargs(build(docs), make_decisions([])))
        requests = read_jsonl(result.paths["requests_jsonl"])
        gold = {record["request_id"]: record for record in read_jsonl(result.paths["gold_jsonl"])}
        source_order = [paraphrase["request_id"]
                        for key in ("benchmark_a", "benchmark_b")
                        for group in docs[key]["groups"]
                        for paraphrase in group["paraphrases"]]
        for record in requests:
            self.assertEqual(set(record), {"request_id", "request_text"})
            self.assertRegex(record["request_id"], r"^ft\d+-r\d{4}$")
            for source_id in source_order:
                self.assertNotIn(source_id, record["request_text"])
            self.assertEqual(gold[record["request_id"]]["request_text_sha256"],
                             sha256_text(record["request_text"]))
        self.assertTrue(all(check["passed"] for check in result.manifest["leakage_checks"]))
        sealed_source_order = [gold[record["request_id"]]["source_request_id"]
                               for record in requests]
        self.assertNotEqual(sealed_source_order, source_order)
        self.assertEqual(sorted(sealed_source_order), sorted(source_order))

    def test_leakage_checker_flags_forbidden_content(self):
        requests = [
            {"request_id": "ft2-r0001", "request_text": "Please EXECUTE this.",
             "gold_action": "EXECUTE"},
            {"request_id": "syn-a-001-p1", "request_text": "This mentions syn-a-001 here."},
        ]
        gold = [
            {"request_id": "ft2-r0001", "source_request_id": "syn-a-001-p1",
             "gold_action": "EXECUTE", "request_text_sha256": sha256_text("Please EXECUTE this.")},
            {"request_id": "syn-a-001-p1", "source_request_id": "syn-a-001-p2",
             "gold_action": "EXECUTE", "request_text_sha256": "bad"},
        ]
        checks = sealing.check_request_leakage(requests, gold, source_identifiers=["syn-a-001"])
        failed = {check["check"] for check in checks if not check["passed"]}
        for name in ("request_keys_allowlist", "opaque_request_ids", "no_source_identifiers",
                     "no_label_tokens", "gold_text_binding"):
            self.assertIn(name, failed)
        clean_requests = [{"request_id": "ft2-r0001", "request_text": "Plain text one."},
                          {"request_id": "ft2-r0002", "request_text": "Plain text two."}]
        clean_gold = [
            {"request_id": "ft2-r0001", "source_request_id": "x-p1", "gold_action": "EXECUTE",
             "request_text_sha256": sha256_text("Plain text one.")},
            {"request_id": "ft2-r0002", "source_request_id": "x-p2", "gold_action": "CLARIFY",
             "request_text_sha256": sha256_text("Plain text two.")},
        ]
        checks = sealing.check_request_leakage(clean_requests, clean_gold,
                                               source_identifiers=["x-p1", "x-p2"],
                                               source_order=["x-p2", "x-p1"])
        self.assertTrue(all(check["passed"] for check in checks))

    def test_manifest_contains_required_metadata(self):
        docs = standard_documents()
        ready = loaded(docs)
        reconciliation = reconcile(ready["benchmark_a"], ready["review_of_a"],
                                   ready["benchmark_b"], ready["review_of_b"])
        result = sealing.seal(**self.seal_kwargs(reconciliation, make_decisions([])))
        manifest = json.loads(result.paths["manifest"].read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_format"], sealing.MANIFEST_FORMAT)
        self.assertTrue(manifest["sealed_at_utc"].endswith("Z"))
        self.assertEqual(manifest["policy_version"], "synthetic-scope-policy.v2")
        self.assertEqual(manifest["source_commit"]["value"], "synthetic-commit-0001")
        self.assertEqual(manifest["model_metadata"]["declared"]["model_a"]["model_id"],
                         "synthetic-model-a")
        self.assertIn("generator of synthetic-model-a",
                      manifest["model_metadata"]["roles"]["model_a"])
        self.assertIn("blind reviewer of synthetic-model-a",
                      manifest["model_metadata"]["roles"]["model_b"])
        prompt_path = self.support["prompt_files"]["generator_prompt"]
        self.assertEqual(manifest["prompt_hashes"]["generator_prompt"]["sha256"],
                         sha256_file(prompt_path))
        self.assertEqual(manifest["topology_count"], 1)
        self.assertEqual(sorted(manifest["topologies"]), [TOPOLOGY_ID])
        self.assertEqual(manifest["topologies"][TOPOLOGY_ID]["sha256"],
                         sha256_file(self.support["topology_file"]))
        self.assertEqual(manifest["topologies"][TOPOLOGY_ID]["topology_id"], TOPOLOGY_ID)
        self.assertEqual(manifest["topologies"][TOPOLOGY_ID]["node_count"], 3)
        self.assertEqual(manifest["inputs"]["benchmark_a"]["sha256"], ready["benchmark_a"].sha256)
        self.assertEqual(manifest["inputs"]["review_of_b"]["sha256"], ready["review_of_b"].sha256)
        for key, entry in manifest["outputs"].items():
            self.assertEqual(entry["sha256"], sha256_file(result.output_dir / entry["path"]), key)
        digest = (result.output_dir / sealing.MANIFEST_DIGEST_FILENAME).read_text(
            encoding="utf-8").split()[0]
        self.assertEqual(digest, sha256_file(result.paths["manifest"]))
        self.assertEqual(manifest["reconciliation_summary"]["requires_human_decision"], 0)
        self.assertEqual(manifest["shuffle_seed"], sealing.DEFAULT_SHUFFLE_SEED)
        self.assertEqual(manifest["source_defects"], [])

    def test_verify_detects_tampering(self):
        result = sealing.seal(**self.seal_kwargs(build(standard_documents()), make_decisions([])))
        path = result.paths["requests_jsonl"]
        path.write_text(path.read_text(encoding="utf-8").replace("Synthetic", "Tampered"),
                        encoding="utf-8")
        report = sealing.verify_sealed_directory(result.output_dir)
        self.assertFalse(report["valid"])
        self.assertTrue(any("requests_jsonl" in failure for failure in report["failures"]))
        self.assertTrue(any("gold_text_binding" in failure for failure in report["failures"]))

    def test_keep_with_edits_overrides_text(self):
        docs = standard_documents()
        group = with_paraphrase_mismatch(docs)
        decision = keep_decision("syn-a-001", "EXECUTE", fields=group["proposed_gold_fields"],
                                 resolution="keep_with_edits",
                                 overrides={"syn-a-001-p2": NEW_TEXT})
        result = sealing.seal(**self.seal_kwargs(build(docs), make_decisions([decision])))
        texts = {record["request_text"] for record in read_jsonl(result.paths["requests_jsonl"])}
        self.assertIn(NEW_TEXT, texts)
        gold = next(record for record in read_jsonl(result.paths["gold_jsonl"])
                    if record["source_request_id"] == "syn-a-001-p2")
        self.assertEqual(gold["decision_source"], "human:keep_with_edits")
        self.assertEqual(gold["paraphrase_equivalence_source"], "human")
        self.assertEqual(gold["request_text_sha256"], sha256_text(NEW_TEXT))
        self.assertEqual(result.manifest["human_decisions"]["decisions_applied"], 1)

    def test_decision_must_assert_paraphrase_equivalence(self):
        docs = standard_documents()
        group = with_paraphrase_mismatch(docs)
        decision = keep_decision("syn-a-001", "EXECUTE", fields=group["proposed_gold_fields"],
                                 equivalent=False)
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**self.seal_kwargs(build(docs), make_decisions([decision])))
        self.assertTrue(any("paraphrase equivalence" in problem
                            for problem in ctx.exception.problems))

    def test_decision_with_invalid_execute_fields_is_refused(self):
        docs = standard_documents()
        with_paraphrase_mismatch(docs)
        decision = keep_decision("syn-a-001", "EXECUTE", fields=execute_fields(channels=0))
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**self.seal_kwargs(build(docs), make_decisions([decision])))
        self.assertTrue(any("EXECUTE gold channels" in problem
                            for problem in ctx.exception.problems))

    def test_reject_decision_needs_confirmed_invalid_fields(self):
        docs = standard_documents()
        with_paraphrase_mismatch(docs, "syn-a-003")
        decision = keep_decision("syn-a-003", "REJECT", fields={"topology_id": TOPOLOGY_ID},
                                 invalid_fields=None)
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**self.seal_kwargs(build(docs), make_decisions([decision])))
        self.assertTrue(any("final_invalid_fields" in problem
                            for problem in ctx.exception.problems))

    def test_decision_for_unknown_group_is_refused(self):
        decision = keep_decision("syn-z-999", "CLARIFY")
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**self.seal_kwargs(build(standard_documents()),
                                            make_decisions([decision])))
        self.assertTrue(any("unknown group syn-z-999" in problem
                            for problem in ctx.exception.problems))

    def test_source_commit_resolution(self):
        with self.assertRaises(SealRefusal):
            sealing.resolve_source_commit(None, None)
        self.assertEqual(sealing.resolve_source_commit(None, "abc123"),
                         {"value": "abc123", "source": "explicit", "dirty": None})
        with self.assertRaises(SealRefusal):
            sealing.resolve_source_commit(self.root / "not-a-checkout", None)

    def test_topology_mismatch_is_refused(self):
        bad = self.root / "bad_topology.json"
        bad.write_text(json.dumps({"name": TOPOLOGY_ID, "working_period": 9,
                                   "communication_range": 18.0, "nodes": []}),
                       encoding="utf-8")
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**self.seal_kwargs(build(standard_documents()), make_decisions([]),
                                            topology_files={TOPOLOGY_ID: bad}))
        self.assertTrue(any("working_period" in problem for problem in ctx.exception.problems))

    def test_every_catalogue_topology_must_be_hashed(self):
        reconciliation = build(standard_documents())
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**self.seal_kwargs(reconciliation, make_decisions([]),
                                            topology_files={}))
        self.assertTrue(any("no file for topology" in problem
                            for problem in ctx.exception.problems))
        with self.assertRaises(SealRefusal) as ctx:
            sealing.seal(**self.seal_kwargs(
                reconciliation, make_decisions([]),
                topology_files={"not_in_catalogue": self.support["topology_file"]}))
        self.assertTrue(any("not in the catalogue" in problem
                            for problem in ctx.exception.problems))
        self.assertFalse((self.root / "sealed").exists())

    def test_missing_provenance_inputs_are_refused(self):
        reconciliation = build(standard_documents())
        with self.assertRaises(SealRefusal):
            sealing.seal(**self.seal_kwargs(reconciliation, make_decisions([]), prompt_files={}))
        with self.assertRaises(SealRefusal):
            sealing.seal(**self.seal_kwargs(reconciliation, make_decisions([]),
                                            policy_version=""))
        bad_metadata = document_from_data({"model_a": {"model_id": "a"}})
        with self.assertRaises(SealRefusal):
            sealing.seal(**self.seal_kwargs(reconciliation, make_decisions([]),
                                            model_metadata=bad_metadata))
        self.assertFalse((self.root / "sealed").exists())

    def test_cli_end_to_end(self):
        docs = standard_documents()
        paths = {}
        for key, doc in docs.items():
            path = self.root / f"{key}.json"
            path.write_text(canonical_json(doc), encoding="utf-8")
            paths[key] = path
        common = ["--batch-a", str(paths["benchmark_a"]),
                  "--review-of-a", str(paths["review_of_a"]),
                  "--batch-b", str(paths["benchmark_b"]),
                  "--review-of-b", str(paths["review_of_b"])]
        code, payload = run_cli(["validate", *common])
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "valid")
        code, payload = run_cli(["reconcile", *common, "--out", str(self.root / "reconcile")])
        self.assertEqual(code, 0)
        self.assertEqual(payload["summary"]["requires_human_decision"], 0)
        for name in ("reconciliation_worksheet.json", "reconciliation_worksheet.md",
                     "human_decisions_template.json"):
            self.assertTrue((self.root / "reconcile" / name).is_file(), name)
        code, payload = run_cli(["reconcile", *common, "--out", str(self.root / "reconcile")])
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "refused")
        decisions_path = self.root / "decisions.json"
        decisions_path.write_text(canonical_json(make_decisions([])), encoding="utf-8")
        metadata_path = self.root / "model_metadata.json"
        metadata_path.write_text(canonical_json(self.support["model_metadata"].data),
                                 encoding="utf-8")
        prompt = self.support["prompt_files"]["generator_prompt"]
        seal_args = ["seal", *common,
                     "--decisions", str(decisions_path),
                     "--model-metadata", str(metadata_path),
                     "--prompt", f"generator_prompt={prompt}",
                     "--topology-file", str(self.support["topology_file"]),
                     "--policy-version", "synthetic-scope-policy.v2",
                     "--source-commit", "synthetic-commit",
                     "--out", str(self.root / "cli_sealed")]
        code, payload = run_cli(seal_args)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["status"], "sealed")
        self.assertEqual(payload["counts"]["requests"], 16)
        code, payload = run_cli(["verify", "--sealed-dir", str(self.root / "cli_sealed")])
        self.assertEqual(code, 0, payload)
        code, payload = run_cli(seal_args)
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "refused")
        self.assertIn("refusing to overwrite", payload["problems"][0])

    def test_cli_check_decisions_reports_without_sealing(self):
        docs = standard_documents()
        with_paraphrase_mismatch(docs)
        paths = {}
        for key, doc in docs.items():
            path = self.root / f"{key}.json"
            path.write_text(canonical_json(doc), encoding="utf-8")
            paths[key] = path
        common = ["--batch-a", str(paths["benchmark_a"]),
                  "--review-of-a", str(paths["review_of_a"]),
                  "--batch-b", str(paths["benchmark_b"]),
                  "--review-of-b", str(paths["review_of_b"])]
        decisions_path = self.root / "decisions.json"
        bad = make_decisions([{"semantic_group_id": "syn-a-001", "resolution": "revise",
                               "rationale": "not a valid resolution"}])
        decisions_path.write_text(canonical_json(bad), encoding="utf-8")
        code, payload = run_cli(["check-decisions", *common, "--decisions", str(decisions_path)])
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "refused")
        self.assertTrue(any("resolution 'revise'" in problem for problem in payload["problems"]))
        group = docs["benchmark_a"]["groups"][0]
        good = make_decisions([keep_decision("syn-a-001", "EXECUTE",
                                             fields=group["proposed_gold_fields"])])
        decisions_path.write_text(canonical_json(good), encoding="utf-8")
        code, payload = run_cli(["check-decisions", *common, "--decisions", str(decisions_path)])
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["status"], "decisions_accepted")
        self.assertEqual(payload["kept_groups"], 8)
        self.assertEqual(payload["decisions_applied"], 1)
        self.assertFalse(list(self.root.glob("**/frozen_test_v2_lock_manifest.json")))

    def test_cli_leading_prose_requires_the_tolerance_flag(self):
        docs = standard_documents()
        paths = {}
        for key, doc in docs.items():
            path = self.root / f"{key}.json"
            prefix = "Model output preamble.\n" if key == "benchmark_b" else ""
            path.write_text(prefix + canonical_json(doc), encoding="utf-8")
            paths[key] = path
        common = ["--batch-a", str(paths["benchmark_a"]),
                  "--review-of-a", str(paths["review_of_a"]),
                  "--batch-b", str(paths["benchmark_b"]),
                  "--review-of-b", str(paths["review_of_b"])]
        code, payload = run_cli(["validate", *common])
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "invalid")
        code, payload = run_cli(["validate", *common, "--tolerate-leading-prose"])
        self.assertEqual(code, 0)
        self.assertTrue(any("leading_prose" in warning
                            for warning in payload["batch_warnings"]["synthetic-model-b"]))


if __name__ == "__main__":
    unittest.main()
