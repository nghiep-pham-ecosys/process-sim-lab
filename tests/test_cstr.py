import unittest

from process_sim_lab import Stream
from process_sim_lab.units import isothermal_cstr_first_order


class IsothermalCSTRTest(unittest.TestCase):
    def setUp(self):
        self.feed = Stream(flows={"A": 10.0, "W": 50.0}, temperature=330.0, pressure=2e5)

    def test_matches_analytic_conversion(self):
        # k = 0.01 1/s, V = 2 m3, Q = 0.004 m3/s -> tau = 500 s, Da = 5, X = 5/6.
        r = isothermal_cstr_first_order(
            self.feed, reactant="A", product="B", rate_constant=0.01, volume=2.0, volumetric_flow=0.004
        )
        self.assertAlmostEqual(r.space_time, 500.0)
        self.assertAlmostEqual(r.damkohler, 5.0)
        self.assertAlmostEqual(r.conversion, 5.0 / 6.0, places=12)
        self.assertAlmostEqual(r.outlet.flows["A"], 10.0 / 6.0, places=12)
        self.assertAlmostEqual(r.outlet.flows["B"], 10.0 * 5.0 / 6.0, places=12)

    def test_conserves_moles_and_keeps_state(self):
        r = isothermal_cstr_first_order(
            self.feed, reactant="A", product="B", rate_constant=0.2, volume=1.0, volumetric_flow=0.01
        )
        self.assertAlmostEqual(r.outlet.total_flow, self.feed.total_flow, places=12)
        self.assertEqual(r.outlet.flows["W"], 50.0)
        self.assertEqual(r.outlet.temperature, 330.0)
        self.assertEqual(r.outlet.pressure, 2e5)

    def test_zero_rate_means_no_conversion(self):
        r = isothermal_cstr_first_order(
            self.feed, reactant="A", product="B", rate_constant=0.0, volume=1.0, volumetric_flow=0.01
        )
        self.assertEqual(r.conversion, 0.0)
        self.assertEqual(r.outlet.flows["B"], 0.0)

    def test_conversion_rises_with_volume(self):
        small = isothermal_cstr_first_order(
            self.feed, reactant="A", product="B", rate_constant=0.01, volume=1.0, volumetric_flow=0.01
        )
        large = isothermal_cstr_first_order(
            self.feed, reactant="A", product="B", rate_constant=0.01, volume=10.0, volumetric_flow=0.01
        )
        self.assertLess(small.conversion, large.conversion)
        self.assertLess(large.conversion, 1.0)

    def test_rejects_bad_inputs(self):
        cases = [
            dict(rate_constant=-1.0, volume=1.0, volumetric_flow=0.01),
            dict(rate_constant=0.1, volume=0.0, volumetric_flow=0.01),
            dict(rate_constant=0.1, volume=1.0, volumetric_flow=0.0),
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                isothermal_cstr_first_order(self.feed, reactant="A", product="B", **kwargs)
        with self.assertRaises(ValueError):
            isothermal_cstr_first_order(
                self.feed, reactant="X", product="B", rate_constant=0.1, volume=1.0, volumetric_flow=0.01
            )
        with self.assertRaises(ValueError):
            isothermal_cstr_first_order(
                self.feed, reactant="A", product="A", rate_constant=0.1, volume=1.0, volumetric_flow=0.01
            )


if __name__ == "__main__":
    unittest.main()
