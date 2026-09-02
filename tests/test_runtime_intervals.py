from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.runtime_intervals import RuntimeIntervalLog


def _tick(log, now, *, rec=True, task="T", title="顶", leaf=None, leaf_title=None):
    return log.tick(
        recording=rec,
        task_id=task if rec else None,
        title=title,
        leaf_id=leaf,
        leaf_title=leaf_title,
        now=now,
    )


class IntervalTickTests(unittest.TestCase):
    def test_open_then_close(self):
        log = RuntimeIntervalLog()
        self.assertTrue(_tick(log, 100.0))
        self.assertIsNotNone(log.open)
        self.assertEqual(log.open.task_id, "T")
        self.assertIsNone(log.open.leaf_id)
        self.assertTrue(_tick(log, 110.0, rec=False))
        self.assertIsNone(log.open)
        self.assertEqual(len(log.intervals), 1)
        self.assertEqual(log.intervals[0].start, 100.0)
        self.assertEqual(log.intervals[0].end, 110.0)

    def test_same_identity_does_not_split(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0, leaf="L", leaf_title="叶")
        self.assertFalse(_tick(log, 101.0, leaf="L", leaf_title="叶"))
        self.assertEqual(log.open.start, 100.0)

    def test_switch_leaf_closes_and_opens(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0, leaf="A", leaf_title="甲")
        self.assertTrue(_tick(log, 110.0, leaf="B", leaf_title="乙"))
        self.assertEqual(log.intervals[0].leaf_id, "A")
        self.assertEqual(log.intervals[0].end, 110.0)
        self.assertEqual(log.open.leaf_id, "B")
        self.assertEqual(log.open.start, 110.0)

    def test_switch_top_level_splits(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0, task="A", title="甲")
        _tick(log, 110.0, task="B", title="乙")
        self.assertEqual(log.intervals[0].task_id, "A")
        self.assertEqual(log.open.task_id, "B")

    def test_discard_shorter_than_one_second(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0)
        _tick(log, 100.5, rec=False)
        self.assertEqual(log.intervals, [])
        self.assertIsNone(log.open)

    def test_merge_same_identity_gap_under_two_seconds(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0)
        _tick(log, 110.0, rec=False)
        _tick(log, 111.5)
        _tick(log, 120.0, rec=False)
        self.assertEqual(len(log.intervals), 1)
        self.assertEqual(log.intervals[0].end, 120.0)

    def test_different_leaf_does_not_merge(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0, leaf="A", leaf_title="甲")
        _tick(log, 110.0, rec=False)
        _tick(log, 111.0, leaf="B", leaf_title="乙")
        _tick(log, 120.0, rec=False)
        self.assertEqual(len(log.intervals), 2)

    def test_clock_jump_back_drops_open(self):
        log = RuntimeIntervalLog()
        _tick(log, 10_000.0)
        _tick(log, 100.0, rec=False)
        self.assertIsNone(log.open)
        self.assertEqual(log.intervals, [])

    def test_clock_jump_forward_closes_at_last_now(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0)
        _tick(log, 10_000.0)
        self.assertEqual(len(log.intervals), 1)
        self.assertEqual(log.intervals[0].end, 100.0)
        self.assertIsNotNone(log.open)
        self.assertEqual(log.open.start, 10_000.0)
