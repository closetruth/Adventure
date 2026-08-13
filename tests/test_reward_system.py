"""开奖系统测试：固定随机种子保证确定性。"""
from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import AppState
from src.reward_system import (
    ensure_roll_runtime,
    maybe_roll,
    roll_progress,
    start_new_roll_cycle,
)


class RollSystemTests(unittest.TestCase):
    def setUp(self):
        random.seed(1234)
        self.state = AppState()
        # 先完成一次启动迁移（会重抽参数），之后才能覆盖概率字段
        ensure_roll_runtime(self.state)

    def test_roll_progress_clamps(self):
        s = self.state
        s.total_operations = 5
        s.roll_runtime.next_roll_at = 10
        self.assertEqual(roll_progress(s), (5, 10))
        s.total_operations = 99
        self.assertEqual(roll_progress(s), (10, 10), "进度不能超过周期格数")

    def test_cycle_span_in_range(self):
        s = self.state
        s.total_operations = 42
        start_new_roll_cycle(s)
        span = s.roll_runtime.roll_span
        self.assertTrue(6 <= span <= 14)
        self.assertEqual(s.roll_runtime.next_roll_at, 42 + span)
        self.assertEqual(len(s.roll_runtime.segment_colors), span)

    def test_before_roll_point_returns_none(self):
        s = self.state
        s.total_operations = 5
        s.roll_runtime.next_roll_at = 10
        self.assertIsNone(maybe_roll(s))
        self.assertEqual(s.roll_history, [])

    def test_at_roll_point_with_certain_gold(self):
        s = self.state
        s.roll_runtime.next_roll_at = 10
        s.roll_runtime.gold_chance = 1.0
        s.roll_runtime.diamond_chance = 0.0
        s.total_operations = 10
        reward = maybe_roll(s)
        self.assertIsNotNone(reward)
        self.assertGreater(reward.gold, 0)
        self.assertEqual(reward.diamond, 0.0)
        self.assertEqual(s.last_roll_at, 10)
        self.assertEqual(len(s.roll_history), 1)
        self.assertGreater(s.roll_runtime.next_roll_at, 10, "开奖后要开新周期")

    def test_history_newest_first(self):
        s = self.state
        s.roll_runtime.gold_chance = 0.0
        s.roll_runtime.diamond_chance = 0.0
        for i in range(1, 4):
            s.total_operations = 10 * i
            s.roll_runtime.next_roll_at = s.total_operations
            maybe_roll(s)
        self.assertEqual(
            [e.op_at for e in s.roll_history], [30, 20, 10],
            "开奖历史应最新在前",
        )


if __name__ == "__main__":
    unittest.main()
