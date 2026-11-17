import unittest

from process_sim_lab.antoine import ANTOINE, AntoineConstants, saturation_temperature, vapour_pressure

ATM = 101_325.0  # Pa

# Normal boiling points from the NIST Chemistry WebBook (SRD 69), "Phase change data", row Tboil (method AVG),
# with the uncertainty the WebBook states. The test tolerance is that uncertainty.
NIST_TBOIL = {
    "benzene": (353.3, 0.1),
    "toluene": (383.8, 0.2),
    "ethylbenzene": (409.3, 0.4),
}


class AntoineTest(unittest.TestCase):
    def test_normal_boiling_points_match_nist_within_its_uncertainty(self):
        for component, (tboil, uncertainty) in NIST_TBOIL.items():
            with self.subTest(component=component):
                self.assertAlmostEqual(saturation_temperature(component, ATM), tboil, delta=uncertainty)

    def test_pressure_at_nist_boiling_point_is_one_atmosphere(self):
        # 0.4 K at d(ln P)/dT of about 0.03 1/K is about 1.2 %, so 1.5 % covers every NIST uncertainty above.
        for component, (tboil, _) in NIST_TBOIL.items():
            with self.subTest(component=component):
                self.assertAlmostEqual(vapour_pressure(component, tboil) / ATM, 1.0, delta=0.015)

    def test_hand_checked_benzene_value(self):
        # T = 300 K: log10(P/bar) = 4.01814 - 1203.835 / (300 - 53.226) = 4.01814 - 4.8782894...
        # = -0.8601494..., so P = 0.137991 bar = 13 799 Pa.
        exponent = 4.01814 - 1203.835 / (300.0 - 53.226)
        self.assertAlmostEqual(exponent, -0.8601494, places=6)
        self.assertAlmostEqual(vapour_pressure("benzene", 300.0), 1e5 * 10.0**exponent, places=6)
        self.assertAlmostEqual(vapour_pressure("benzene", 300.0), 13_799.0, delta=1.0)

    def test_inverse_round_trip(self):
        for component, k in ANTOINE.items():
            for t in (k.t_min, 0.5 * (k.t_min + k.t_max), k.t_max):
                with self.subTest(component=component, temperature=t):
                    p = vapour_pressure(component, t)
                    self.assertAlmostEqual(saturation_temperature(component, p), t, places=9)

    def test_volatility_order(self):
        # At one temperature inside all three ranges the lighter aromatic has the higher vapour pressure.
        t = 350.0
        pb, pt, pe = (vapour_pressure(c, t) for c in ("benzene", "toluene", "ethylbenzene"))
        self.assertGreater(pb, pt)
        self.assertGreater(pt, pe)

    def test_every_set_has_range_and_source(self):
        self.assertEqual(len(ANTOINE), 3)
        for component, k in ANTOINE.items():
            with self.subTest(component=component):
                self.assertLess(k.t_min, k.t_max)
                self.assertIn("NIST", k.source)

    def test_rejects_out_of_range_and_unknown(self):
        with self.assertRaises(ValueError):
            vapour_pressure("benzene", 360.0)  # above 354.07 K
        with self.assertRaises(ValueError):
            vapour_pressure("toluene", 300.0)  # below 308.52 K
        with self.assertRaises(ValueError):
            saturation_temperature("benzene", 10 * ATM)  # answer far above the fitted range
        with self.assertRaises(ValueError):
            saturation_temperature("benzene", 0.0)
        with self.assertRaises(ValueError):
            vapour_pressure("unobtainium", 300.0)

    def test_rejects_bad_constants(self):
        with self.assertRaises(ValueError):
            AntoineConstants(a=4.0, b=-1.0, c=0.0, t_min=300.0, t_max=350.0, source="synthetic")
        with self.assertRaises(ValueError):
            AntoineConstants(a=4.0, b=1000.0, c=0.0, t_min=350.0, t_max=300.0, source="synthetic")
        with self.assertRaises(ValueError):
            AntoineConstants(a=4.0, b=1000.0, c=-400.0, t_min=300.0, t_max=350.0, source="synthetic")


if __name__ == "__main__":
    unittest.main()
