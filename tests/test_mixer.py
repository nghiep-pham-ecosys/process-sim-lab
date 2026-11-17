import unittest

from process_sim_lab import Stream
from process_sim_lab.units import mix_streams


class MixerTest(unittest.TestCase):
    def test_sums_component_flows(self):
        # Hand-summed: A = 2 + 3 = 5, B = 1, C = 4; total 10 mol/s; x_A = 0.5.
        s1 = Stream(flows={"A": 2.0, "B": 1.0}, temperature=300.0, pressure=3e5)
        s2 = Stream(flows={"A": 3.0, "C": 4.0}, temperature=300.0, pressure=2e5)
        out = mix_streams([s1, s2])
        self.assertEqual(out.flows, {"A": 5.0, "B": 1.0, "C": 4.0})
        self.assertAlmostEqual(out.total_flow, s1.total_flow + s2.total_flow, places=12)
        self.assertAlmostEqual(out.mole_fraction("A"), 0.5, places=12)
        self.assertEqual(list(out.flows), ["A", "B", "C"])

    def test_takes_lowest_pressure_and_common_temperature(self):
        inlets = [
            Stream(flows={"A": 1.0}, temperature=350.0, pressure=5e5),
            Stream(flows={"A": 1.0}, temperature=350.0, pressure=1.5e5),
            Stream(flows={"B": 1.0}, temperature=350.0, pressure=4e5),
        ]
        out = mix_streams(inlets)
        self.assertEqual(out.pressure, 1.5e5)
        self.assertEqual(out.temperature, 350.0)
        self.assertAlmostEqual(out.total_flow, 3.0, places=12)

    def test_single_inlet_is_unchanged(self):
        s = Stream(flows={"A": 2.5, "B": 0.5}, temperature=310.0, pressure=1.2e5)
        self.assertEqual(mix_streams([s]), s)

    def test_different_temperatures_need_an_explicit_outlet_temperature(self):
        hot = Stream(flows={"W": 1.0}, temperature=360.0)
        cold = Stream(flows={"W": 1.0}, temperature=300.0)
        with self.assertRaises(ValueError):
            mix_streams([hot, cold])
        out = mix_streams([hot, cold], temperature=330.0)
        self.assertEqual(out.temperature, 330.0)
        self.assertAlmostEqual(out.flows["W"], 2.0, places=12)

    def test_rejects_no_inlets(self):
        with self.assertRaises(ValueError):
            mix_streams([])


if __name__ == "__main__":
    unittest.main()
