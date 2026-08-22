"""顶栏金币/钻石显示值匀速追上背包。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.currency_display import MIN_DURATION, CurrencyDisplay


class CurrencyDisplayTests(unittest.TestCase):
    def test_large_increase_one_unit_per_second(self):
        d = CurrencyDisplay(gold=10.0, diamond=1.0)
        still = d.step(target_gold=12.0, target_diamond=1.0, dt=0.1)
        self.assertAlmostEqual(d.gold, 10.1)
        self.assertAlmostEqual(d.diamond, 1.0)
        self.assertTrue(still)

    def test_small_increase_uses_min_duration(self):
        d = CurrencyDisplay(gold=10.0, diamond=0.0)
        d.step(target_gold=10.2, target_diamond=0.0, dt=MIN_DURATION / 2)
        self.assertAlmostEqual(d.gold, 10.1)
        still = d.step(target_gold=10.2, target_diamond=0.0, dt=MIN_DURATION / 2)
        self.assertAlmostEqual(d.gold, 10.2)
        self.assertFalse(still)

    def test_clamps_when_dt_covers_remaining(self):
        d = CurrencyDisplay(gold=10.0, diamond=0.0)
        still = d.step(target_gold=12.0, target_diamond=0.0, dt=3.0)
        self.assertAlmostEqual(d.gold, 12.0)
        self.assertFalse(still)

    def test_decrease_snaps(self):
        d = CurrencyDisplay(gold=100.0, diamond=5.0)
        still = d.step(target_gold=90.0, target_diamond=4.5, dt=0.05)
        self.assertAlmostEqual(d.gold, 90.0)
        self.assertAlmostEqual(d.diamond, 4.5)
        self.assertFalse(still)

    def test_lanes_independent(self):
        d = CurrencyDisplay(gold=0.0, diamond=0.0)
        d.step(target_gold=2.0, target_diamond=0.5, dt=0.5)
        self.assertAlmostEqual(d.gold, 0.5)
        self.assertAlmostEqual(d.diamond, 0.5 * (0.5 / MIN_DURATION))

    def test_retarget_recomputes_rate(self):
        d = CurrencyDisplay(gold=0.0, diamond=0.0)
        d.step(target_gold=2.0, target_diamond=0.0, dt=0.5)
        self.assertAlmostEqual(d.gold, 0.5)
        d.step(target_gold=4.0, target_diamond=0.0, dt=0.5)
        self.assertAlmostEqual(d.gold, 1.0)

    def test_zero_dt_does_not_move(self):
        d = CurrencyDisplay(gold=1.0, diamond=1.0)
        d.step(target_gold=9.0, target_diamond=9.0, dt=0.0)
        self.assertAlmostEqual(d.gold, 1.0)
        self.assertAlmostEqual(d.diamond, 1.0)


if __name__ == "__main__":
    unittest.main()
