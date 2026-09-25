import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_frozen_test_v3_seed_campaign.py"


def load_script():
    spec = importlib.util.spec_from_file_location("run_frozen_test_v3_seed_campaign", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SeedCampaignPlanTests(unittest.TestCase):
    """The plan is built without contacting a provider, so it can be checked offline."""

    def setUp(self):
        self.script = load_script()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.patch = mock.patch.object(self.script, "ROOT", self.root)
        self.patch.start()
        (self.root / "results" / "frozen_test_v3").mkdir(parents=True)

    def tearDown(self):
        self.patch.stop()
        self._tmp.cleanup()

    def test_plan_covers_every_arm_for_every_seed(self):
        runs = self.script.plan((1, 2), 600, 2)
        self.assertEqual(len(runs), len(self.script.ARMS) * 2)
        self.assertEqual({(r["arm"], r["seed"]) for r in runs},
                         {(arm[0], seed) for arm in self.script.ARMS for seed in (1, 2)})

    def test_every_run_writes_its_own_seeded_ledger(self):
        runs = self.script.plan((1, 2), 600, 2)
        ledgers = [Path(str(r["ledger"])).name for r in runs]
        self.assertEqual(len(set(ledgers)), len(ledgers), "ledgers must not collide")
        for run in runs:
            self.assertTrue(Path(str(run["ledger"])).name.endswith(f"_seed{run['seed']}.jsonl"),
                            run["ledger"])

    def test_seed_zero_ledgers_are_never_targeted(self):
        """The existing seed-0 ledgers carry no suffix; the driver must not touch them."""
        runs = self.script.plan((1, 2), 600, 2)
        names = {Path(str(r["ledger"])).name for r in runs}
        for stem in ("phi4_policy_v2", "phi4_no_scope_gate", "qwen25_policy_v2"):
            self.assertNotIn(f"{stem}.jsonl", names)

    def test_non_primary_runs_are_confirmed_and_gated_runs_are_not(self):
        runs = {r["arm"]: r["command"] for r in self.script.plan((1,), 600, 2)}
        for arm, mode in (("phi4_no_scope_gate", "off"),
                          ("phi4_advisory_scope_gate", "advisory")):
            command = runs[arm]
            self.assertIn("--confirm-ablation", command)
            self.assertIn("run_scope_gate_ablation.py", " ".join(command))
            self.assertNotIn("--systems", command)
            self.assertEqual(command[command.index("--scope-mode") + 1], mode)
        for arm in ("phi4_policy_v2", "qwen25_policy_v2"):
            command = runs[arm]
            self.assertNotIn("--confirm-ablation", command)
            self.assertNotIn("--scope-mode", command)
            self.assertIn("run_frozen_test_v3_experiments.py", " ".join(command))
            self.assertEqual(command[command.index("--systems") + 1], "llm_agent")

    def test_the_advisory_arm_uses_the_same_model_as_the_arms_it_is_compared_with(self):
        """An advisory-versus-gated difference must not also be a model difference."""
        arms = {label: model for label, _, _, model, _ in self.script.ARMS}
        self.assertEqual(arms["phi4_advisory_scope_gate"], arms["phi4_policy_v2"])
        self.assertEqual(arms["phi4_advisory_scope_gate"], arms["phi4_no_scope_gate"])

    def test_every_run_pins_one_seed_and_greedy_decoding(self):
        for run in self.script.plan((1, 2), 600, 2):
            command = run["command"]
            self.assertEqual(command[command.index("--seeds") + 1], str(run["seed"]))
            self.assertEqual(command[command.index("--temperature") + 1], "0")
            self.assertEqual(command[command.index("--model") + 1], run["model"])

    def run_main(self, *argv):
        out = io.StringIO()
        with mock.patch("sys.argv", ["run_frozen_test_v3_seed_campaign.py", *argv]), \
                contextlib.redirect_stdout(out):
            code = self.script.main()
        return code, json.loads(out.getvalue())

    def test_dry_run_calls_no_subprocess(self):
        with mock.patch.object(self.script.subprocess, "run") as runner:
            code, payload = self.run_main("--dry-run", "--seeds", "1,2")
        runner.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "planned")
        self.assertEqual(len(payload["runs"]), len(self.script.ARMS) * 2)

    def test_refuses_to_overwrite_an_existing_ledger(self):
        clash = self.script.ledger_for("qwen25_policy_v2", 1)
        clash.write_text("{}\n", encoding="utf-8")
        with mock.patch.object(self.script.subprocess, "run") as runner:
            code, payload = self.run_main("--seeds", "1,2")
        runner.assert_not_called()
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "refused")
        self.assertIn("qwen25_policy_v2_seed1.jsonl", payload["problems"][0])
        self.assertEqual(clash.read_text(encoding="utf-8"), "{}\n", "ledger must be untouched")

    def test_rejects_duplicate_seeds(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_main("--seeds", "1,1")



class OnlyFilterTests(unittest.TestCase):
    """Filling gaps left by an aborted campaign must not re-run what succeeded."""

    def setUp(self):
        self.script = load_script()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.patch = mock.patch.object(self.script, "RESULTS", str(self.root))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self._tmp.cleanup()

    def run_main(self, *argv):
        out = io.StringIO()
        with mock.patch("sys.argv", ["x", "--dry-run", *argv]), \
                contextlib.redirect_stdout(out):
            code = self.script.main()
        return code, json.loads(out.getvalue())

    def test_only_selects_exactly_the_named_pairs(self):
        code, payload = self.run_main("--arms", "frontier", "--seeds", "11,12,13",
                                      "--only", "gpt55_no_scope_gate=13",
                                      "--only", "gpt55_advisory_scope_gate=11")
        self.assertEqual(code, 0)
        self.assertEqual({(r["arm"], r["seed"]) for r in payload["runs"]},
                         {("gpt55_no_scope_gate", 13),
                          ("gpt55_advisory_scope_gate", 11)})

    def test_a_pair_outside_the_plan_is_refused(self):
        """A typo must not silently produce an empty campaign."""
        with self.assertRaises(SystemExit):
            self.run_main("--arms", "frontier", "--seeds", "11",
                          "--only", "gpt55_no_scope_gate=99")

    def test_a_malformed_spec_is_refused(self):
        with self.assertRaises(SystemExit):
            self.run_main("--arms", "frontier", "--seeds", "11",
                          "--only", "gpt55_no_scope_gate")

    def test_without_only_the_whole_set_runs(self):
        code, payload = self.run_main("--arms", "frontier", "--seeds", "11")
        self.assertEqual(len(payload["runs"]), len(self.script.FRONTIER_ARMS))


class ProviderOutageTests(unittest.TestCase):
    """A run the provider refused is not a result, whatever the exit code says."""

    def setUp(self):
        self.script = load_script()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def ledger(self, name, codes):
        path = self.root / name
        path.write_text("\n".join(
            json.dumps({"request_id": f"r{i}", "error_code": c})
            for i, c in enumerate(codes)) + "\n", encoding="utf-8")
        return path

    def test_a_healthy_ledger_reports_no_provider_errors(self):
        path = self.ledger("ok.jsonl", [None] * 20)
        rate, bad, total = self.script.provider_error_rate(path)
        self.assertEqual((rate, bad, total), (0.0, 0, 20))

    def test_a_rate_limited_ledger_is_almost_all_provider_error(self):
        """This is the shape of the campaign that exited 0 and measured nothing."""
        path = self.ledger("bad.jsonl", ["HTTP_PROVIDER_ERROR"] * 113 + [None] * 31)
        rate, bad, total = self.script.provider_error_rate(path)
        self.assertEqual((bad, total), (113, 144))
        self.assertGreater(rate, self.script.MAX_PROVIDER_ERROR_RATE)

    def test_timeouts_and_missing_models_count_too(self):
        for code in ("PROVIDER_TIMEOUT", "MODEL_UNAVAILABLE"):
            with self.subTest(code=code):
                path = self.ledger(f"{code}.jsonl", [code] * 10)
                self.assertEqual(self.script.provider_error_rate(path)[1], 10)

    def test_an_absent_ledger_is_not_treated_as_an_outage(self):
        rate, bad, total = self.script.provider_error_rate(self.root / "nope.jsonl")
        self.assertEqual((rate, bad, total), (0.0, 0, 0))

    def test_a_few_stray_errors_stay_under_the_threshold(self):
        path = self.ledger("few.jsonl", ["HTTP_PROVIDER_ERROR"] * 5 + [None] * 139)
        self.assertLess(self.script.provider_error_rate(path)[0],
                        self.script.MAX_PROVIDER_ERROR_RATE)


class FrontierArmTests(unittest.TestCase):
    """The API arms must differ from the local ones only where they have to."""

    def setUp(self):
        self.script = load_script()

    def test_frontier_arms_decode_at_temperature_one(self):
        """The provider rejects any other value at the transport layer."""
        runs = self.script.plan((1,), 600, 2, None, self.script.FRONTIER_ARMS)
        self.assertTrue(runs)
        for run in runs:
            command = run["command"]
            self.assertEqual(command[command.index("--temperature") + 1], "1")
            self.assertEqual(command[command.index("--provider") + 1], "openai")

    def test_local_arms_still_decode_greedily(self):
        for run in self.script.plan((1,), 600, 2, None, self.script.LOCAL_ARMS):
            command = run["command"]
            self.assertEqual(command[command.index("--temperature") + 1], "0")
            self.assertEqual(command[command.index("--provider") + 1], "ollama")

    def test_a_base_url_is_not_forced_on_the_api_arms(self):
        """--base-url names the local endpoint; sending it to the API is wrong."""
        for run in self.script.plan((1,), 600, 2, "http://127.0.0.1:11435",
                                    self.script.FRONTIER_ARMS):
            self.assertNotIn("--base-url", run["command"])

    def test_every_scope_mode_is_covered_at_both_capability_levels(self):
        modes = lambda arms: {runner for _, _, runner, _, _ in arms}
        self.assertEqual(modes(self.script.LOCAL_ARMS) & {"gated", "off", "advisory"},
                         {"gated", "off", "advisory"})
        self.assertEqual(modes(self.script.FRONTIER_ARMS),
                         {"gated", "off", "advisory"})

    def test_arm_sets_do_not_share_ledger_stems(self):
        stems = [stem for _, stem, _, _, _ in self.script.ARM_SETS["all"]]
        self.assertEqual(len(stems), len(set(stems)))


class DeviceCheckTests(unittest.TestCase):
    """A campaign must not start a timed run on a device it did not check."""

    def setUp(self):
        self.script = load_script()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.patch = mock.patch.object(self.script, "RESULTS", str(self.root))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self._tmp.cleanup()

    def test_the_device_report_sits_beside_the_ledger_it_certifies(self):
        ledger = Path("/tmp/results/phi4_policy_v2_seed11.jsonl")
        self.assertEqual(self.script.device_report_for(ledger).name,
                         "phi4_policy_v2_seed11.device.json")

    def test_a_cpu_served_model_stops_the_campaign_before_the_first_run(self):
        refusal = {"status": "refused", "serving_device": "cpu",
                   "problems": ["served on cpu"]}
        with mock.patch.object(self.script, "check_device",
                               return_value=(False, refusal)) as check, \
                mock.patch.object(self.script.subprocess, "run") as runner, \
                contextlib.redirect_stdout(io.StringIO()):
            with mock.patch("sys.argv", ["x", "--seeds", "11"]):
                code = self.script.main()
        self.assertEqual(code, 1)
        check.assert_called()
        runner.assert_not_called()

    def test_allow_cpu_is_passed_through_to_the_preflight(self):
        with mock.patch.object(self.script.subprocess, "run") as runner:
            runner.return_value = mock.Mock(returncode=0, stdout='{"serving_device":"cpu"}',
                                            stderr="")
            ready, report = self.script.check_device("phi4:14b", self.root / "l.jsonl",
                                                     allow_cpu=True)
        self.assertTrue(ready)
        self.assertIn("--allow-cpu", runner.call_args[0][0])
        self.assertEqual(report["serving_device"], "cpu")

if __name__ == "__main__":
    unittest.main()
