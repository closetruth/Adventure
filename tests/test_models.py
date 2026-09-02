"""模型层测试：文件夹式 rollup、聚焦路径、状态不变量。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import (
    AppState,
    Reward,
    Subtask,
    Task,
    TaskStatus,
    validate_state_invariants,
)


class RollupTests(unittest.TestCase):
    """文件夹式记账：父/分组自身字段不参与汇总，只算子孙叶子。"""

    def _task_with_leaves(self) -> tuple[Task, Subtask, Subtask]:
        t = Task(title="父", status=TaskStatus.ACTIVE)
        a = Subtask(title="A")
        a.operations = 3
        a.earned_gold = 1.5
        a.earned_diamond = 0.2
        b = Subtask(title="B")
        b.operations = 5
        b.earned_gold = 2.0
        t.subtasks = [a, b]
        return t, a, b

    def test_rollup_operations(self):
        t, _a, _b = self._task_with_leaves()
        self.assertEqual(t.rollup_operations(), 8)

    def test_rollup_earned(self):
        t, _a, _b = self._task_with_leaves()
        self.assertEqual(t.rollup_earned(), (3.5, 0.2))

    def test_flat_task_uses_own_fields(self):
        t = Task(operations=4, earned_gold=1.0)
        self.assertEqual(t.rollup_operations(), 4)

    def test_container_ignores_own_fields(self):
        t, a, b = self._task_with_leaves()
        container = Subtask(title="组", children=[a, b], operations=99, earned_gold=50.0)
        self.assertEqual(container.rollup_operations(), 8)
        self.assertEqual(container.rollup_earned(), (3.5, 0.2))

    def test_active_focus_path_ids(self):
        t = Task(status=TaskStatus.ACTIVE)
        group = Subtask(title="组")
        leaf = Subtask(title="叶")
        group.children = [leaf]
        t.subtasks = [group]
        t.current_subtask_id = leaf.id
        self.assertEqual(t.active_focus_path_ids(), frozenset({group.id, leaf.id}))

    def test_current_subtask_skips_done(self):
        t = Task(status=TaskStatus.ACTIVE)
        leaf = Subtask(title="叶", done=True)
        t.subtasks = [leaf]
        t.current_subtask_id = leaf.id
        self.assertIsNone(t.current_subtask())


class InvariantTests(unittest.TestCase):
    """存档保存前校验：不变量被破坏时必须拒绝写盘。"""

    def test_fresh_state_ok(self):
        self.assertIsNone(validate_state_invariants(AppState()))

    def test_two_active_tasks_rejected(self):
        s = AppState()
        s.tasks = [Task(status=TaskStatus.ACTIVE), Task(status=TaskStatus.ACTIVE)]
        self.assertIn("进行中", validate_state_invariants(s))

    def test_current_pointing_done_leaf_rejected(self):
        s = AppState()
        t = Task(status=TaskStatus.ACTIVE)
        leaf = Subtask(done=True)
        t.subtasks = [leaf]
        t.current_subtask_id = leaf.id
        s.tasks = [t]
        self.assertIn("已完成", validate_state_invariants(s))

    def test_negative_inventory_rejected(self):
        s = AppState()
        s.inventory.gold = -1.0
        self.assertIsNotNone(validate_state_invariants(s))


class VisibleCurrencyTests(unittest.TestCase):
    def test_global_is_backpack_only(self):
        s = AppState()
        s.inventory.gold = 10.0
        s.inventory.diamond = 1.0
        leaf = Subtask(title="A")
        leaf.pending_rewards.append(Reward(gold=0.5, diamond=0.2))
        t = Task(title="父", status=TaskStatus.PAUSED, subtasks=[leaf])
        s.tasks = [t]
        gold, diamond = s.visible_gold_diamond()
        self.assertAlmostEqual(gold, 10.0)
        self.assertAlmostEqual(diamond, 1.0)

    def test_skips_completed_and_pending(self):
        s = AppState()
        s.inventory.gold = 3.0
        leaf = Subtask(title="A")
        leaf.pending_rewards.append(Reward(gold=9.0))
        t = Task(title="完", status=TaskStatus.COMPLETED, subtasks=[leaf])
        s.tasks = [t]
        gold, _ = s.visible_gold_diamond()
        self.assertAlmostEqual(gold, 3.0)


if __name__ == "__main__":
    unittest.main()
