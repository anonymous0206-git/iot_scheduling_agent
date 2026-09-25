import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_validator_mutation_test.py"
CATALOGUE = ROOT / "benchmarks" / "topologies" / "frozen_test_v3_llm_catalogue.json"
# Small enough to schedule in milliseconds, dense enough to exercise every
# operator: a sparser fixture cannot produce a secondary collision at all.
TOPOLOGY = "legacy30_seed7"
CHANNELS = 2


def load_script():
    spec = importlib.util.spec_from_file_location("run_validator_mutation_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # The script defines a dataclass, and dataclasses resolve their annotations
    # through sys.modules, so the module has to be registered before it runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()
        from agentic_anex.models import AnexConfig
        from agentic_anex.tools import run_anex
        from agentic_anex.topology_io import load_json_topology
        catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
        cls.network = load_json_topology(ROOT / catalogue[TOPOLOGY]["path"])
        config = AnexConfig(working_period=cls.network.working_period, channels=CHANNELS,
                            communication_range=cls.network.communication_range)
        cls.schedule = run_anex(cls.network, config).schedule

    def mutants(self, limit=4):
        return self.script.mutants_for(self.network, self.schedule, CHANNELS, limit)

    def test_every_operator_produces_mutants(self):
        produced = {mutant.operator for mutant in self.mutants()}
        expected = {operator.__name__ for operator in self.script.OPERATORS}
        self.assertEqual(produced, expected)

    def test_every_condition_is_attacked(self):
        conditions = {mutant.condition for mutant in self.mutants()}
        self.assertEqual(conditions, set(self.script.CONDITIONS))

    def test_every_mutant_changes_the_schedule(self):
        for mutant in self.mutants():
            with self.subTest(operator=mutant.operator):
                self.assertNotEqual(mutant.schedule, tuple(self.schedule))

    def test_operators_leave_the_certified_schedule_untouched(self):
        before = tuple(self.schedule)
        self.mutants()
        self.assertEqual(tuple(self.schedule), before)

    def test_mutation_is_deterministic(self):
        first = [(m.operator, m.witness, m.schedule) for m in self.mutants()]
        second = [(m.operator, m.witness, m.schedule) for m in self.mutants()]
        self.assertEqual(first, second)

    def test_every_mutant_is_killed_by_the_check_it_attacks(self):
        report = self.script.kill_report(self.network, self.schedule, CHANNELS, self.mutants())
        survivors = [r for r in report["results"] if not r["rejected"]]
        self.assertEqual(survivors, [])
        missed = [r for r in report["results"] if not r["caught_by_the_targeted_check"]]
        self.assertEqual(missed, [], "a mutant was rejected, but not by the intended check")

    def test_a_surviving_mutant_is_reported_rather_than_hidden(self):
        """The suite has to be able to fail, or a clean run means nothing."""
        untouched = self.script.Mutant("no_op", "(i)", "MISSING_TRANSMISSION",
                                       "a mutation that changes nothing",
                                       tuple(self.schedule))
        report = self.script.kill_report(self.network, self.schedule, CHANNELS, [untouched])
        self.assertEqual(report["results"][0]["rejected"], False)
        self.assertEqual(report["results"][0]["caught_by_the_targeted_check"], False)

    def test_an_invalid_starting_schedule_is_refused(self):
        """A mutation test over a broken baseline would kill everything and prove nothing."""
        broken = tuple(self.schedule[1:])
        with self.assertRaises(ValueError):
            self.script.kill_report(self.network, broken, CHANNELS, [])

    def test_retiming_keeps_the_recorded_active_slot_consistent(self):
        entry = self.schedule[0]
        moved = self.script._retimed(entry, entry.timeslot + 3, self.network.working_period)
        self.assertEqual(moved.receiver_active_slot,
                         (entry.timeslot + 3) % self.network.working_period)


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra):
        argv = ["run_validator_mutation_test.py", "--catalogue", str(CATALOGUE),
                "--topology", TOPOLOGY, "--per-operator", "3", *extra]
        buffer = io.StringIO()
        with mock.patch("sys.argv", argv), contextlib.redirect_stdout(buffer):
            code = self.script.main()
        return code, buffer.getvalue()

    def test_a_clean_sweep_exits_zero_and_writes_once(self):
        out = self.root / "mutation"
        code, _ = self._run("--output-dir", str(out))
        self.assertEqual(code, 0)
        report = json.loads((out / "mutation.json").read_text(encoding="utf-8"))
        self.assertEqual(report["totals"]["survivors"], 0)
        self.assertEqual(report["totals"]["mutants"], report["totals"]["rejected"])
        self.assertIn("(v)", report["by_condition"])
        code, output = self._run("--output-dir", str(out))
        self.assertEqual(code, 1)
        self.assertIn("refusing to overwrite", output)

    def test_a_survivor_makes_the_run_fail(self):
        """Patch in an operator that breaks nothing, and the exit code must change."""
        def no_op(network, schedule, channels, limit):
            yield self.script.Mutant("no_op", "(i)", "MISSING_TRANSMISSION",
                                     "changes nothing", tuple(schedule))
        with mock.patch.object(self.script, "OPERATORS", (no_op,)):
            code, output = self._run()
        self.assertEqual(code, 1)
        self.assertIn("Survivors", output)

    def test_an_unknown_topology_is_refused(self):
        argv = ["run_validator_mutation_test.py", "--catalogue", str(CATALOGUE),
                "--topology", "not_a_topology"]
        buffer = io.StringIO()
        with mock.patch("sys.argv", argv), contextlib.redirect_stdout(buffer):
            code = self.script.main()
        self.assertEqual(code, 1)
        self.assertIn("is not in", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
