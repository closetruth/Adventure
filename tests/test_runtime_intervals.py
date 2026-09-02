from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.runtime_intervals import RuntimeIntervalLog, load_log, save_log


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


class IntervalPersistTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "runtime_intervals.json"

    def test_roundtrip_open_and_closed(self):
        log = RuntimeIntervalLog()
        log.tick(recording=True, task_id="T", title="顶", leaf_id="L", leaf_title="叶", now=100.0)
        log.tick(recording=False, task_id=None, now=110.0)
        log.tick(recording=True, task_id="T", title="顶", now=200.0)
        save_log(log, self.path)
        loaded = load_log(self.path, now=200.0, recover=False)
        self.assertEqual(len(loaded.intervals), 1)
        self.assertEqual(loaded.intervals[0].leaf_id, "L")
        self.assertIsNotNone(loaded.open)
        self.assertEqual(loaded.open.start, 200.0)
        self.assertFalse(loaded.load_reset)

    def test_corrupt_file_archived_and_reset(self):
        self.path.write_text("{not json", encoding="utf-8")
        loaded = load_log(self.path, now=1.0)
        self.assertTrue(loaded.load_reset)
        self.assertEqual(loaded.intervals, [])
        broken = list(Path(self._tmp.name).glob("runtime_intervals.broken.*.json"))
        self.assertEqual(len(broken), 1)

    def test_crash_recover_uses_mtime(self):
        payload = {
            "version": 1,
            "intervals": [],
            "open": {"task_id": "T", "title": "顶", "leaf_id": None, "leaf_title": None, "start": 100.0},
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_log(self.path, data_mtime=150.0, now=160.0)
        self.assertIsNone(loaded.open)
        self.assertEqual(loaded.intervals[0].end, 150.0)

    def test_crash_recover_drops_stale_open(self):
        payload = {
            "version": 1,
            "intervals": [],
            "open": {"task_id": "T", "title": "顶", "leaf_id": None, "leaf_title": None, "start": 100.0},
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_log(self.path, data_mtime=150.0, now=10_000.0)
        self.assertIsNone(loaded.open)
        self.assertEqual(loaded.intervals, [])

    def test_crash_recover_no_mtime_drops_open(self):
        payload = {
            "version": 1,
            "intervals": [],
            "open": {"task_id": "T", "title": "顶", "leaf_id": None, "leaf_title": None, "start": 100.0},
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_log(self.path, data_mtime=None, now=160.0)
        self.assertIsNone(loaded.open)
        self.assertEqual(loaded.intervals, [])
