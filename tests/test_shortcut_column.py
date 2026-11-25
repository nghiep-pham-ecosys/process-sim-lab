"""Tests for the shortcut (Fenske-Underwood-Gilliland) distillation column.

Check cases:

- Textbook case: P. C. Wankat, Separation Process Engineering, 5th ed., Examples 7-1 and 7-2. Saturated vapour feed
  (q = 0) of 40 % benzene, 30 % toluene, 30 % cumene, 100 kmol/h; alpha = (2.25, 1.0, 0.21) against toluene; light
  key toluene with 95 % to the distillate, heavy key cumene with 98 % to the bottoms. Printed answers: benzene 99.85 %
  to the distillate, D = 0.6904 F, x_D = (0.5785, 0.4128, 0.0087), x_B = (0.001938, 0.0485, 0.9496),
  L_min = 46.00 kmol/h and (L / D)_min = 0.6663. The book rounds to the printed digits (x_B of benzene uses the rounded
  99.85 %, its toluene value is 1.5 / 30.96 = 0.04845 printed as 0.0485, and its theta is rounded), so the tolerances
  below are half a unit in the last printed digit, 1e-4 for the three-digit toluene value, 2e-5 for the benzene value,
  and 0.1 % for L_min and (L / D)_min. Flows here are in mol/s; the method depends only on ratios, so the basis does
  not matter. N_min is hand-checked: ln[(0.95 / 0.05) (0.98 / 0.02)] / ln(1 / 0.21) = ln(931) / ln(4.7619) = 4.3804.
- Binary case with a closed form. alpha = (2, 1), z = (0.5, 0.5), 99 % recovery of each key, so x_D = 0.99. Fenske:
  N_min = 2 ln 99 / ln 2 = 13.2587. The minimum reflux of a binary is set by the pinch where the operating line meets
  the equilibrium curve on the q-line (McCabe-Thiele), independent of Underwood:
  q = 1: pinch x* = z = 0.5, y* = 2/3, R_min = (x_D - y*) / (y* - x*) = (0.99 - 2/3) / (1/6) = 1.94; theta = 4/3.
  q = 0: pinch y* = z = 0.5, x* = 1/3, R_min = (0.99 - 0.5) / (0.5 - 1/3) = 2.94; theta = 3/2.
- Gilliland curve: the Molokanov equation by hand at X = 0.5: (1 + 27.2) / (11 + 58.6) = 0.405172,
  (X - 1) / sqrt(X) = -0.707107, Y = 1 - exp(-0.286500) = 0.249113; its end points Y(0) = 1 and Y(1) = 0; and it stays
  within 0.025 of Eduljee's independent fit of the same chart, Y = 0.75 (1 - X^0.5668) (H. E. Eduljee, "Equations
  replace Gilliland plot", Hydrocarbon Processing 54(9), 1975), for X in [0.01, 0.9].
"""

import math
import unittest

from process_sim_lab import Stream
from process_sim_lab.units import ShortcutColumnResult, shortcut_column
from process_sim_lab.units.shortcut_column import fenske_minimum_stages, molokanov_y

TOL = 1e-9  # closed-form binary values; the Underwood root is found to float resolution

WANKAT_FEED = Stream(flows={"benzene": 40.0, "toluene": 30.0, "cumene": 30.0}, temperature=360.0, pressure=101325.0)
WANKAT_ALPHA = {"benzene": 2.25, "toluene": 1.0, "cumene": 0.21}


def wankat(**changes):
    args = dict(
        relative_volatilities=WANKAT_ALPHA,
        light_key="toluene",
        heavy_key="cumene",
        light_key_recovery=0.95,
        heavy_key_recovery=0.98,
        q=0.0,
        reflux_ratio=2.0,
    )
    args.update(changes)
    return shortcut_column(WANKAT_FEED, **args)


def binary(q, **reflux):
    feed = Stream(flows={"A": 5.0, "B": 5.0})
    return shortcut_column(
        feed,
        relative_volatilities={"A": 2.0, "B": 1.0},
        light_key="A",
        heavy_key="B",
        light_key_recovery=0.99,
        heavy_key_recovery=0.99,
        q=q,
        **(reflux or {"reflux_factor": 1.5}),
    )


class TextbookCaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = wankat()
        cls.d = cls.r.distillate.total_flow
        cls.b = cls.r.bottoms.total_flow

    def test_result_type(self):
        self.assertIsInstance(self.r, ShortcutColumnResult)

    def test_minimum_stages(self):
        self.assertAlmostEqual(self.r.minimum_stages, math.log(931.0) / math.log(1.0 / 0.21), places=12)
        self.assertAlmostEqual(self.r.minimum_stages, 4.3804, delta=5e-5)

    def test_non_key_split_and_product_rates(self):
        self.assertAlmostEqual(self.r.distillate_fraction["benzene"], 0.9985, delta=5e-5)
        self.assertEqual(self.r.distillate_fraction["toluene"], 0.95)
        self.assertAlmostEqual(self.r.distillate_fraction["cumene"], 0.02, places=15)
        self.assertAlmostEqual(self.d / 100.0, 0.6904, delta=5e-5)
        self.assertAlmostEqual(self.b / 100.0, 0.3096, delta=5e-5)

    def test_distillate_composition(self):
        for c, x in (("benzene", 0.5785), ("toluene", 0.4128), ("cumene", 0.0087)):
            with self.subTest(component=c):
                self.assertAlmostEqual(self.r.distillate.flows[c] / self.d, x, delta=5e-5)

    def test_bottoms_composition(self):
        for c, x, tol in (("benzene", 0.001938, 2e-5), ("toluene", 0.0485, 1e-4), ("cumene", 0.9496, 5e-5)):
            with self.subTest(component=c):
                self.assertAlmostEqual(self.r.bottoms.flows[c] / self.b, x, delta=tol)

    def test_minimum_reflux(self):
        self.assertAlmostEqual(self.r.minimum_reflux, 0.6663, delta=0.001 * 0.6663)
        self.assertAlmostEqual(self.r.minimum_reflux * self.d, 46.00, delta=0.001 * 46.00)
        self.assertTrue(0.21 < self.r.theta < 1.0)

    def test_theta_solves_underwood(self):
        z = {"benzene": 0.4, "toluene": 0.3, "cumene": 0.3}
        total = sum(WANKAT_ALPHA[c] * z[c] / (WANKAT_ALPHA[c] - self.r.theta) for c in z)
        self.assertAlmostEqual(total, 1.0 - 0.0, delta=1e-9)

    def test_gilliland_stages(self):
        r = self.r
        self.assertEqual(r.reflux_ratio, 2.0)
        self.assertAlmostEqual(r.gilliland_x, (2.0 - r.minimum_reflux) / 3.0, places=15)
        self.assertAlmostEqual(r.gilliland_y, molokanov_y(r.gilliland_x), places=15)
        self.assertAlmostEqual((r.stages - r.minimum_stages) / (r.stages + 1.0), r.gilliland_y, places=12)
        self.assertGreater(r.stages, r.minimum_stages)

    def test_material_balance_closes(self):
        for c, f in WANKAT_FEED.flows.items():
            with self.subTest(component=c):
                self.assertAlmostEqual(self.r.distillate.flows[c] + self.r.bottoms.flows[c], f, places=12)

    def test_products_carry_the_feed_state(self):
        for s in (self.r.distillate, self.r.bottoms):
            self.assertEqual((s.temperature, s.pressure), (360.0, 101325.0))

    def test_volatility_reference_does_not_matter(self):
        rebased = {c: a / 0.21 for c, a in WANKAT_ALPHA.items()}  # cumene as the reference
        r = wankat(relative_volatilities=rebased)
        self.assertAlmostEqual(r.minimum_stages, self.r.minimum_stages, places=12)
        self.assertAlmostEqual(r.minimum_reflux, self.r.minimum_reflux, places=10)
        self.assertAlmostEqual(r.theta, self.r.theta / 0.21, places=9)


class BinaryClosedFormTest(unittest.TestCase):
    def test_saturated_liquid_feed(self):
        r = binary(1.0)
        self.assertAlmostEqual(r.minimum_stages, 2.0 * math.log(99.0) / math.log(2.0), delta=TOL)
        self.assertAlmostEqual(r.theta, 4.0 / 3.0, delta=TOL)
        self.assertAlmostEqual(r.minimum_reflux, 1.94, delta=TOL)
        self.assertAlmostEqual(r.reflux_ratio, 1.5 * 1.94, delta=TOL)
        self.assertAlmostEqual(r.distillate.flows["A"], 4.95, delta=TOL)
        self.assertAlmostEqual(r.distillate.flows["B"], 0.05, delta=TOL)

    def test_saturated_vapour_feed(self):
        r = binary(0.0)
        self.assertAlmostEqual(r.theta, 1.5, delta=TOL)
        self.assertAlmostEqual(r.minimum_reflux, 2.94, delta=TOL)

    def test_colder_feed_needs_less_reflux(self):
        rmins = [binary(q).minimum_reflux for q in (-0.5, 0.0, 0.5, 1.0, 1.5)]
        self.assertEqual(rmins, sorted(rmins, reverse=True))

    def test_more_reflux_fewer_stages(self):
        stages = [binary(1.0, reflux_factor=f).stages for f in (1.05, 1.2, 1.5, 2.0, 5.0)]
        self.assertEqual(stages, sorted(stages, reverse=True))
        self.assertGreater(stages[-1], binary(1.0).minimum_stages)

    def test_reflux_ratio_and_factor_agree(self):
        a = binary(1.0, reflux_factor=1.5)
        b = binary(1.0, reflux_ratio=1.5 * 1.94)
        self.assertAlmostEqual(a.stages, b.stages, delta=1e-9)


class GillilandTest(unittest.TestCase):
    def test_hand_value(self):
        self.assertAlmostEqual(molokanov_y(0.5), 0.249113, delta=1e-6)

    def test_end_points(self):
        self.assertEqual(molokanov_y(0.0), 1.0)
        self.assertEqual(molokanov_y(1.0), 0.0)

    def test_close_to_eduljee_fit(self):
        for i in range(1, 91):
            x = i / 100.0
            with self.subTest(x=x):
                self.assertAlmostEqual(molokanov_y(x), 0.75 * (1.0 - x**0.5668), delta=0.025)

    def test_falls_with_x(self):
        ys = [molokanov_y(i / 50.0) for i in range(51)]
        self.assertEqual(ys, sorted(ys, reverse=True))

    def test_x_out_of_range(self):
        for x in (-0.1, 1.1):
            with self.assertRaises(ValueError):
                molokanov_y(x)


class FenskeTest(unittest.TestCase):
    def test_symmetric_binary(self):
        self.assertAlmostEqual(fenske_minimum_stages(0.99, 0.99, 2.0), math.log(9801.0) / math.log(2.0), places=12)

    def test_bad_inputs(self):
        for args in ((1.0, 0.9, 2.0), (0.9, 0.0, 2.0), (0.9, 0.9, 1.0), (0.4, 0.5, 2.0), (0.9, 0.9, math.inf)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                fenske_minimum_stages(*args)


class EdgeCaseTest(unittest.TestCase):
    def test_zero_flow_component_passes_through_at_zero(self):
        feed = Stream(flows={"A": 5.0, "B": 5.0, "C": 0.0})
        r = shortcut_column(feed, relative_volatilities={"A": 2.0, "B": 1.0}, light_key="A", heavy_key="B",
                            light_key_recovery=0.99, heavy_key_recovery=0.99, reflux_factor=1.5)
        self.assertEqual((r.distillate.flows["C"], r.bottoms.flows["C"], r.distillate_fraction["C"]), (0.0, 0.0, 0.0))

    def test_very_light_and_very_heavy_non_keys_do_not_overflow(self):
        feed = Stream(flows={"L": 1.0, "A": 5.0, "B": 5.0, "H": 1.0})
        r = shortcut_column(feed, relative_volatilities={"L": 1e6, "A": 2.0, "B": 1.0, "H": 1e-6}, light_key="A",
                            heavy_key="B", light_key_recovery=0.99, heavy_key_recovery=0.99, reflux_factor=1.5)
        self.assertEqual(r.distillate_fraction["L"], 1.0)
        self.assertLess(r.distillate_fraction["H"], 1e-50)
        self.assertTrue(math.isfinite(r.stages))


class BadInputTest(unittest.TestCase):
    def assert_rejected(self, fragment, **changes):
        with self.assertRaises(ValueError) as ctx:
            wankat(**changes)
        self.assertIn(fragment, str(ctx.exception))

    def test_reflux_given_twice_or_not_at_all(self):
        self.assert_rejected("exactly one", reflux_factor=1.3)
        self.assert_rejected("exactly one", reflux_ratio=None)

    def test_reflux_below_minimum(self):
        self.assert_rejected("> R_min", reflux_ratio=0.5)
        self.assert_rejected("reflux_factor", reflux_ratio=None, reflux_factor=1.0)

    def test_reflux_too_close_to_minimum(self):
        for factor in (1.0000000000000002, 1.000001, 1.00001):
            with self.subTest(reflux_factor=factor):
                self.assert_rejected("too close to R_min", reflux_ratio=None, reflux_factor=factor)
        self.assertTrue(math.isfinite(wankat(reflux_ratio=None, reflux_factor=1.001).stages))

    def test_keys(self):
        self.assert_rejected("must differ", heavy_key="toluene")
        self.assert_rejected("more volatile", light_key="cumene", heavy_key="toluene")
        self.assert_rejected("between the keys", light_key="benzene", heavy_key="cumene")
        self.assert_rejected("no flow", light_key="xylene")

    def test_volatilities(self):
        self.assert_rejected("no relative volatility", relative_volatilities={"toluene": 1.0, "cumene": 0.21})
        self.assert_rejected("finite and > 0", relative_volatilities={**WANKAT_ALPHA, "benzene": 0.0})

    def test_recoveries(self):
        self.assert_rejected("(0, 1)", light_key_recovery=1.0)
        self.assert_rejected("> 1 for a separation", light_key_recovery=0.5, heavy_key_recovery=0.5)

    def test_q_and_empty_feed(self):
        self.assert_rejected("q must be finite", q=math.nan)
        with self.assertRaises(ValueError):
            shortcut_column(Stream(flows={"A": 0.0}), relative_volatilities={"A": 2.0}, light_key="A",
                            heavy_key="B", light_key_recovery=0.9, heavy_key_recovery=0.9, reflux_factor=1.3)


if __name__ == "__main__":
    unittest.main()
