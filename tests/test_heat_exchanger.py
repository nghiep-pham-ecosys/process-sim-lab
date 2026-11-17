import math
import unittest

from process_sim_lab.units import counter_current_area, log_mean_temperature_difference


class LMTDTest(unittest.TestCase):
    def test_hand_checked_value(self):
        # dT1 = 80 K, dT2 = 60 K: LMTD = 20 / ln(4/3) = 20 / 0.2876820725 = 69.521190 K.
        self.assertAlmostEqual(log_mean_temperature_difference(80.0, 60.0), 69.5211899356, places=9)

    def test_symmetric_in_its_arguments(self):
        self.assertAlmostEqual(
            log_mean_temperature_difference(80.0, 60.0), log_mean_temperature_difference(60.0, 80.0), places=12
        )

    def test_equal_differences_give_the_limit(self):
        self.assertEqual(log_mean_temperature_difference(50.0, 50.0), 50.0)

    def test_continuous_near_the_equal_limit(self):
        # Just inside and just outside the switch to the arithmetic mean, the value stays within 1e-9 K of 50 K.
        for gap in (1e-12, 1e-8, 1e-5, 1e-4):
            with self.subTest(gap=gap):
                self.assertAlmostEqual(log_mean_temperature_difference(50.0 + gap, 50.0), 50.0 + gap / 2, delta=1e-9)

    def test_lies_between_geometric_and_arithmetic_means(self):
        a, b = 120.0, 15.0
        lmtd = log_mean_temperature_difference(a, b)
        self.assertGreater(lmtd, math.sqrt(a * b))
        self.assertLess(lmtd, 0.5 * (a + b))

    def test_rejects_non_positive_differences(self):
        for a, b in ((0.0, 10.0), (10.0, 0.0), (-5.0, 10.0)):
            with self.subTest(a=a, b=b), self.assertRaises(ValueError):
                log_mean_temperature_difference(a, b)


class CounterCurrentAreaTest(unittest.TestCase):
    def test_hand_checked_area(self):
        # Hot 423.15 -> 363.15 K, cold 303.15 -> 343.15 K: dT1 = 80 K, dT2 = 60 K, LMTD = 69.521190 K.
        # Q = 500 kW, U = 500 W/(m2 K): A = 5e5 / (500 * 69.521190) = 14.384104 m2.
        r = counter_current_area(
            duty=5e5, overall_u=500.0, hot_in=423.15, hot_out=363.15, cold_in=303.15, cold_out=343.15
        )
        self.assertAlmostEqual(r.delta_t1, 80.0, places=9)
        self.assertAlmostEqual(r.delta_t2, 60.0, places=9)
        self.assertAlmostEqual(r.lmtd, 69.5211899356, places=6)
        self.assertAlmostEqual(r.area, 14.3841036, places=6)
        self.assertAlmostEqual(500.0 * r.area * r.lmtd, 5e5, places=6)

    def test_equal_terminal_differences(self):
        # Balanced counter-current exchanger (equal heat-capacity rates): dT1 = dT2 = 50 K, so LMTD = 50 K.
        # Q = 100 kW, U = 400 W/(m2 K): A = 1e5 / (400 * 50) = 5 m2.
        r = counter_current_area(duty=1e5, overall_u=400.0, hot_in=400.0, hot_out=350.0, cold_in=300.0, cold_out=350.0)
        self.assertEqual(r.lmtd, 50.0)
        self.assertAlmostEqual(r.area, 5.0, places=12)

    def test_area_falls_as_u_rises(self):
        kw = dict(duty=5e5, hot_in=423.15, hot_out=363.15, cold_in=303.15, cold_out=343.15)
        self.assertAlmostEqual(
            counter_current_area(overall_u=250.0, **kw).area, 2 * counter_current_area(overall_u=500.0, **kw).area
        )

    def test_rejects_bad_inputs(self):
        good = dict(duty=5e5, overall_u=500.0, hot_in=423.15, hot_out=363.15, cold_in=303.15, cold_out=343.15)
        bad = [
            dict(duty=0.0),
            dict(overall_u=-1.0),
            dict(hot_out=430.0),  # hot side heats up
            dict(cold_out=300.0),  # cold side cools down
            dict(cold_out=430.0),  # temperature cross at the hot end
            dict(cold_in=0.0),
        ]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                counter_current_area(**{**good, **change})


if __name__ == "__main__":
    unittest.main()
