"""Tests for the local demo of the week-3 flowsheet.

The pure-Python part (week3_spec, solve_week3, demo_outputs) always runs. The interface tests need the optional extra
(``pip install -e '.[demo]'``) and are skipped without it, so the base CI stays standard library only. No test starts
a web server.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from process_sim_lab.demo import (
    DEFAULTS,
    HOST,
    INPUT_ORDER,
    SIZING_UNITS,
    build_app,
    convergence_markdown,
    demo_outputs,
    solve_week3,
    week3_spec,
)
from process_sim_lab.flowsheet import SIZING_FIELDS

try:
    import gradio
except ImportError:
    gradio = None

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
EXAMPLE = ROOT / "examples" / "reactor_flash_recycle.json"
VALUE_TOL = 1e-8  # mol/s, as tests/test_flowsheet.py

# The week-3 flowsheet by hand (docs/flowsheet-worked-example.md, section 2): flows in mol/s for (A, I, B).
HAND = {
    "feed": (5.6, 2.4, 0.0),
    "recycle": (1.0, 0.6, 0.4),
    "reactor-in": (6.6, 3.0, 0.4),
    "reactor-out": (2.0, 3.0, 5.0),
    "vapour": (1.25, 0.75, 0.5),
    "liquid": (0.75, 2.25, 4.5),
    "purge": (0.25, 0.15, 0.1),
}


def rows_by_name(rows):
    return {row[0]: row for row in rows}


class Week3SpecTest(unittest.TestCase):
    def test_defaults_are_the_example_file(self):
        self.assertEqual(week3_spec(), json.loads(EXAMPLE.read_text(encoding="utf-8")))

    def test_values_reach_the_spec(self):
        spec = week3_spec(feed_a=7.0, k_b=0.25, purge_fraction=0.1, method="direct", max_iter=40)
        self.assertEqual(spec["feeds"]["feed"]["flows"]["A"], 7.0)
        self.assertEqual(spec["units"][2]["params"]["k_values"]["B"], 0.25)
        self.assertEqual(spec["units"][3]["params"]["fractions"], [0.1, 0.9])
        self.assertEqual(spec["tear"]["method"], "direct")
        self.assertEqual(spec["tear"]["max_iter"], 40)

    def test_input_order_covers_every_keyword(self):
        self.assertEqual(set(INPUT_ORDER), set(DEFAULTS))
        self.assertEqual(week3_spec(**DEFAULTS), week3_spec())


class SolveWeek3Test(unittest.TestCase):
    """Pure Python: the function behind the form, against the hand derivation."""

    @classmethod
    def setUpClass(cls):
        cls.out = solve_week3()

    def test_streams_match_the_hand_answer(self):
        self.assertTrue(self.out["ok"])
        headers = self.out["streams"]["headers"]
        self.assertEqual(headers[:4], ["stream", "A (mol/s)", "I (mol/s)", "B (mol/s)"])
        rows = rows_by_name(self.out["streams"]["rows"])
        self.assertEqual(set(rows), set(HAND))
        for name, flows in HAND.items():
            with self.subTest(stream=name):
                for got, want in zip(rows[name][1:4], flows):
                    self.assertAlmostEqual(got, want, delta=VALUE_TOL)
                self.assertAlmostEqual(rows[name][4], sum(flows), delta=3 * VALUE_TOL)
                self.assertEqual(rows[name][5:], [330.0, 200000.0])

    def test_sizing_lists_every_field_with_its_unit(self):
        rows = self.out["sizing"]["rows"]
        fields = {(r[0], r[2]): r for r in rows}
        expected = [("reactor", f) for f in SIZING_FIELDS["cstr"]] + [("drum", f) for f in SIZING_FIELDS["flash"]]
        self.assertEqual([(r[0], r[2]) for r in rows], expected)
        self.assertEqual(fields[("reactor", "space_time")][3:], [100.0, "s"])  # tau = V / Q = 2 / 0.02
        self.assertAlmostEqual(fields[("drum", "diameter")][3], 0.206, delta=5e-4)  # worked example, section 5
        self.assertAlmostEqual(fields[("drum", "height")][3], 0.823, delta=5e-4)
        self.assertEqual(fields[("drum", "diameter")][4], "m")
        for type_fields in SIZING_FIELDS.values():
            for f in type_fields:
                self.assertIn(f, SIZING_UNITS)

    def test_convergence(self):
        c = self.out["convergence"]
        self.assertEqual((c["method"], c["iterations"]), ("wegstein", 3))
        self.assertLessEqual(c["residual"], 1e-10)
        self.assertEqual(len(c["history"]), 3)
        for v in c["overall_balance"].values():
            self.assertLess(abs(v), 1e-9)

    def test_direct_substitution_reaches_the_same_answer(self):
        out = solve_week3(method="direct")
        self.assertTrue(out["ok"])
        self.assertGreater(out["convergence"]["iterations"], 3)
        rows = rows_by_name(out["streams"]["rows"])
        for got, want in zip(rows["recycle"][1:4], HAND["recycle"]):
            self.assertAlmostEqual(got, want, delta=VALUE_TOL)

    def test_result_is_json(self):
        json.dumps(self.out["result"], allow_nan=False)
        self.assertEqual(self.out["result"]["name"], "reactor-flash-recycle")

    def test_a_changed_value_changes_the_answer(self):
        out = solve_week3(purge_fraction=0.5)
        self.assertTrue(out["ok"])
        before = rows_by_name(self.out["streams"]["rows"])["purge"][4]
        self.assertGreater(rows_by_name(out["streams"]["rows"])["purge"][4], before + 0.1)

    def test_bad_inputs_come_back_as_errors(self):
        cases = {
            "no convergence": ({"method": "direct", "max_iter": 3}, "did not converge"),
            "negative flow": ({"feed_a": -1.0}, "negative"),
            "unsizable drum": ({"k_a": 0.5, "k_i": 0.5, "k_b": 0.5}, "cannot be sized"),
            "bad method": ({"method": "newton"}, "method must be one of"),
            "fractional max_iter": ({"max_iter": 2.5}, "whole number"),
            "empty field": ({"volume": None}, "no value for ['volume']"),
            "unknown input": ({"colour": 1}, "unknown inputs ['colour']"),
        }
        for label, (values, message) in cases.items():
            with self.subTest(case=label):
                out = solve_week3(**values)
                self.assertFalse(out["ok"])
                self.assertIn(message, out["error"])
                self.assertIn(message, convergence_markdown(out))


class DemoOutputsTest(unittest.TestCase):
    def test_outputs_in_input_order(self):
        streams, sizing, markdown, text = demo_outputs(*(DEFAULTS[k] for k in INPUT_ORDER))
        self.assertEqual(len(streams), len(HAND))
        self.assertEqual(len(sizing), len(SIZING_FIELDS["cstr"]) + len(SIZING_FIELDS["flash"]))
        self.assertIn("**Converged** with `wegstein` in 3 passes", markdown)
        self.assertEqual(json.loads(text)["iterations"], 3)

    def test_error_outputs(self):
        values = dict(DEFAULTS, method="direct", max_iter=3)
        streams, sizing, markdown, text = demo_outputs(*(values[k] for k in INPUT_ORDER))
        self.assertEqual((streams, sizing), ([], []))
        self.assertTrue(markdown.startswith("**Not solved.**"))
        self.assertIn("error", json.loads(text))


class WithoutGradioTest(unittest.TestCase):
    def run_python(self, code):
        env = dict(os.environ, PYTHONPATH=str(SRC))
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)

    def test_module_imports_without_gradio(self):
        out = self.run_python("import sys; sys.modules['gradio'] = None; import process_sim_lab.demo as d; "
                              "print(d.solve_week3()['ok'])")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "True")

    def test_main_without_gradio_exits_2_with_a_hint(self):
        out = self.run_python("import sys; sys.modules['gradio'] = None; import process_sim_lab.demo as d; "
                              "sys.exit(d.main([]))")
        self.assertEqual(out.returncode, 2)
        self.assertIn("pip install -e '.[demo]'", out.stderr)

    def test_core_library_does_not_import_gradio(self):
        out = self.run_python("import sys, process_sim_lab, process_sim_lab.flowsheet, process_sim_lab.agent.runner; "
                              "print('gradio' in sys.modules)")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "False")


@unittest.skipIf(gradio is None, "needs the optional extra: pip install -e '.[demo]'")
class GradioAppTest(unittest.TestCase):
    """The interface builds and wires solve_week3; no server is started."""

    @classmethod
    def setUpClass(cls):
        cls.app = build_app()

    def test_app_is_blocks(self):
        self.assertIsInstance(self.app, gradio.Blocks)

    def test_inputs_and_outputs_are_wired(self):
        config = self.app.get_config_file()
        fns = [d for d in config["dependencies"] if len(d["inputs"]) == len(INPUT_ORDER)]
        self.assertTrue(fns, "no event takes every input")
        for dep in fns:
            self.assertEqual(len(dep["outputs"]), 4)

    def test_never_shares(self):
        self.assertEqual(HOST, "127.0.0.1")
        source = (SRC / "process_sim_lab" / "demo.py").read_text(encoding="utf-8")
        self.assertIn("share=False", source)
        self.assertNotIn("share=True", source)


if __name__ == "__main__":
    unittest.main()
