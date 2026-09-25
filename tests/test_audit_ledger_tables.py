import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_ledger_tables.py"


def load_script():
    spec = importlib.util.spec_from_file_location("audit_ledger_tables", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def harness_item(request_id, group, action, batch="batch-a", category="synthetic"):
    return {"request_id": request_id, "paraphrase_group_id": group, "gold_action": action,
            "batch_id": batch, "category": category, "user_text": f"text for {request_id}"}


def record(request_id, group, action, *, model_calls=1, error_code=None,
           scope_policy=None, validation=None, system="llm_agent"):
    return {"request_id": request_id, "paraphrase_group_id": group, "action": action,
            "model_calls": model_calls, "error_code": error_code, "system": system,
            "scope_policy": scope_policy, "validation": validation}


def refused_by_gate():
    return {"supported": False, "policy_version": "test.v1", "checked_taxonomy": [],
            "violations": [{"category": "energy_aware_scheduling"}]}


def write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


class StageAttributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def test_each_stage_is_named_from_the_ledger(self):
        cases = {
            "scope_gate": record("r1", "g1", "UNSUPPORTED", model_calls=0,
                                 error_code="UNSUPPORTED_OBJECTIVE",
                                 scope_policy=refused_by_gate()),
            "parameter_check": record("r2", "g1", "REJECT", model_calls=0,
                                      error_code="INVALID_CHANNEL_COUNT"),
            "topology_gate": record("r3", "g2", "CLARIFY", model_calls=0,
                                    error_code="MISSING_TOPOLOGY"),
            "baseline_filter": record("r4", "g2", "UNSUPPORTED", model_calls=0,
                                      error_code="UNSUPPORTED_OBJECTIVE",
                                      system="rule_based"),
            "model": record("r5", "g3", "EXECUTE"),
            "none": record("r6", "g3", "EXECUTE", model_calls=0),
        }
        for expected, item in cases.items():
            with self.subTest(stage=expected):
                self.assertEqual(self.script.terminating_stage(item), expected)

    def test_the_gate_outranks_the_error_code_it_raises(self):
        """A gate refusal also carries an UNSUPPORTED_* code, like the baseline's."""
        gated = record("r1", "g1", "UNSUPPORTED", model_calls=0,
                       error_code="UNSUPPORTED_OBJECTIVE", scope_policy=refused_by_gate())
        baseline = record("r2", "g1", "UNSUPPORTED", model_calls=0,
                          error_code="UNSUPPORTED_OBJECTIVE", system="rule_based")
        self.assertEqual(self.script.terminating_stage(gated), "scope_gate")
        self.assertEqual(self.script.terminating_stage(baseline), "baseline_filter")

    def test_the_baseline_filter_survives_the_baseline_running_the_gate(self):
        """The baseline now carries a passing scope report on what the gate let through.

        Keying `baseline_filter` on the absence of that report would have
        silently reclassified every parser refusal as unclassified.
        """
        passed_the_gate = {"supported": True, "policy_version": "test.v1",
                           "checked_taxonomy": [], "violations": []}
        parser = record("r1", "g1", "UNSUPPORTED", model_calls=0, system="rule_based",
                        error_code="UNSUPPORTED_OBJECTIVE", scope_policy=passed_the_gate)
        self.assertEqual(self.script.terminating_stage(parser), "baseline_filter")

    def test_an_unexplained_refusal_from_a_model_arm_stays_unclassified(self):
        odd = record("r1", "g1", "REJECT", model_calls=0, error_code="SOMETHING_NEW")
        self.assertEqual(self.script.terminating_stage(odd), "unclassified")

    def test_forced_errors_count_only_deterministic_stages(self):
        harness = {"r1": harness_item("r1", "g1", "EXECUTE"),
                   "r2": harness_item("r2", "g1", "EXECUTE"),
                   "r3": harness_item("r3", "g2", "UNSUPPORTED")}
        records = [
            # the gate over-blocks a gold-EXECUTE request: a forced error
            record("r1", "g1", "UNSUPPORTED", model_calls=0, error_code="UNSUPPORTED_OBJECTIVE",
                   scope_policy=refused_by_gate()),
            # the model gets one wrong on its own
            record("r2", "g1", "REJECT"),
            # and one right
            record("r3", "g2", "UNSUPPORTED"),
        ]
        table = self.script.stage_termination("arm", records, harness)
        self.assertEqual(table["errors_total"], 2)
        self.assertEqual(table["errors_forced_by_a_deterministic_stage"], 1)
        self.assertEqual(table["errors_chosen_by_the_model"], 1)
        self.assertEqual(table["decided_before_the_model"], 1)
        self.assertEqual(table["by_stage"]["scope_gate"]["request_ids"], ["r1"])


class FalseAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def test_identity_is_reported_not_only_the_count(self):
        harness = {"r1": harness_item("r1", "g1", "REJECT", category="range_mismatch"),
                   "r2": harness_item("r2", "g1", "EXECUTE")}
        records = [record("r1", "g1", "EXECUTE"),
                   record("r2", "g1", "EXECUTE", validation={"valid": True, "violations": []})]
        table = self.script.false_acceptance("arm", records, harness)
        self.assertEqual(table["count"], 1)
        self.assertEqual(table["items"][0]["request_id"], "r1")
        self.assertEqual(table["items"][0]["category"], "range_mismatch")
        self.assertEqual(table["by_category"], {"range_mismatch": 1})

    def test_an_uncertified_execute_counts_even_when_the_action_is_right(self):
        harness = {"r1": harness_item("r1", "g1", "EXECUTE")}
        records = [record("r1", "g1", "EXECUTE",
                          validation={"valid": False, "violations": ["PRIMARY_COLLISION"]})]
        table = self.script.false_acceptance("arm", records, harness)
        self.assertEqual(table["count"], 1)
        self.assertIn("certificate", table["items"][0]["reason"])


class GateTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def setUp(self):
        self.harness = {
            # the gate over-blocks this one; removing it recovers the item
            "r1": harness_item("r1", "g1", "EXECUTE"),
            # the gate holds this one correctly; the model loses it when ungated
            "r2": harness_item("r2", "g1", "UNSUPPORTED"),
            # neither arm gates it and the model changes its mind for the better
            "r3": harness_item("r3", "g2", "EXECUTE"),
            # neither arm gates it and the model regresses
            "r4": harness_item("r4", "g2", "REJECT"),
        }
        self.gated = [
            record("r1", "g1", "UNSUPPORTED", model_calls=0, error_code="UNSUPPORTED_OBJECTIVE",
                   scope_policy=refused_by_gate()),
            record("r2", "g1", "UNSUPPORTED", model_calls=0, error_code="UNSUPPORTED_OBJECTIVE",
                   scope_policy=refused_by_gate()),
            record("r3", "g2", "REJECT"),
            record("r4", "g2", "REJECT"),
        ]
        self.ungated = [record("r1", "g1", "EXECUTE"), record("r2", "g1", "EXECUTE"),
                        record("r3", "g2", "EXECUTE"), record("r4", "g2", "CLARIFY")]

    def test_the_two_directions_are_counted_separately(self):
        pair = self.script.gate_transition("gated", self.gated, "ungated", self.ungated,
                                           self.harness)
        self.assertEqual(pair["wrong_to_right"], 2)
        self.assertEqual(pair["right_to_wrong"], 2)
        self.assertEqual(pair["net"], 0)
        self.assertEqual(pair["recovered_from_a_gate_over_block"], 1)
        self.assertEqual(pair["recovered_by_the_model_changing_its_answer"], 1)
        self.assertEqual(pair["correct_refusals_the_gate_was_carrying"], 1)
        self.assertEqual(pair["regressions_the_model_owns"], 1)

    def test_gated_answer_from_is_a_source_not_a_verdict(self):
        """The same value means a gate cost in one direction and a gate benefit in the other."""
        pair = self.script.gate_transition("gated", self.gated, "ungated", self.ungated,
                                           self.harness)
        moves = {move["request_id"]: move for move in pair["moves"]}
        self.assertEqual(moves["r1"]["direction"], "wrong_to_right")
        self.assertEqual(moves["r1"]["gated_answer_from"], "gate")
        self.assertEqual(moves["r2"]["direction"], "right_to_wrong")
        self.assertEqual(moves["r2"]["gated_answer_from"], "gate")

    def test_unchanged_items_are_absent(self):
        pair = self.script.gate_transition("gated", self.gated, "gated", self.gated,
                                           self.harness)
        self.assertEqual(pair["moves"], [])
        self.assertEqual(pair["net"], 0)


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.harness_path = self.root / "harness.jsonl"
        write_jsonl(self.harness_path, [harness_item("r1", "g1", "EXECUTE"),
                                        harness_item("r2", "g1", "UNSUPPORTED", batch="batch-b")])
        self.arm_path = self.root / "arm.jsonl"
        write_jsonl(self.arm_path, [record("r1", "g1", "EXECUTE"),
                                    record("r2", "g1", "EXECUTE")])

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra):
        argv = ["audit_ledger_tables.py", "--harness", str(self.harness_path),
                "--ledger", f"arm={self.arm_path}", *extra]
        buffer = io.StringIO()
        with mock.patch("sys.argv", argv), contextlib.redirect_stdout(buffer):
            code = self.script.main()
        return code, buffer.getvalue()

    def test_writes_each_table_once(self):
        out = self.root / "audit"
        code, _ = self._run("--output-dir", str(out))
        self.assertEqual(code, 0)
        for name in ("stage_termination.json", "false_acceptance.json", "per_batch.json",
                     "gate_transitions.json", "audit.json", "audit.md"):
            self.assertTrue((out / name).exists(), name)
        accepted = json.loads((out / "false_acceptance.json").read_text(encoding="utf-8"))
        self.assertEqual(accepted["arm"]["count"], 2)
        # a second run must refuse rather than overwrite
        code, output = self._run("--output-dir", str(out))
        self.assertEqual(code, 1)
        self.assertIn("refusing to overwrite", output)

    def test_a_request_id_outside_the_harness_is_refused(self):
        write_jsonl(self.arm_path, [record("rX", "gX", "EXECUTE")])
        code, output = self._run()
        self.assertEqual(code, 1)
        self.assertIn("absent from the harness", output)

    def test_a_pair_naming_an_unknown_arm_is_refused(self):
        code, output = self._run("--pair", "arm=missing")
        self.assertEqual(code, 1)
        self.assertIn("was not given", output)

    def test_no_output_dir_prints_the_tables(self):
        code, output = self._run()
        self.assertEqual(code, 0)
        self.assertIn("Which stage decided the request", output)
        self.assertIn("Per batch", output)


if __name__ == "__main__":
    unittest.main()
