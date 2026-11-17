import unittest

from process_sim_lab import Stream
from process_sim_lab.units import mix_streams, split_stream


class SplitterTest(unittest.TestCase):
    def setUp(self):
        self.feed = Stream(flows={"A": 6.0, "B": 4.0}, temperature=320.0, pressure=1.8e5)

    def test_splits_by_fraction(self):
        # Hand-multiplied: 0.25 * (6, 4) = (1.5, 1.0); 0.75 * (6, 4) = (4.5, 3.0).
        purge, recycle = split_stream(self.feed, [0.25, 0.75])
        self.assertAlmostEqual(purge.flows["A"], 1.5, places=12)
        self.assertAlmostEqual(purge.flows["B"], 1.0, places=12)
        self.assertAlmostEqual(recycle.flows["A"], 4.5, places=12)
        self.assertAlmostEqual(recycle.flows["B"], 3.0, places=12)

    def test_outlets_keep_composition_and_state(self):
        outlets = split_stream(self.feed, [0.1, 0.3, 0.6])
        self.assertEqual(len(outlets), 3)
        for out in outlets:
            self.assertAlmostEqual(out.mole_fraction("A"), 0.6, places=12)
            self.assertEqual(out.temperature, 320.0)
            self.assertEqual(out.pressure, 1.8e5)

    def test_outlets_add_back_to_feed(self):
        outlets = split_stream(self.feed, [0.1, 0.3, 0.6])
        for name, value in self.feed.flows.items():
            self.assertAlmostEqual(sum(o.flows[name] for o in outlets), value, places=12)
        rejoined = mix_streams(outlets)
        self.assertAlmostEqual(rejoined.total_flow, self.feed.total_flow, places=12)

    def test_zero_fraction_gives_empty_outlet(self):
        empty, full = split_stream(self.feed, [0.0, 1.0])
        self.assertEqual(empty.total_flow, 0.0)
        self.assertEqual(full.flows, self.feed.flows)

    def test_rejects_bad_fractions(self):
        for fractions in ([], [0.5, 0.6], [0.5, 0.4], [-0.2, 1.2], [1.5, -0.5], [float("nan"), 1.0]):
            with self.subTest(fractions=fractions), self.assertRaises(ValueError):
                split_stream(self.feed, fractions)


if __name__ == "__main__":
    unittest.main()
