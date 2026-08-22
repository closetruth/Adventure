"""计数器式金额：按位滚动偏移（不依赖窗口）。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ui_odometer import integer_digit_count, place_scroll


class PlaceScrollTests(unittest.TestCase):
    def test_tenths_of_10_2_is_exactly_two(self):
        digit, frac = place_scroll(10.2, 0.1)
        self.assertEqual(digit, 2)
        self.assertAlmostEqual(frac, 0.0, places=6)

    def test_ones_of_10_2_rests_on_full_digit(self):
        digit, frac = place_scroll(10.2, 1.0)
        self.assertEqual(digit, 0)
        self.assertAlmostEqual(frac, 0.0, places=6)

    def test_tens_of_10_2_rests_on_full_digit(self):
        digit, frac = place_scroll(10.2, 10.0)
        self.assertEqual(digit, 1)
        self.assertAlmostEqual(frac, 0.0, places=6)

    def test_integer_digit_count(self):
        self.assertEqual(integer_digit_count(0.5), 1)
        self.assertEqual(integer_digit_count(10.2), 2)
        self.assertEqual(integer_digit_count(3058.0), 4)


if __name__ == "__main__":
    unittest.main()
