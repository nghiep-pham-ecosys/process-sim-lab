import unittest

from process_sim_lab import Stream


class StreamTest(unittest.TestCase):
    def test_total_flow_and_mole_fraction(self):
        s = Stream(flows={"A": 3.0, "B": 1.0})
        self.assertAlmostEqual(s.total_flow, 4.0)
        self.assertAlmostEqual(s.mole_fraction("A"), 0.75)
        self.assertEqual(s.mole_fraction("C"), 0.0)

    def test_empty_stream_has_zero_fractions(self):
        self.assertEqual(Stream().mole_fraction("A"), 0.0)

    def test_rejects_negative_flow_and_bad_state(self):
        with self.assertRaises(ValueError):
            Stream(flows={"A": -1.0})
        with self.assertRaises(ValueError):
            Stream(temperature=0.0)
        with self.assertRaises(ValueError):
            Stream(pressure=-5.0)


if __name__ == "__main__":
    unittest.main()
