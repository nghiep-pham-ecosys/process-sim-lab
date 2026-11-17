"""Tests for the JSON flowsheet and its recycle solver.

The check cases are built so the converged answer is known exactly:

- Reactor-flash-recycle (examples/reactor_flash_recycle.json). Components A (reactant), I (inert), B (product); a
  mixer, a CSTR for A -> B, a flash drum with K = (5, 1, 1/3), and a splitter that purges 1/5 of the vapour and
  recycles the rest. The converged state is chosen first and the feed and Damkohler number follow from it:
  reactor outlet C = (2, 3, 5) mol/s is the ternary flash case of test_flash (psi = 1/4, x = (0.1, 0.3, 0.6),
  y = (0.5, 0.3, 0.2)), so the vapour is V = (5/4, 3/4, 1/2), the liquid L = (3/4, 9/4, 9/2), the recycle
  R = 4/5 V = (1, 3/5, 2/5) and the purge 1/5 V = (1/4, 3/20, 1/10). A feed without B needs C_B - Da C_A = R_B,
  so Da = (5 - 2/5) / 2 = 23/10 (k = 0.023 1/s, V = 2 m3, Q = 0.02 m3/s), the reactor inlet is
  M = (C_A (1 + Da), C_I, C_B - Da C_A) = (33/5, 3, 2/5) and the feed is M - R = (28/5, 12/5, 0).
  ``constructed_case`` below repeats this derivation in exact fractions.
- Linear loop: feed of 10 mol/s A, mixer, CSTR with Da = 1, splitter with purge fraction p. The A balance is
  linear, R_A = a (F_0 + R_A) with a = (1 - p) / (1 + Da), so R_A = a F_0 / (1 - a); the total moles give
  M = F_0 / p, so R_B = (1 - p) M - R_A. For p = 1/5: R_A = 20/3, R_B = 100/3.
"""

import json
import math
import unittest
from fractions import Fraction
from pathlib import Path

from process_sim_lab import Stream
from process_sim_lab.flowsheet import (
    ConvergenceError,
    Flowsheet,
    FlowsheetResult,
    UnitSpec,
    _wegstein_step,
    solve_flowsheet,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "reactor_flash_recycle.json"
BALANCE_TOL = 1e-6  # the issue asks mass balances to close within 1e-6
VALUE_TOL = 1e-8  # converged values against the exact answer (tear tol 1e-10)


def constructed_case():
    """Exact converged state of the example flowsheet, derived from the chosen reactor outlet and flash state."""
    k = {"A": Fraction(5), "I": Fraction(1), "B": Fraction(1, 3)}
    c = {"A": Fraction(2), "I": Fraction(3), "B": Fraction(5)}
    psi, purge = Fraction(1, 4), Fraction(1, 5)
    liquid = {i: c[i] * (1 - psi) / (1 + psi * (k[i] - 1)) for i in c}
    vapour = {i: c[i] - liquid[i] for i in c}
    recycle = {i: (1 - purge) * vapour[i] for i in c}
    da = (c["B"] - recycle["B"]) / c["A"]
    reactor_in = {"A": c["A"] * (1 + da), "I": c["I"], "B": c["B"] - c["A"] * da}
    feed = {i: reactor_in[i] - recycle[i] for i in c}
    return {
        "da": da,
        "feed": feed,
        "reactor-in": reactor_in,
        "reactor-out": c,
        "vapour": vapour,
        "liquid": liquid,
        "recycle": recycle,
        "purge": {i: purge * vapour[i] for i in c},
    }


def linear_spec(purge_fraction, **tear):
    return {
        "name": "linear-loop",
        "feeds": {"feed": {"flows": {"A": 10.0}}},
        "units": [
            {"name": "mixer", "type": "mixer", "inlets": ["feed", "recycle"], "outlets": ["s1"]},
            {
                "name": "reactor",
                "type": "cstr",
                "inlets": ["s1"],
                "outlets": ["s2"],
                "params": {"reactant": "A", "product": "B", "rate_constant": 0.01, "volume": 2.0,
                           "volumetric_flow": 0.02},
            },
            {
                "name": "split",
                "type": "splitter",
                "inlets": ["s2"],
                "outlets": ["purge", "recycle"],
                "params": {"fractions": [purge_fraction, 1.0 - purge_fraction]},
            },
        ],
        "tear": {"streams": ["recycle"], **tear},
    }


def example_spec():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class ConstructedCaseTest(unittest.TestCase):
    def test_derivation_matches_the_example_file(self):
        case = constructed_case()
        self.assertEqual(case["da"], Fraction(23, 10))
        self.assertEqual(case["feed"], {"A": Fraction(28, 5), "I": Fraction(12, 5), "B": 0})
        self.assertEqual(case["recycle"], {"A": 1, "I": Fraction(3, 5), "B": Fraction(2, 5)})
        spec = example_spec()
        self.assertEqual(spec["feeds"]["feed"]["flows"], {"A": 5.6, "I": 2.4})
        reactor = spec["units"][1]["params"]
        self.assertAlmostEqual(
            reactor["rate_constant"] * reactor["volume"] / reactor["volumetric_flow"], float(case["da"]), places=12
        )


class ExampleFlowsheetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flowsheet = Flowsheet.load(EXAMPLE)
        cls.result = solve_flowsheet(cls.flowsheet)
        cls.case = constructed_case()

    def test_structure(self):
        fs = self.flowsheet
        self.assertEqual(fs.name, "reactor-flash-recycle")
        self.assertEqual(fs.order, ("mixer", "reactor", "drum", "purge-split"))
        self.assertEqual(fs.products, ("liquid", "purge"))
        self.assertEqual(fs.components, ("A", "I", "B"))
        self.assertEqual(fs.tear.streams, ("recycle",))

    def test_converges_to_stated_tolerance(self):
        r = self.result
        self.assertIsInstance(r, FlowsheetResult)
        self.assertEqual(r.method, "wegstein")
        self.assertEqual(r.tol, 1e-10)
        self.assertLessEqual(r.residual, 1e-10)
        self.assertEqual(r.residual, r.history[-1])
        self.assertEqual(len(r.history), r.iterations)
        self.assertLessEqual(r.iterations, 100)

    def test_matches_constructed_answer(self):
        for stream in ("reactor-in", "reactor-out", "vapour", "liquid", "recycle", "purge"):
            for c, expected in self.case[stream].items():
                with self.subTest(stream=stream, component=c):
                    self.assertAlmostEqual(self.result.streams[stream].flows[c], float(expected), delta=VALUE_TOL)

    def test_reaction_extent_and_overall_conversion(self):
        # Reacted A = M_A Da / (1 + Da) = (33/5) (23/10) / (33/10) = 23/5; overall conversion 23/5 / 28/5 = 23/28.
        gen = self.result.total_generation()
        self.assertAlmostEqual(gen["A"], -4.6, delta=VALUE_TOL)
        self.assertAlmostEqual(gen["B"], 4.6, delta=VALUE_TOL)
        self.assertEqual(gen["I"], 0.0)
        self.assertAlmostEqual(-gen["A"] / self.result.streams["feed"].flows["A"], 23 / 28, delta=VALUE_TOL)

    def test_every_unit_balance_closes(self):
        for unit in self.result.units:
            for c, residual in self.result.unit_balance(unit).items():
                with self.subTest(unit=unit, component=c):
                    self.assertLessEqual(abs(residual), BALANCE_TOL)

    def test_overall_balance_closes(self):
        for c, residual in self.result.overall_balance().items():
            with self.subTest(component=c):
                self.assertLessEqual(abs(residual), BALANCE_TOL)
        feed = self.result.streams["feed"].total_flow
        out = sum(self.result.streams[s].total_flow for s in self.result.products)
        self.assertAlmostEqual(feed, out, delta=BALANCE_TOL)  # A -> B keeps the total moles

    def test_streams_keep_temperature_and_pressure(self):
        for name, s in self.result.streams.items():
            with self.subTest(stream=name):
                self.assertEqual(s.temperature, 330.0)
                self.assertEqual(s.pressure, 2e5)

    def test_direct_substitution_reaches_the_same_answer_more_slowly(self):
        direct = solve_flowsheet(self.flowsheet, method="direct")
        self.assertEqual(direct.method, "direct")
        self.assertLessEqual(direct.residual, 1e-10)
        self.assertLess(self.result.iterations, direct.iterations)
        for c, expected in self.case["recycle"].items():
            self.assertAlmostEqual(direct.streams["recycle"].flows[c], float(expected), delta=VALUE_TOL)

    def test_other_initial_guesses_reach_the_same_answer(self):
        guesses = ({"A": 20.0, "I": 20.0, "B": 20.0}, {"A": 0.0, "I": 10.0, "B": 0.0})
        for flows in guesses:
            for method in ("direct", "wegstein"):
                spec = example_spec()
                spec["tear"]["initial"] = {"recycle": {"flows": flows, "temperature": 330.0, "pressure": 2e5}}
                spec["tear"]["method"] = method
                with self.subTest(guess=flows, method=method):
                    r = solve_flowsheet(spec)
                    for c, expected in self.case["recycle"].items():
                        self.assertAlmostEqual(r.streams["recycle"].flows[c], float(expected), delta=VALUE_TOL)

    def test_tear_upstream_of_the_flash_with_initial_guess(self):
        # Tearing reactor-out closes the same loop; the flash runs first, so the tear needs a guess with flow.
        guesses = ({"A": 1.0, "I": 1.0, "B": 1.0}, {"A": 5.6, "I": 2.4, "B": 0.0})
        for flows in guesses:
            for method in ("direct", "wegstein"):
                spec = example_spec()
                spec["tear"] = {
                    "streams": ["reactor-out"],
                    "initial": {"reactor-out": {"flows": flows, "temperature": 330.0, "pressure": 2e5}},
                    "method": method,
                }
                with self.subTest(guess=flows, method=method):
                    fs = Flowsheet.from_dict(spec)
                    self.assertEqual(fs.order, ("drum", "purge-split", "mixer", "reactor"))
                    r = solve_flowsheet(fs)
                    self.assertLessEqual(r.residual, 1e-10)
                    for stream in ("reactor-in", "reactor-out", "vapour", "liquid", "recycle", "purge"):
                        for c, expected in self.case[stream].items():
                            self.assertAlmostEqual(r.streams[stream].flows[c], float(expected), delta=VALUE_TOL)
                    for c, residual in r.overall_balance().items():
                        self.assertLessEqual(abs(residual), BALANCE_TOL)
                    for unit in r.units:
                        for c, residual in r.unit_balance(unit).items():
                            self.assertLessEqual(abs(residual), BALANCE_TOL)

    def test_result_exports_as_json(self):
        data = json.loads(json.dumps(self.result.to_dict()))
        self.assertEqual(data["name"], "reactor-flash-recycle")
        self.assertEqual(data["products"], ["liquid", "purge"])
        self.assertEqual(data["units"]["drum"]["outlets"], ["vapour", "liquid"])
        self.assertAlmostEqual(data["streams"]["liquid"]["flows"]["B"], 4.5, delta=VALUE_TOL)
        self.assertAlmostEqual(data["units"]["reactor"]["generation"]["B"], 4.6, delta=VALUE_TOL)

    def test_from_json_matches_load(self):
        fs = Flowsheet.from_json(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(fs, self.flowsheet)


class LinearLoopTest(unittest.TestCase):
    def test_matches_closed_form(self):
        r = solve_flowsheet(linear_spec(0.2))
        self.assertAlmostEqual(r.streams["recycle"].flows["A"], 20 / 3, delta=VALUE_TOL)
        self.assertAlmostEqual(r.streams["recycle"].flows["B"], 100 / 3, delta=1e-6)
        # Purge = p * reactor outlet = (5/3, 25/3); overall conversion (10 - 5/3) / 10 = 5/6.
        self.assertAlmostEqual(r.streams["purge"].flows["A"], 5 / 3, delta=VALUE_TOL)
        self.assertAlmostEqual(r.streams["purge"].flows["B"], 25 / 3, delta=1e-6)
        for c, residual in r.overall_balance().items():
            self.assertLessEqual(abs(residual), BALANCE_TOL)

    def test_wegstein_needs_far_fewer_passes(self):
        # Measured: 5 passes with Wegstein, 98 with direct substitution (the loop gain of the total moles is 0.8).
        wegstein = solve_flowsheet(linear_spec(0.2))
        direct = solve_flowsheet(linear_spec(0.2), method="direct", max_iter=500)
        self.assertLessEqual(wegstein.iterations, 10)
        self.assertGreater(direct.iterations, 5 * wegstein.iterations)
        self.assertAlmostEqual(direct.streams["recycle"].flows["B"], 100 / 3, delta=1e-6)

    def test_max_iter_guard_raises(self):
        # With p = 1/10 the total moles converge at rate 0.9: 100 passes of direct substitution are not enough.
        with self.assertRaises(ConvergenceError) as ctx:
            solve_flowsheet(linear_spec(0.1, method="direct", max_iter=100))
        err = ctx.exception
        self.assertEqual(err.iterations, 100)
        self.assertGreater(err.residual, 1e-10)
        self.assertIn("did not converge in 100 passes", str(err))
        # Wegstein converges on the same loop within the default limit; R_A = 90/11, R_B = 900/11.
        r = solve_flowsheet(linear_spec(0.1))
        self.assertAlmostEqual(r.streams["recycle"].flows["A"], 90 / 11, delta=VALUE_TOL)
        self.assertAlmostEqual(r.streams["recycle"].flows["B"], 900 / 11, delta=1e-6)

    def test_loop_without_purge_has_no_steady_state(self):
        # Everything is recycled, so the moles pile up by 10 mol/s every pass and the residual never falls.
        for method in ("direct", "wegstein"):
            with self.subTest(method=method), self.assertRaises(ConvergenceError):
                solve_flowsheet(linear_spec(0.0, method=method, max_iter=50))


class WegsteinStepTest(unittest.TestCase):
    def test_linear_function_lands_on_fixed_point(self):
        # g(x) = 0.45 x + 4.5 has the fixed point 4.5 / 0.55 = 90/11; s = 0.45, q = -0.45 / 0.55, inside [-5, 0].
        g = lambda x: 0.45 * x + 4.5  # noqa: E731
        x0, x1 = 0.0, g(0.0)
        (x2,) = _wegstein_step([x1], [g(x1)], [x0], [g(x0)], -5.0, 0.0)
        self.assertAlmostEqual(x2, 90 / 11, places=12)

    def test_q_is_bounded(self):
        # g(x) = 0.9 x + 1: s = 0.9 gives q = -9, bounded to -5: x2 = -5 * 1 + 6 * 1.9 = 6.4 (fixed point 10).
        g = lambda x: 0.9 * x + 1.0  # noqa: E731
        (x2,) = _wegstein_step([1.0], [g(1.0)], [0.0], [g(0.0)], -5.0, 0.0)
        self.assertAlmostEqual(x2, 6.4, places=12)

    def test_unchanged_variable_takes_plain_substitution(self):
        (x2,) = _wegstein_step([3.0], [4.0], [3.0], [3.5], -5.0, 0.0)
        self.assertEqual(x2, 4.0)


class NoRecycleTest(unittest.TestCase):
    def test_single_pass(self):
        # CSTR with Da = 1: X = 1/2, so the outlet is A 5, B 5; the flash is the binary equal split of test_flash.
        spec = {
            "feeds": {"feed": {"flows": {"A": 10.0}, "temperature": 350.0, "pressure": 1.5e5}},
            "units": [
                {"name": "reactor", "type": "cstr", "inlets": ["feed"], "outlets": ["s1"],
                 "params": {"reactant": "A", "product": "B", "rate_constant": 0.01, "volume": 2.0,
                            "volumetric_flow": 0.02}},
                {"name": "drum", "type": "flash", "inlets": ["s1"], "outlets": ["vap", "liq"],
                 "params": {"k_values": {"A": 2.0, "B": 0.5}}},
            ],
        }
        r = solve_flowsheet(spec)
        self.assertEqual(r.iterations, 1)
        self.assertEqual(r.residual, 0.0)
        self.assertEqual(r.products, ("vap", "liq"))
        self.assertAlmostEqual(r.streams["s1"].flows["A"], 5.0, places=12)
        self.assertAlmostEqual(r.streams["vap"].total_flow, 5.0, delta=1e-9)
        self.assertAlmostEqual(r.streams["liq"].flows["B"], 10 / 3, delta=1e-9)

    def test_pfr_unit(self):
        # PFR with k tau = ln 2: X = 1/2.
        spec = {
            "feeds": {"feed": {"flows": {"A": 4.0}}},
            "units": [
                {"name": "reactor", "type": "pfr", "inlets": ["feed"], "outlets": ["out"],
                 "params": {"reactant": "A", "product": "B", "rate_constant": math.log(2) / 100, "volume": 2.0,
                            "volumetric_flow": 0.02}},
            ],
        }
        r = solve_flowsheet(spec)
        self.assertAlmostEqual(r.streams["out"].flows["A"], 2.0, places=12)
        self.assertAlmostEqual(r.units["reactor"].generation["B"], 2.0, places=12)


class SpecErrorTest(unittest.TestCase):
    def assert_rejected(self, spec, fragment):
        with self.assertRaises(ValueError) as ctx:
            Flowsheet.from_dict(spec)
        self.assertIn(fragment, str(ctx.exception))

    def test_loop_without_tear_stream(self):
        spec = example_spec()
        del spec["tear"]
        self.assert_rejected(spec, "recycle loop that no tear stream breaks")

    def test_unknown_unit_type(self):
        spec = example_spec()
        spec["units"][2]["type"] = "distillation"
        self.assert_rejected(spec, "unknown type 'distillation'")

    def test_unknown_and_missing_params(self):
        spec = example_spec()
        spec["units"][1]["params"]["temprature"] = 330.0
        self.assert_rejected(spec, "unknown params ['temprature']")
        spec = example_spec()
        del spec["units"][1]["params"]["volume"]
        self.assert_rejected(spec, "missing params ['volume']")

    def test_unknown_top_level_key(self):
        spec = example_spec()
        spec["stream"] = {}
        self.assert_rejected(spec, "unknown keys ['stream']")

    def test_stream_with_two_producers(self):
        spec = example_spec()
        spec["units"][3]["outlets"] = ["liquid", "recycle"]
        self.assert_rejected(spec, "outlet of both 'drum' and 'purge-split'")

    def test_undefined_inlet(self):
        spec = example_spec()
        spec["units"][0]["inlets"] = ["feed", "recycel"]
        self.assert_rejected(spec, "inlet 'recycel' of unit 'mixer'")

    def test_wrong_outlet_count(self):
        spec = example_spec()
        spec["units"][2]["outlets"] = ["vapour"]
        self.assert_rejected(spec, "needs 2 outlets")

    def test_tear_stream_must_be_internal(self):
        spec = example_spec()
        spec["tear"]["streams"] = ["feed"]
        self.assert_rejected(spec, "tear stream 'feed'")

    def test_bad_tear_settings(self):
        for key, value, fragment in (
            ("method", "newton", "tear method"),
            ("tol", 0.0, "tear tol"),
            ("max_iter", 0, "tear max_iter"),
            ("q_max", 1.5, "q_min <= q_max < 1"),
        ):
            spec = example_spec()
            spec["tear"][key] = value
            with self.subTest(key=key):
                self.assert_rejected(spec, fragment)

    def test_initial_guess_for_a_stream_that_is_not_torn(self):
        spec = example_spec()
        spec["tear"]["initial"] = {"purge": {"flows": {"A": 1.0}}}
        self.assert_rejected(spec, "not a tear stream")

    def test_negative_feed_flow(self):
        spec = example_spec()
        spec["feeds"]["feed"]["flows"]["A"] = -1.0
        self.assert_rejected(spec, "negative")

    def test_unit_error_names_the_unit(self):
        # The recycle guess at 300 K meets a 330 K feed in the mixer, which needs one temperature.
        spec = example_spec()
        spec["tear"]["initial"] = {"recycle": {"flows": {"A": 1.0}, "temperature": 300.0, "pressure": 2e5}}
        with self.assertRaises(ValueError) as ctx:
            solve_flowsheet(spec)
        self.assertIn("unit 'mixer' (mixer)", str(ctx.exception))

    def test_tear_upstream_of_the_flash_without_guess_says_so(self):
        # A zero first guess reaches the flash as an empty feed; the error names the unit and the unguessed tear.
        for tear in ("reactor-out", "reactor-in"):
            spec = example_spec()
            spec["tear"]["streams"] = [tear]
            with self.subTest(tear=tear):
                with self.assertRaises(ValueError) as ctx:
                    solve_flowsheet(spec)
                message = str(ctx.exception)
                self.assertIn("unit 'drum' (flash)", message)
                self.assertIn(f"tear streams [{tear!r}] start at zero flow", message)
                self.assertIn("tear.initial", message)

    def test_param_of_wrong_type_names_the_unit(self):
        spec = example_spec()
        spec["units"][1]["params"]["volume"] = "2.0"
        with self.assertRaises(ValueError) as ctx:
            solve_flowsheet(spec)
        self.assertIn("unit 'reactor' (cstr)", str(ctx.exception))

    def test_build_from_python_objects(self):
        # Hand-multiplied: 0.25 * (6, 4) = (1.5, 1.0).
        fs = Flowsheet.build(
            feeds={"feed": Stream(flows={"A": 6.0, "B": 4.0})},
            units=[UnitSpec("split", "splitter", ("feed",), ("a", "b"), {"fractions": [0.25, 0.75]})],
        )
        r = solve_flowsheet(fs)
        self.assertEqual(r.streams["a"].flows, {"A": 1.5, "B": 1.0})
        with self.assertRaises(ValueError):
            Flowsheet.build(feeds={"feed": Stream(flows={"A": 1.0})}, units=[])


if __name__ == "__main__":
    unittest.main()
