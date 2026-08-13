"""存档测试：往返一致 + 损坏恢复。使用临时目录，绝不触碰真实 %APPDATA%。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import AppState, Reward
from src.power_monitor import PowerMonitor
from src.storage import load_state, save_state, take_load_warning
from src.task_manager import TaskManager


class StorageRoundtripTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch(
            "src.storage.get_data_dir", return_value=Path(self._tmp.name)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(take_load_warning)  # 清掉模块级警告，避免串到其他测试

    @staticmethod
    def _sample_state() -> AppState:
        state = AppState()
        m = TaskManager(state, PowerMonitor())
        t = m.create("学习")
        sub = m.add_subtask(t.id, "读书", target_minutes=30)
        m.focus_subtask(t.id, sub.id)
        m.record_operation(Reward(gold=1.0, diamond=0.2))
        m.record_operation(None)
        state.total_operations = 12
        state.inventory.gold = 7.5
        return state

    def test_roundtrip_preserves_state(self):
        state = self._sample_state()
        save_state(state)
        loaded = load_state()
        self.assertIsNone(take_load_warning())
        self.assertEqual(loaded.total_operations, 12)
        self.assertEqual(loaded.inventory.gold, 7.5)
        self.assertEqual(len(loaded.tasks), 1)
        sub = loaded.tasks[0].subtasks[0]
        self.assertEqual(sub.title, "读书")
        self.assertEqual(sub.operations, 2)
        self.assertEqual(sub.pending_summary().gold, 1.0)
        self.assertEqual(
            loaded.roll_runtime.next_roll_at, state.roll_runtime.next_roll_at
        )

    def test_corrupt_main_recovers_from_backup(self):
        state = self._sample_state()
        save_state(state)
        data_file = Path(self._tmp.name) / "data.json"
        data_file.write_text("这不是 JSON", encoding="utf-8")

        loaded = load_state()
        self.assertEqual(loaded.total_operations, 12, "损坏后应从 anchor/bak 恢复")
        self.assertIsNotNone(take_load_warning(), "恢复应产生警告")
        # 恢复后主存档被写回有效内容
        restored = data_file.read_text(encoding="utf-8")
        self.assertTrue(restored.strip().startswith("{"))

    def test_garbage_only_creates_fresh_state(self):
        data_file = Path(self._tmp.name) / "data.json"
        data_file.write_text("garbage", encoding="utf-8")
        loaded = load_state()
        self.assertEqual(loaded.total_operations, 0)
        self.assertEqual(loaded.tasks, [])


if __name__ == "__main__":
    unittest.main()
