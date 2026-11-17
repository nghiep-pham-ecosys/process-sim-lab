"""Tests for the isothermal flash.

The check cases are built so the answer is known exactly, not taken from a textbook table:

- Binary feed. Rachford-Rice with two components is linear in psi after clearing denominators:
  z1 a1 (1 + psi a2) + z2 a2 (1 + psi a1) = 0 with a_i = K_i - 1, so psi = -(z1 a1 + z2 a2) / (a1 a2).
- Ternary feed. Pick psi, x and K with sum x = sum K x = 1, then set z_i = x_i (1 + psi (K_i - 1)).
"""

import math
import unittest

from process_sim_lab import Stream
from process_sim_lab.units import FlashResult, isothermal_flash
from process_sim_lab.units.flash import rachford_rice

TOL = 1e-9  # the issue asks for 1e-6; bisection reaches 1e-12


def binary_psi(z1, k1, k2):
    """Closed-form Rachford-Rice root for a binary feed."""
    a1, a2 = k1 - 1.0, k2 - 1.0
    return -(z1 * a1 + (1.0 - z1) * a2) / (a1 * a2)


class BinaryFlashTest(unittest.TestCase):
    def test_equal_split_matches_closed_form(self):
        # z = (0.5, 0.5), K = (2, 0.5): psi = -(0.5 - 0.25) / (-0.5) = 0.5, x = (1/3, 2/3), y = (2/3, 1/3).
        feed = Stream(flows={"A": 5.0, "B": 5.0}, temperature=350.0, pressure=1.5e5)
        r = isothermal_flash(feed, k_values={"A": 2.0, "B": 0.5})
        self.assertIsInstance(r, FlashResult)
        self.assertEqual(r.phase, "two-phase")
        self.assertAlmostEqual(r.vapour_fraction, 0.5, delta=TOL)
        self.assertAlmostEqual(r.vapour_fraction, binary_psi(0.5, 2.0, 0.5), delta=TOL)
        self.assertAlmostEqual(r.x["A"], 1.0 / 3.0, delta=TOL)
        self.assertAlmostEqual(r.x["B"], 2.0 / 3.0, delta=TOL)
        self.assertAlmostEqual(r.y["A"], 2.0 / 3.0, delta=TOL)
        self.assertAlmostEqual(r.y["B"], 1.0 / 3.0, delta=TOL)
        self.assertAlmostEqual(r.vapour.total_flow, 5.0, delta=TOL)
        self.assertAlmostEqual(r.liquid.total_flow, 5.0, delta=TOL)
        self.assertGreater(r.iterations, 0)

    def test_unequal_split_matches_closed_form(self):
        # z = (0.4, 0.6), K = (3, 0.2): psi = -(0.8 - 0.48) / (-1.6) = 0.2, x = (2/7, 5/7), y = (6/7, 1/7).
        feed = Stream(flows={"A": 4.0, "B": 6.0})
        r = isothermal_flash(feed, k_values={"A": 3.0, "B": 0.2})
        self.assertAlmostEqual(r.vapour_fraction, 0.2, delta=TOL)
        self.assertAlmostEqual(r.x["A"], 2.0 / 7.0, delta=TOL)
        self.assertAlmostEqual(r.x["B"], 5.0 / 7.0, delta=TOL)
        self.assertAlmostEqual(r.y["A"], 6.0 / 7.0, delta=TOL)
        self.assertAlmostEqual(r.y["B"], 1.0 / 7.0, delta=TOL)
        self.assertAlmostEqual(r.vapour.flows["A"], 2.0 * 6.0 / 7.0, delta=TOL)
        self.assertAlmostEqual(r.liquid.flows["B"], 8.0 * 5.0 / 7.0, delta=TOL)


class TernaryFlashTest(unittest.TestCase):
    def test_constructed_case(self):
        # psi = 0.25, x = (0.1, 0.3, 0.6), K = (5, 1, 1/3) -> y = (0.5, 0.3, 0.2), z = (0.2, 0.3, 0.5).
        feed = Stream(flows={"A": 2.0, "B": 3.0, "C": 5.0}, temperature=320.0, pressure=3e5)
        k = {"A": 5.0, "B": 1.0, "C": 1.0 / 3.0}
        r = isothermal_flash(feed, k_values=k)
        self.assertAlmostEqual(r.vapour_fraction, 0.25, delta=TOL)
        for c, xi, yi in (("A", 0.1, 0.5), ("B", 0.3, 0.3), ("C", 0.6, 0.2)):
            with self.subTest(component=c):
                self.assertAlmostEqual(r.x[c], xi, delta=TOL)
                self.assertAlmostEqual(r.y[c], yi, delta=TOL)
                self.assertAlmostEqual(r.y[c], k[c] * r.x[c], delta=TOL)
        self.assertAlmostEqual(rachford_rice({"A": 0.2, "B": 0.3, "C": 0.5}, k, r.vapour_fraction), 0.0, delta=TOL)

    def test_conserves_moles_and_keeps_state(self):
        feed = Stream(flows={"A": 2.0, "B": 3.0, "C": 5.0, "N": 0.0}, temperature=320.0, pressure=3e5)
        r = isothermal_flash(feed, k_values={"A": 5.0, "B": 1.0, "C": 1.0 / 3.0})
        for c, f in feed.flows.items():
            with self.subTest(component=c):
                self.assertAlmostEqual(r.vapour.flows[c] + r.liquid.flows[c], f, places=12)
        self.assertEqual(r.vapour.flows["N"], 0.0)
        self.assertEqual(r.x["N"], 0.0)
        self.assertAlmostEqual(sum(r.x.values()), 1.0, delta=TOL)
        self.assertAlmostEqual(sum(r.y.values()), 1.0, delta=TOL)
        for s in (r.vapour, r.liquid):
            self.assertEqual(s.temperature, 320.0)
            self.assertEqual(s.pressure, 3e5)


class SinglePhaseTest(unittest.TestCase):
    def test_subcooled_feed_is_all_liquid(self):
        # sum z K = 0.5 * 0.8 + 0.5 * 0.3 < 1.
        feed = Stream(flows={"A": 1.0, "B": 1.0})
        r = isothermal_flash(feed, k_values={"A": 0.8, "B": 0.3})
        self.assertEqual(r.phase, "liquid")
        self.assertEqual(r.vapour_fraction, 0.0)
        self.assertEqual(r.iterations, 0)
        self.assertEqual(r.liquid.flows, {"A": 1.0, "B": 1.0})
        self.assertEqual(r.vapour.total_flow, 0.0)
        self.assertEqual(r.x, {"A": 0.5, "B": 0.5})
        # Incipient vapour: K z / sum K z = (0.4, 0.15) / 0.55.
        self.assertAlmostEqual(r.y["A"], 0.4 / 0.55, places=12)

    def test_superheated_feed_is_all_vapour(self):
        # sum z / K = 0.5 / 2 + 0.5 / 4 < 1.
        feed = Stream(flows={"A": 1.0, "B": 1.0})
        r = isothermal_flash(feed, k_values={"A": 2.0, "B": 4.0})
        self.assertEqual(r.phase, "vapour")
        self.assertEqual(r.vapour_fraction, 1.0)
        self.assertEqual(r.vapour.flows, {"A": 1.0, "B": 1.0})
        self.assertEqual(r.liquid.total_flow, 0.0)
        self.assertEqual(r.y, {"A": 0.5, "B": 0.5})
        # Incipient liquid: (z / K) / sum (z / K) = (0.25, 0.125) / 0.375.
        self.assertAlmostEqual(r.x["A"], 2.0 / 3.0, places=12)

    def test_bubble_point_gives_psi_zero(self):
        # z = (1/3, 2/3), K = (2, 0.5): sum z K = 1, the feed is a saturated liquid.
        feed = Stream(flows={"A": 1.0, "B": 2.0})
        r = isothermal_flash(feed, k_values={"A": 2.0, "B": 0.5})
        self.assertAlmostEqual(r.vapour_fraction, 0.0, delta=TOL)
        self.assertAlmostEqual(r.y["A"], 2.0 / 3.0, delta=TOL)

    def test_dew_point_gives_psi_one(self):
        # z = (2/3, 1/3), K = (2, 0.5): sum z / K = 1, the feed is a saturated vapour.
        feed = Stream(flows={"A": 2.0, "B": 1.0})
        r = isothermal_flash(feed, k_values={"A": 2.0, "B": 0.5})
        self.assertAlmostEqual(r.vapour_fraction, 1.0, delta=TOL)
        self.assertAlmostEqual(r.x["A"], 1.0 / 3.0, delta=TOL)


class SweepTest(unittest.TestCase):
    def test_binary_sweep_matches_closed_form(self):
        k1, k2 = 2.5, 0.4
        # Two-phase window: bubble z1 = (1 - k2) / (k1 - k2) = 0.2857, dew z1 = k1 (1 - k2) / (k1 - k2) = 0.7143.
        for z1 in (0.3, 0.4, 0.5, 0.6, 0.7):
            with self.subTest(z1=z1):
                r = isothermal_flash(Stream(flows={"A": z1, "B": 1.0 - z1}), k_values={"A": k1, "B": k2})
                self.assertAlmostEqual(r.vapour_fraction, binary_psi(z1, k1, k2), delta=TOL)

    def test_vapour_fraction_rises_with_volatility(self):
        feed = Stream(flows={"A": 1.0, "B": 1.0})
        low = isothermal_flash(feed, k_values={"A": 1.5, "B": 0.5})
        high = isothermal_flash(feed, k_values={"A": 3.0, "B": 0.5})
        self.assertLess(low.vapour_fraction, high.vapour_fraction)


class BadInputTest(unittest.TestCase):
    def test_rejects_bad_inputs(self):
        feed = Stream(flows={"A": 1.0, "B": 1.0})
        bad_k = [
            {"A": 2.0},
            {"A": 2.0, "B": 0.0},
            {"A": 2.0, "B": -1.0},
            {"A": math.inf, "B": 0.5},
            {"A": math.nan, "B": 0.5},
        ]
        for k in bad_k:
            with self.subTest(k_values=k), self.assertRaises(ValueError):
                isothermal_flash(feed, k_values=k)
        with self.assertRaises(ValueError):
            isothermal_flash(Stream(flows={"A": 0.0}), k_values={"A": 2.0})
        with self.assertRaises(ValueError):
            isothermal_flash(feed, k_values={"A": 2.0, "B": 0.5}, tol=0.0)
        with self.assertRaises(ValueError):
            isothermal_flash(feed, k_values={"A": 2.0, "B": 0.5}, max_iter=0)

    def test_ignores_k_for_absent_components(self):
        feed = Stream(flows={"A": 5.0, "B": 5.0})
        r = isothermal_flash(feed, k_values={"A": 2.0, "B": 0.5, "Z": 9.0})
        self.assertAlmostEqual(r.vapour_fraction, 0.5, delta=TOL)
        self.assertNotIn("Z", r.x)


if __name__ == "__main__":
    unittest.main()
