from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import AppState
from src.power_monitor import PowerMonitor
from src.runtime_intervals import DaySlice
from src.task_manager import TaskManager
from src.ui_week_runtime import (
    format_clock_hours,
    format_legend_label,
    format_running_status,
    format_slice_hover,
)


def _make(test_case: unittest.TestCase):
    state = AppState()
    tmp = tempfile.TemporaryDirectory()
    test_case.addCleanup(tmp.cleanup)
    manager = TaskManager(state, PowerMonitor())
    manager._intervals_path = Path(tmp.name) / "runtime_intervals.json"
    return state, manager


class WeekRuntimeTextTests(unittest.TestCase):
    def test_status_leaf_and_flat_and_idle(self):
        state, m = _make(self)
        self.assertEqual(format_running_status(state), "当前没有运行中的目标")
        t = m.create("写文档")
        self.assertEqual(format_running_status(state), "正在运行  顶层「写文档」")
        leaf = m.add_subtask(t.id, "第 3 章", target_minutes=10)
        t.current_subtask_id = None
        self.assertEqual(format_running_status(state), "当前没有运行中的目标")
        m.focus_subtask(t.id, leaf.id)
        self.assertEqual(
            format_running_status(state),
            "正在运行  顶层「写文档」  ·  「第 3 章」",
        )

    def test_hover_and_clock(self):
        sl = DaySlice(
            date="2026-09-02", t0=9.0, t1=11.0 + 20 / 60.0,
            task_id="T", title="写文档", leaf_id="L", leaf_title="第 3 章",
        )
        self.assertEqual(format_clock_hours(9.0), "09:00")
        self.assertEqual(format_clock_hours(24.0), "24:00")
        text = format_slice_hover(sl)
        self.assertIn("写文档 · 第 3 章", text)
        self.assertIn("09:00", text)
        self.assertIn("11:20", text)
        flat = DaySlice(
            date="2026-09-02", t0=9.0, t1=10.0,
            task_id="T", title="写文档", leaf_id=None, leaf_title=None,
        )
        self.assertNotIn("·", format_slice_hover(flat))

    def test_legend_running_suffix(self):
        self.assertEqual(
            format_legend_label("写文档", "第 3 章", running=True),
            "写文档 · 第 3 章  运行中",
        )
        self.assertEqual(
            format_legend_label("写文档", None, running=False),
            "写文档",
        )
