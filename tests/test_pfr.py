import math
import unittest

from process_sim_lab import Stream
from process_sim_lab.units import isothermal_cstr_first_order, isothermal_pfr_first_order


class IsothermalPFRTest(unittest.TestCase):
    def setUp(self):
        self.feed = Stream(flows={"A": 10.0, "W": 50.0}, temperature=330.0, pressure=2e5)

    def test_half_life_case(self):
        # Hand-derived: k * tau = ln 2 -> exp(-k * tau) = 1/2 -> X = 1/2.
        # k = ln 2 / 100 1/s, V = 1 m3, Q = 0.01 m3/s -> tau = 100 s.
        r = isothermal_pfr_first_order(
            self.feed, reactant="A", product="B", rate_constant=math.log(2) / 100, volume=1.0, volumetric_flow=0.01
        )
        self.assertAlmostEqual(r.space_time, 100.0)
        self.assertAlmostEqual(r.damkohler, math.log(2), places=12)
        self.assertAlmostEqual(r.conversion, 0.5, places=12)
        self.assertAlmostEqual(r.outlet.flows["A"], 5.0, places=12)
        self.assertAlmostEqual(r.outlet.flows["B"], 5.0, places=12)

    def test_matches_analytic_conversion(self):
        # Same inputs as the CSTR test: tau = 500 s, Da = 5, X = 1 - e^-5 = 0.993262053 (e^-5 = 0.006737947).
        r = isothermal_pfr_first_order(
            self.feed, reactant="A", product="B", rate_constant=0.01, volume=2.0, volumetric_flow=0.004
        )
        self.assertAlmostEqual(r.space_time, 500.0)
        self.assertAlmostEqual(r.damkohler, 5.0)
        self.assertAlmostEqual(r.conversion, 0.993262053, places=9)
        self.assertAlmostEqual(r.outlet.flows["A"], 0.06737947, places=8)

    def test_ninety_percent_conversion(self):
        # Hand-derived: X = 0.9 needs k * tau = ln 10 = 2.302585093. With k = 0.01 1/s, Q = 0.01 m3/s:
        # tau = 230.2585093 s, V = 2.302585093 m3.
        r = isothermal_pfr_first_order(
            self.feed, reactant="A", product="B", rate_constant=0.01, volume=2.302585093, volumetric_flow=0.01
        )
        self.assertAlmostEqual(r.conversion, 0.9, places=9)
        self.assertAlmostEqual(r.outlet.flows["A"], 1.0, places=8)

    def test_beats_cstr_and_equals_many_cstrs_in_series(self):
        k, volume, q = 0.02, 1.0, 0.01  # tau = 100 s, Da = 2
        pfr = isothermal_pfr_first_order(
            self.feed, reactant="A", product="B", rate_constant=k, volume=volume, volumetric_flow=q
        )
        cstr = isothermal_cstr_first_order(
            self.feed, reactant="A", product="B", rate_constant=k, volume=volume, volumetric_flow=q
        )
        # Da = 2: CSTR X = 2/3, PFR X = 1 - e^-2 = 0.864664717.
        self.assertAlmostEqual(cstr.conversion, 2.0 / 3.0, places=12)
        self.assertAlmostEqual(pfr.conversion, 0.864664717, places=9)
        self.assertGreater(pfr.conversion, cstr.conversion)

        # N equal CSTRs in series tend to the PFR: X_N = 1 - (1 + Da/N)^-N -> 1 - e^-Da.
        # The gap is about Da^2 * e^-Da / (2N) = 1.4e-4 for N = 2000.
        n = 2000
        stream = self.feed
        for _ in range(n):
            stream = isothermal_cstr_first_order(
                stream, reactant="A", product="B", rate_constant=k, volume=volume / n, volumetric_flow=q
            ).outlet
        series_conversion = 1.0 - stream.flows["A"] / self.feed.flows["A"]
        self.assertAlmostEqual(series_conversion, 1.0 - (1.0 + 2.0 / n) ** -n, places=10)
        self.assertLess(series_conversion, pfr.conversion)
        self.assertAlmostEqual(series_conversion, pfr.conversion, delta=2e-4)

    def test_conserves_moles_and_keeps_state(self):
        r = isothermal_pfr_first_order(
            self.feed, reactant="A", product="B", rate_constant=0.2, volume=1.0, volumetric_flow=0.01
        )
        self.assertAlmostEqual(r.outlet.total_flow, self.feed.total_flow, places=12)
        self.assertEqual(r.outlet.flows["W"], 50.0)
        self.assertEqual(r.outlet.temperature, 330.0)
        self.assertEqual(r.outlet.pressure, 2e5)

    def test_zero_rate_means_no_conversion(self):
        r = isothermal_pfr_first_order(
            self.feed, reactant="A", product="B", rate_constant=0.0, volume=1.0, volumetric_flow=0.01
        )
        self.assertEqual(r.conversion, 0.0)
        self.assertEqual(r.outlet.flows["B"], 0.0)

    def test_small_damkohler_keeps_precision(self):
        # Da = 1e-12: X = Da - Da^2/2 + ... = 1e-12 to 12 significant digits.
        r = isothermal_pfr_first_order(
            self.feed, reactant="A", product="B", rate_constant=1e-14, volume=1.0, volumetric_flow=0.01
        )
        self.assertAlmostEqual(r.conversion / 1e-12, 1.0, places=11)

    def test_rejects_bad_inputs(self):
        cases = [
            dict(rate_constant=-1.0, volume=1.0, volumetric_flow=0.01),
            dict(rate_constant=0.1, volume=0.0, volumetric_flow=0.01),
            dict(rate_constant=0.1, volume=1.0, volumetric_flow=0.0),
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                isothermal_pfr_first_order(self.feed, reactant="A", product="B", **kwargs)
        with self.assertRaises(ValueError):
            isothermal_pfr_first_order(
                self.feed, reactant="X", product="B", rate_constant=0.1, volume=1.0, volumetric_flow=0.01
            )
        with self.assertRaises(ValueError):
            isothermal_pfr_first_order(
                self.feed, reactant="A", product="A", rate_constant=0.1, volume=1.0, volumetric_flow=0.01
            )


if __name__ == "__main__":
    unittest.main()
