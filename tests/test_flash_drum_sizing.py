import math
import unittest

from process_sim_lab import Stream
from process_sim_lab.units import size_vertical_flash_drum
from process_sim_lab.units.flash_drum_sizing import GAS_CONSTANT

# The vapour of the week-3 example drum: (A, I, B) = (1.25, 0.75, 0.5) mol/s at 330 K and 2 bar, with illustrative
# molar masses 60, 28 and 60 g/mol, liquid 800 kg/m3, K_SB = 0.07 m/s (demister pad) and H / D = 4.
VAPOUR = Stream(flows={"A": 1.25, "I": 0.75, "B": 0.5}, temperature=330.0, pressure=200000.0)
MOLAR_MASSES = {"A": 0.060, "I": 0.028, "B": 0.060}
SIZING = {"molar_masses": MOLAR_MASSES, "liquid_density": 800.0, "souders_brown_k": 0.07, "height_to_diameter": 4.0}


class HandCheckedDrumTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.size = size_vertical_flash_drum(VAPOUR, **SIZING)

    def test_vapour_properties(self):
        # M_V = (1.25 * 0.060 + 0.75 * 0.028 + 0.5 * 0.060) / 2.5 = 0.126 / 2.5 = 0.0504 kg/mol.
        # R T = 8.31446261815324 * 330 = 2743.772664 J/mol; rho_V = 2e5 * 0.0504 / 2743.772664 = 3.673774 kg/m3.
        # Q_V = 2.5 * 2743.772664 / 2e5 = 0.0342971583 m3/s.
        self.assertAlmostEqual(self.size.vapour_molar_mass, 0.0504, places=12)
        self.assertAlmostEqual(self.size.vapour_density, 3.6737737540, places=9)
        self.assertAlmostEqual(self.size.vapour_volumetric_flow, 0.0342971583, places=10)

    def test_velocity_and_dimensions(self):
        # u_max = 0.07 * sqrt((800 - 3.673774) / 3.673774) = 0.07 * sqrt(216.759735) = 1.0305934 m/s.
        # A = 0.0342971583 / 1.0305934 = 0.0332790 m2; D = sqrt(4 A / pi) = 0.2058451 m; H = 4 D = 0.8233803 m;
        # V = pi D^2 / 4 * H = 0.0274013 m3.
        self.assertAlmostEqual(self.size.max_vapour_velocity, 1.0305933741, places=9)
        self.assertAlmostEqual(self.size.diameter, 0.2058450630, places=9)
        self.assertAlmostEqual(self.size.height, 0.8233802520, places=9)
        self.assertAlmostEqual(self.size.volume, 0.0274013045, places=9)
        self.assertEqual(self.size.height_to_diameter, 4.0)

    def test_cross_section_carries_the_vapour_at_the_allowed_velocity(self):
        area = math.pi * self.size.diameter**2 / 4.0
        self.assertAlmostEqual(area * self.size.max_vapour_velocity, self.size.vapour_volumetric_flow, places=14)

    def test_gas_constant_is_avogadro_times_boltzmann(self):
        self.assertAlmostEqual(GAS_CONSTANT, 6.02214076e23 * 1.380649e-23, places=12)


class ScalingTest(unittest.TestCase):
    def test_diameter_grows_with_the_square_root_of_the_vapour_flow(self):
        double = Stream(flows={c: 2 * f for c, f in VAPOUR.flows.items()}, temperature=330.0, pressure=200000.0)
        d1 = size_vertical_flash_drum(VAPOUR, **SIZING).diameter
        d2 = size_vertical_flash_drum(double, **SIZING).diameter
        self.assertAlmostEqual(d2 / d1, math.sqrt(2.0), places=12)

    def test_components_without_vapour_flow_need_no_molar_mass(self):
        vapour = Stream(flows={**VAPOUR.flows, "W": 0.0}, temperature=330.0, pressure=200000.0)
        self.assertAlmostEqual(
            size_vertical_flash_drum(vapour, **SIZING).diameter, size_vertical_flash_drum(VAPOUR, **SIZING).diameter,
            places=15,
        )


class RejectTest(unittest.TestCase):
    def test_no_vapour(self):
        empty = Stream(flows={"A": 0.0}, temperature=330.0, pressure=200000.0)
        with self.assertRaisesRegex(ValueError, "no flow"):
            size_vertical_flash_drum(empty, **SIZING)

    def test_missing_or_bad_molar_mass(self):
        with self.assertRaisesRegex(ValueError, "no molar mass for component 'I'"):
            size_vertical_flash_drum(VAPOUR, **{**SIZING, "molar_masses": {"A": 0.06, "B": 0.06}})
        for bad in (0.0, -0.028, math.nan, math.inf):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "molar mass of 'I'"):
                size_vertical_flash_drum(VAPOUR, **{**SIZING, "molar_masses": {**MOLAR_MASSES, "I": bad}})

    def test_non_positive_inputs(self):
        for key in ("liquid_density", "souders_brown_k", "height_to_diameter"):
            for bad in (0.0, -1.0, math.nan, math.inf):
                with self.subTest(key=key, bad=bad), self.assertRaisesRegex(ValueError, key):
                    size_vertical_flash_drum(VAPOUR, **{**SIZING, key: bad})

    def test_liquid_no_denser_than_the_vapour(self):
        with self.assertRaisesRegex(ValueError, "must exceed the vapour density"):
            size_vertical_flash_drum(VAPOUR, **{**SIZING, "liquid_density": 3.0})


if __name__ == "__main__":
    unittest.main()
