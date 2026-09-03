"""任务管理流程测试：记账路由、legacy 迁移、完成领奖、分解、删除。"""
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
from src.runtime_intervals import load_log
from src.task_manager import TaskManager


def _make(test_case: unittest.TestCase):
    state = AppState()
    tmp = tempfile.TemporaryDirectory()
    test_case.addCleanup(tmp.cleanup)
    manager = TaskManager(state, PowerMonitor())
    manager._intervals_path = Path(tmp.name) / "runtime_intervals.json"
    return state, manager


class TaskManagerFlowTests(unittest.TestCase):
    def test_second_create_is_paused(self):
        state, m = _make(self)
        t1 = m.create("甲")
        t2 = m.create("乙")
        self.assertEqual(t1.status.value, "active")
        self.assertEqual(t2.status.value, "paused")

    def test_resume_pauses_other(self):
        state, m = _make(self)
        t1 = m.create("甲")
        t2 = m.create("乙")
        m.resume(t2.id)
        self.assertIs(state.active_task(), t2)
        self.assertEqual(t1.status.value, "paused")

    def test_flat_ops_move_to_legacy_on_first_subtask(self):
        """首次加子目标时，扁平目标上的进度必须迁入（原进度）子叶子。"""
        state, m = _make(self)
        t = m.create("甲")
        for _ in range(5):
            m.record_operation(None)
        self.assertEqual(t.operations, 5)
        m.add_subtask(t.id, "子1", target_minutes=10)
        self.assertEqual(t.operations, 0, "扁平进度应迁入 legacy 子叶子")
        self.assertEqual(t.rollup_operations(), 5, "汇总不能丢进度")
        self.assertTrue(t.subtasks[-1].is_legacy_progress())

    def test_ops_route_to_focused_leaf(self):
        state, m = _make(self)
        t = m.create("甲")
        a = m.add_subtask(t.id, "A", target_minutes=10)
        b = m.add_subtask(t.id, "B", target_minutes=10)
        m.focus_subtask(t.id, a.id)
        m.record_operation(Reward(gold=1.0, diamond=0.2))
        m.record_operation(Reward())  # 空奖励只记操作，不进 pending
        self.assertEqual(a.operations, 2)
        self.assertEqual(b.operations, 0)
        self.assertEqual(t.operations, 0, "文件夹模式下父目标不直接记账")
        self.assertEqual(a.pending_summary().gold, 1.0)
        self.assertEqual(state.since_roll.gold, 1.0)

    def test_focus_rejects_container(self):
        state, m = _make(self)
        t = m.create("甲")
        group = m.add_subtask(t.id, "组", target_minutes=10)
        m.add_subtask(t.id, "子", target_minutes=10, parent_subtask_id=group.id)
        self.assertFalse(m.focus_subtask(t.id, group.id))

    def test_claim_adds_bonus_when_done(self):
        state, m = _make(self)
        t = m.create("甲")
        sub = m.add_subtask(t.id, "A", target_minutes=1)
        m.focus_subtask(t.id, sub.id)
        m.record_operation(Reward(gold=2.0))
        sub.active_seconds = sub.target_seconds
        reward = m.complete_and_claim_subtask(t.id, sub.id)
        self.assertIsNotNone(reward)
        self.assertEqual(reward.gold, 2.5, "pending 2.0 + 完成奖 0.5")
        self.assertEqual(state.inventory.gold, 2.5)
        self.assertTrue(sub.done)
        self.assertTrue(sub.rewards_claimed)

    def test_claim_pending_without_done_has_no_bonus(self):
        state, m = _make(self)
        t = m.create("甲")
        sub = m.add_subtask(t.id, "A", target_minutes=1)
        sub.pending_rewards.append(Reward(gold=1.0))
        sub.earned_gold = 1.0
        reward = m.claim_subtask_reward(t.id, sub.id)
        self.assertIsNotNone(reward)
        self.assertEqual(reward.gold, 1.0, "未完成只领 pending，不加完成奖")
        self.assertEqual(state.inventory.gold, 1.0)
        self.assertFalse(sub.rewards_claimed, "未完成领取后仍可再完成")
        self.assertFalse(sub.done)

    def test_recover_does_not_claim_in_progress_leaf(self):
        """启动恢复不得把进行中叶子标成已领取，否则时长达标后也无法完成。"""
        state, m = _make(self)
        t = m.create("甲")
        sub = m.add_subtask(t.id, "A", target_minutes=10)
        sub.pending_rewards.append(Reward(gold=1.0))
        sub.earned_gold = 1.0
        m.recover_stuck_subtask_rewards()
        self.assertFalse(sub.done)
        self.assertFalse(sub.rewards_claimed)
        self.assertEqual(len(sub.pending_rewards), 1)
        self.assertEqual(state.inventory.gold, 0.0)

    def test_recover_repairs_premature_claimed_leaf(self):
        """未完成却已领取的叶子，启动时应恢复为可完成。"""
        state, m = _make(self)
        t = m.create("甲")
        sub = m.add_subtask(t.id, "A", target_minutes=1)
        sub.active_seconds = sub.target_seconds
        sub.rewards_claimed = True
        sub.pending_rewards.append(Reward(gold=2.0))
        sub.earned_gold = 2.0
        m.recover_stuck_subtask_rewards()
        self.assertFalse(sub.rewards_claimed)
        self.assertTrue(sub.can_finish())
        reward = m.complete_and_claim_subtask(t.id, sub.id)
        self.assertIsNotNone(reward)
        self.assertEqual(reward.gold, 2.5)
        self.assertTrue(sub.done)
        self.assertTrue(sub.rewards_claimed)

    def test_decompose_moves_progress_to_legacy(self):
        state, m = _make(self)
        t = m.create("甲")
        sub = m.add_subtask(t.id, "A", target_minutes=10)
        m.focus_subtask(t.id, sub.id)
        for _ in range(3):
            m.record_operation(None)
        self.assertTrue(m.decompose_subtask(t.id, sub.id, ["A1", "A2"]))
        self.assertTrue(sub.is_container())
        self.assertEqual(sub.rollup_operations(), 3, "分解不能丢原进度")
        legacy = sub.children[-1]
        self.assertTrue(legacy.is_legacy_progress())
        self.assertEqual(legacy.operations, 3)
        self.assertEqual(t.current_subtask_id, sub.children[0].id, "聚焦移到第一个新子项")

    def test_delete_focused_leaf_moves_focus(self):
        state, m = _make(self)
        t = m.create("甲")
        a = m.add_subtask(t.id, "A", target_minutes=10)
        b = m.add_subtask(t.id, "B", target_minutes=10)
        m.focus_subtask(t.id, a.id)
        m.delete_subtask(t.id, a.id)
        self.assertEqual(t.current_subtask_id, b.id)

    def test_complete_task_requires_all_leaves_done(self):
        state, m = _make(self)
        t = m.create("甲")
        m.add_subtask(t.id, "A", target_minutes=10)
        self.assertIsNone(m.complete(t.id))

    def test_tick_active_time_counts_focused_leaf(self):
        state, m = _make(self)
        t = m.create("甲")
        sub = m.add_subtask(t.id, "A", target_minutes=10)
        m.focus_subtask(t.id, sub.id)
        m.note_activity()
        # 每次 tick：_is_idle 与 ActiveTimeTracker 各取一次 monotonic
        with mock.patch(
            "time.monotonic", side_effect=[100.0, 100.0, 101.0, 101.0]
        ):
            m.tick_active_time()  # 首 tick 只初始化
            m.tick_active_time()
        self.assertAlmostEqual(sub.active_seconds, 1.0)

    def test_tick_active_time_skips_paused(self):
        state, m = _make(self)
        t = m.create("甲")
        m.pause(t.id)
        m.note_activity()
        with mock.patch(
            "time.monotonic", side_effect=[100.0, 100.0, 101.0, 101.0]
        ):
            m.tick_active_time()
            m.tick_active_time()
        self.assertEqual(t.active_seconds, 0.0)

    def test_tick_active_time_skips_when_idle(self):
        state, m = _make(self)
        t = m.create("甲")
        sub = m.add_subtask(t.id, "A", target_minutes=10)
        m.focus_subtask(t.id, sub.id)
        state.settings["idle_pause_minutes"] = 10
        # 上次活动在 0，之后已超过 10 分钟
        m._last_activity_mono = 0.0
        with mock.patch(
            "time.monotonic", side_effect=[700.0, 700.0, 701.0, 701.0]
        ):
            m.tick_active_time()
            m.tick_active_time()
        self.assertEqual(sub.active_seconds, 0.0)


class RuntimeLogHookTests(unittest.TestCase):
    def setUp(self):
        self.state, self.manager = _make(self)
        self.manager.note_activity()

    def test_tick_opens_for_flat_task(self):
        t = self.manager.create("甲")
        with mock.patch("src.task_manager.time.time", return_value=1_000.0):
            self.manager.tick_active_time()
        self.assertIsNotNone(self.manager.runtime_log.open)
        self.assertEqual(self.manager.runtime_log.open.task_id, t.id)
        self.assertIsNone(self.manager.runtime_log.open.leaf_id)

    def test_pause_closes_interval(self):
        t = self.manager.create("甲")
        with mock.patch("src.task_manager.time.time", return_value=1_000.0):
            self.manager.tick_active_time()
        self.manager.pause(t.id)
        with mock.patch("src.task_manager.time.time", return_value=1_030.0):
            self.manager.tick_active_time()
        self.assertIsNone(self.manager.runtime_log.open)
        self.assertEqual(self.manager.runtime_log.intervals[0].end, 1_030.0)

    def test_switch_leaf_splits(self):
        t = self.manager.create("甲")
        a = self.manager.add_subtask(t.id, "A", target_minutes=10)
        b = self.manager.add_subtask(t.id, "B", target_minutes=10)
        self.manager.focus_subtask(t.id, a.id)
        with mock.patch("src.task_manager.time.time", return_value=1_000.0):
            self.manager.tick_active_time()
        self.manager.focus_subtask(t.id, b.id)
        with mock.patch("src.task_manager.time.time", return_value=1_040.0):
            self.manager.tick_active_time()
        self.assertEqual(self.manager.runtime_log.intervals[0].leaf_id, a.id)
        self.assertEqual(self.manager.runtime_log.open.leaf_id, b.id)

    def test_unfocused_tree_does_not_record(self):
        t = self.manager.create("甲")
        self.manager.add_subtask(t.id, "A", target_minutes=10)
        t.current_subtask_id = None
        with mock.patch("src.task_manager.time.time", return_value=1_000.0):
            self.manager.tick_active_time()
        self.assertIsNone(self.manager.runtime_log.open)

    def test_persist_on_close(self):
        self.manager.create("甲")
        with mock.patch("src.task_manager.time.time", return_value=1_000.0):
            self.manager.tick_active_time()
        with mock.patch("src.task_manager.time.time", return_value=1_020.0):
            self.manager.pause(self.state.active_task().id)
            self.manager.tick_active_time()
        loaded = load_log(self.manager._intervals_path, now=1_020.0)
        self.assertEqual(len(loaded.intervals), 1)


if __name__ == "__main__":
    unittest.main()
