import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "demo_agent.py"


def load_script():
    spec = importlib.util.spec_from_file_location("demo_agent", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def report(status="REJECT", *, code=None, calls=0, supported=True, violations=()):
    """The fields `deciding_stage` reads, and nothing else."""
    policy = SimpleNamespace(supported=supported, violations=violations)
    return SimpleNamespace(
        status=status,
        error={"code": code} if code else None,
        llm_logs=tuple(object() for _ in range(calls)),
        scope_policy=policy,
    )


class DecidingStageTests(unittest.TestCase):
    """The demo must not read the deciding stage off the action.

    An UNSUPPORTED answer can come from the gate or from the model, and telling
    those apart is the point of the demo; an earlier draft mapped the action
    straight to a stage and reported a provider failure as a stage-2 rejection.
    """

    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def test_gate_refusal_is_attributed_to_stage_one(self):
        stage = self.script.deciding_stage(
            report("UNSUPPORTED", code="UNSUPPORTED_DIGITAL_TWIN", calls=0,
                   supported=False), "enforcing")
        self.assertIn("scope gate", stage)
        self.assertIn("before the model ran", stage)

    def test_parameter_rejection_is_attributed_to_stage_two(self):
        stage = self.script.deciding_stage(
            report("REJECT", code="INVALID_CHANNEL_COUNT", calls=0), "enforcing")
        self.assertIn("parameter legality", stage)
        self.assertIn("before the model ran", stage)

    def test_missing_topology_is_attributed_to_stage_three(self):
        stage = self.script.deciding_stage(
            report("CLARIFY", code="MISSING_TOPOLOGY", calls=0), "enforcing")
        self.assertIn("topology gate", stage)

    def test_a_refusal_after_model_calls_is_not_a_deterministic_stage(self):
        # The regression: one model call means no pre-model stage ended the run.
        stage = self.script.deciding_stage(report("REJECT", calls=1), "enforcing")
        self.assertIn("model", stage)
        self.assertNotIn("before the model ran", stage)

    def test_provider_failure_is_not_the_model_judging(self):
        for code in ("PROVIDER_TIMEOUT", "LLM_CLIENT_ERROR"):
            with self.subTest(code=code):
                stage = self.script.deciding_stage(
                    report("REJECT", code=code, calls=3), "enforcing")
                self.assertIn("provider call failed", stage)

    def test_gate_match_under_off_is_not_credited_to_the_gate(self):
        # With the gate off the detector still matches, but the model decided;
        # crediting the gate here would invent the ablation's result.
        stage = self.script.deciding_stage(
            report("UNSUPPORTED", calls=1, supported=False), "off")
        self.assertNotIn("scope gate", stage)

    def test_execute_says_the_deterministic_stages_sustained_it(self):
        stage = self.script.deciding_stage(report("EXECUTE", calls=1), "enforcing")
        self.assertIn("sustained", stage)


class GateDescriptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def test_a_match_names_the_category_and_the_witness(self):
        violation = SimpleNamespace(category="digital_twin_or_emulation",
                                    witness="digital twin")
        lines = self.script.describe_gate(report(supported=False,
                                                 violations=(violation,)))
        self.assertEqual(len(lines), 1)
        self.assertIn("digital_twin_or_emulation", lines[0])
        self.assertIn("digital twin", lines[0])

    def test_no_match_is_stated_rather_than_left_blank(self):
        lines = self.script.describe_gate(report())
        self.assertEqual(lines, ["  scope gate  : matched nothing"])


class UnlistedTopologyTests(unittest.TestCase):
    """Stage 3 binds on an exact whole-token match and says only "no topology".

    A request naming `topo50_seed10` when the catalogue holds `topo50_seed0`
    therefore produced the same question as one naming no topology at all, which
    sent a reader guessing. The demo names the token that missed.
    """

    CATALOGUE = {
        "legacy30_seed7": {}, "topo50_seed0": {}, "topo100_seed0": {},
        "topo150_seed0": {}, "topo200_seed0": {}, "topo250_seed0": {},
        "topo300_seed0": {},
    }

    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def test_a_near_miss_is_named_with_its_closest_match(self):
        found = self.script.unlisted_topologies(
            "schedule topo50_seed10 with two channels", self.CATALOGUE)
        self.assertEqual(found, [("topo50_seed10", "topo50_seed0")])

    def test_another_near_miss(self):
        found = self.script.unlisted_topologies("use topo5_seed0", self.CATALOGUE)
        self.assertEqual(found, [("topo5_seed0", "topo50_seed0")])

    def test_a_listed_topology_is_not_reported(self):
        self.assertEqual(
            self.script.unlisted_topologies("use topo50_seed0", self.CATALOGUE), [])

    def test_text_naming_no_identifier_reports_nothing(self):
        self.assertEqual(
            self.script.unlisted_topologies("the fifty node network", self.CATALOGUE), [])

    def test_an_unrecognisable_identifier_is_reported_without_a_guess(self):
        found = self.script.unlisted_topologies("use zzzz_seed99", self.CATALOGUE)
        self.assertEqual(found, [("zzzz_seed99", None)])

    def test_every_catalogue_id_is_recognised_by_the_token_pattern(self):
        # A catalogue entry the pattern cannot see would be reported as unlisted
        # even after the user typed it correctly.
        for name in self.CATALOGUE:
            with self.subTest(name=name):
                self.assertTrue(self.script.TOPOLOGY_TOKEN.fullmatch(name),
                                f"{name} is not matched by TOPOLOGY_TOKEN")


class ExampleTests(unittest.TestCase):
    """The shipped examples are labelled by what the pipeline does with them.

    Two of them exist to show the gate *missing* an out-of-scope request, which
    is Figure 3's finding; an earlier draft labelled them as refusals.
    """

    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def test_every_example_label_matches_the_scope_policy(self):
        import sys
        sys.path.insert(0, str(ROOT / "src"))
        from agentic_anex.scope_policy import evaluate_scope_policy

        for label, text in self.script.EXAMPLES:
            with self.subTest(label=label):
                blocked = not evaluate_scope_policy(text).supported
                claims_catch = "gate catches it" in label or "over-blocks" in label
                claims_miss = "gate misses it" in label
                if claims_catch:
                    self.assertTrue(blocked, f"{label!r} claims the gate acts, but it does not")
                if claims_miss:
                    self.assertFalse(blocked, f"{label!r} claims the gate misses it, but it matches")

    def test_examples_reach_each_deterministic_outcome(self):
        labels = " ".join(label for label, _ in self.script.EXAMPLES)
        for expected in ("executes", "gate catches it", "gate misses it",
                         "over-blocks", "stage 2", "stage 3"):
            self.assertIn(expected, labels)


if __name__ == "__main__":
    unittest.main()


class CatalogueShapeTests(unittest.TestCase):
    """Both catalogue shapes the repository ships must load.

    `frozen_test_v3_llm_catalogue.json` is a bare mapping; the generated
    `benchmarks/topologies/*/catalogue.json` wraps the same mapping under
    `topologies` beside its provenance. Reading only the bare shape returned the
    wrapper's six metadata keys, so all 180 topologies looked absent and a
    correctly spelled id was reported as unlisted.
    """

    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def test_a_bare_mapping_loads(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({"topo50_seed0": {"path": "a.json"}}))
            self.assertEqual(list(self.script.load_catalogue(path)), ["topo50_seed0"])

    def test_a_wrapped_mapping_loads_its_topologies(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({
                "catalogue_format": "agentic_anex.topology_catalogue.v1",
                "sizes": [50], "samples_per_size": 30,
                "topologies": {"topo50_seed10": {"path": "topo50_seed10.json"}},
            }))
            loaded = self.script.load_catalogue(path)
            self.assertEqual(list(loaded), ["topo50_seed10"])
            self.assertNotIn("catalogue_format", loaded)

    def test_both_shipped_catalogues_load_and_name_their_topologies(self):
        for relative, expected in (
            ("benchmarks/topologies/frozen_test_v3_llm_catalogue.json", "topo50_seed0"),
            ("benchmarks/topologies/fixed_area100_r20/catalogue.json", "topo50_seed10"),
        ):
            with self.subTest(catalogue=relative):
                path = ROOT / relative
                if not path.exists():
                    self.skipTest(f"{relative} is not in this checkout")
                loaded = self.script.load_catalogue(path)
                self.assertIn(expected, loaded,
                              f"{relative} should name {expected}")
                self.assertIn("path", loaded[expected])

    def test_relative_paths_resolve_against_either_root(self):
        # The two shapes disagree about what a relative path is relative to.
        for relative, expected in (
            ("benchmarks/topologies/frozen_test_v3_llm_catalogue.json", "topo50_seed0"),
            ("benchmarks/topologies/fixed_area100_r20/catalogue.json", "topo50_seed10"),
        ):
            with self.subTest(catalogue=relative):
                path = ROOT / relative
                if not path.exists():
                    self.skipTest(f"{relative} is not in this checkout")
                loaded = self.script.load_catalogue(path)
                instance = self.script.resolve_topology(expected, loaded, ROOT, path)
                self.assertEqual(instance.name, expected)


class TimelineTests(unittest.TestCase):
    """The terminal grid is the demo's output; it must not lose a transmission."""

    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    @staticmethod
    def entry(timeslot, channel):
        return SimpleNamespace(sender=0, receiver=1, timeslot=timeslot,
                               channel=channel, receiver_active_slot=0)

    def counted(self, lines):
        import re
        total = 0
        for line in lines:
            match = re.match(r"\s*ch (\d+)\s\s(.*)$", line)
            if match:
                total += sum(int(c) for c in match.group(2) if c.isdigit())
        return total

    def test_every_transmission_appears_in_the_grid(self):
        schedule = [self.entry(i % 27, (i % 3) + 1) for i in range(49)]
        self.assertEqual(self.counted(self.script.render_timeline(schedule)), 49)

    def test_a_slot_carrying_several_transmissions_shows_the_count(self):
        # Spatial reuse puts more than one transmission in a slot on a channel;
        # the validator certifies that is collision-free, so the grid must show
        # it rather than collapse it to a mark.
        schedule = [self.entry(0, 1) for _ in range(6)]
        lines = self.script.render_timeline(schedule)
        self.assertTrue(any(line.strip().startswith("ch 1") and "6" in line
                            for line in lines))

    def test_a_count_over_nine_does_not_widen_the_column(self):
        schedule = [self.entry(0, 1) for _ in range(12)]
        row = [l for l in self.script.render_timeline(schedule)
               if l.strip().startswith("ch 1")][0]
        self.assertIn("+", row)

    def test_one_row_per_channel(self):
        schedule = [self.entry(0, 1), self.entry(1, 2), self.entry(2, 3)]
        rows = [l for l in self.script.render_timeline(schedule)
                if l.strip().startswith("ch ")]
        self.assertEqual(len(rows), 3)

    def test_a_long_schedule_wraps_and_keeps_every_transmission(self):
        schedule = [self.entry(i, 1) for i in range(130)]
        lines = self.script.render_timeline(schedule)
        self.assertEqual(self.counted(lines), 130)
        self.assertTrue(any("slots 0-" in line for line in lines),
                        "a wrapped timeline should label its slot range")

    def test_an_empty_schedule_renders_nothing(self):
        self.assertEqual(self.script.render_timeline([]), [])
