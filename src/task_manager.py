"""任务 CRUD 与状态变更逻辑。"""
from __future__ import annotations

import time
from typing import List, Optional

from .models import AppState, Reward, Subtask, Task, TaskStatus


class TaskManager:
    def __init__(self, state: AppState):
        self.state = state
        for t in state.tasks:
            if t.subtasks:
                t.sync_earned_from_subtasks()
            if t.status == TaskStatus.ACTIVE:
                self._sync_current_subtask(t)

    # ----- 查询 -----
    def all(self) -> List[Task]:
        return list(self.state.tasks)

    def by_status(self, status: TaskStatus) -> List[Task]:
        return [t for t in self.state.tasks if t.status == status]

    def get(self, task_id: str) -> Optional[Task]:
        for t in self.state.tasks:
            if t.id == task_id:
                return t
        return None

    def _get_subtask(self, task: Task, subtask_id: str) -> Optional[Subtask]:
        for s in task.subtasks:
            if s.id == subtask_id:
                return s
        return None

    def _sync_current_subtask(self, task: Task) -> None:
        for s in task.subtasks:
            if not s.done:
                task.current_subtask_id = s.id
                return
        task.current_subtask_id = None

    def _completion_bonus(self) -> float:
        return float(self.state.settings.get("subtask_completion_bonus_gold", 0.5))

    def preview_claim(self, task_id: str, subtask_id: str) -> Optional[Reward]:
        """预览领取总额（pending + 完成固定奖）。"""
        t = self.get(task_id)
        if not t:
            return None
        sub = self._get_subtask(t, subtask_id)
        if not sub or not sub.is_claimable():
            return None
        total = sub.pending_summary()
        total.gold += self._completion_bonus()
        return total

    def _mark_subtask_done(self, task: Task, sub: Subtask) -> None:
        if sub.done:
            return
        sub.done = True
        sub.completed_at = time.time()
        if sub.active_seconds < sub.target_seconds:
            sub.active_seconds = sub.target_seconds
        self._sync_current_subtask(task)

    # ----- 变更 -----
    def create(self, title: str, note: str = "") -> Task:
        title = (title or "").strip() or "未命名目标"
        has_active = self.state.active_task() is not None
        status = TaskStatus.PAUSED if has_active else TaskStatus.ACTIVE
        task = Task(title=title, note=note, status=status)
        self.state.tasks.insert(0, task)
        if status == TaskStatus.ACTIVE:
            self._sync_current_subtask(task)
        return task

    def pause(self, task_id: str) -> Optional[Task]:
        t = self.get(task_id)
        if not t or t.status != TaskStatus.ACTIVE:
            return t
        t.status = TaskStatus.PAUSED
        return t

    def resume(self, task_id: str) -> Optional[Task]:
        t = self.get(task_id)
        if not t or t.status != TaskStatus.PAUSED:
            return t
        current = self.state.active_task()
        if current and current.id != t.id:
            current.status = TaskStatus.PAUSED
        t.status = TaskStatus.ACTIVE
        self._sync_current_subtask(t)
        return t

    def complete(self, task_id: str) -> Optional[Reward]:
        """完成任务并把待领取奖励转入背包，返回本次结算的总奖励。"""
        t = self.get(task_id)
        if not t or t.status == TaskStatus.COMPLETED:
            return None
        if t.has_unclaimed_subtasks():
            return None
        total = t.pending_summary()
        self.state.inventory.add(total)
        t.completed_reward_gold = total.gold
        t.completed_reward_diamond = total.diamond
        t.pending_rewards.clear()
        t.status = TaskStatus.COMPLETED
        t.completed_at = time.time()
        t.current_subtask_id = None
        return total

    def can_complete_task(self, task_id: str) -> bool:
        t = self.get(task_id)
        if not t or t.status == TaskStatus.COMPLETED:
            return False
        return not t.has_unclaimed_subtasks()

    def delete(self, task_id: str) -> bool:
        before = len(self.state.tasks)
        self.state.tasks = [t for t in self.state.tasks if t.id != task_id]
        return len(self.state.tasks) != before

    # ----- 子任务 -----
    def add_subtask(
        self,
        task_id: str,
        title: str,
        target_minutes: Optional[int] = None,
    ) -> Optional[Subtask]:
        t = self.get(task_id)
        if not t or t.status == TaskStatus.COMPLETED:
            return None
        title = (title or "").strip()
        if not title:
            return None
        if target_minutes is None:
            target_minutes = int(self.state.settings.get("subtask_default_target_minutes", 10))
        target_minutes = max(1, int(target_minutes))
        sub = Subtask(title=title, target_seconds=float(target_minutes * 60))
        t.subtasks.append(sub)
        if t.status == TaskStatus.ACTIVE and t.current_subtask_id is None:
            self._sync_current_subtask(t)
        return sub

    def confirm_manual_complete_subtask(self, task_id: str, subtask_id: str) -> bool:
        """手动确认完成：仅 mark done，不领取；须子目标时长达标。"""
        t = self.get(task_id)
        if not t or t.status == TaskStatus.COMPLETED:
            return False
        sub = self._get_subtask(t, subtask_id)
        if not sub or sub.done:
            return False
        if not t.can_complete_sub(sub):
            return False
        self._mark_subtask_done(t, sub)
        return True

    def subtask_time_met(self, task_id: str, subtask_id: str) -> bool:
        t = self.get(task_id)
        if not t:
            return False
        sub = self._get_subtask(t, subtask_id)
        if not sub:
            return False
        return t.can_complete_sub(sub)

    def claim_subtask_reward(self, task_id: str, subtask_id: str) -> Optional[Reward]:
        """领取子任务奖励：pending + 完成固定奖 → 背包。"""
        t = self.get(task_id)
        if not t:
            return None
        sub = self._get_subtask(t, subtask_id)
        if not sub or not sub.is_claimable():
            return None
        total = sub.pending_summary()
        total.gold += self._completion_bonus()
        self.state.inventory.add(total)
        sub.pending_rewards.clear()
        sub.rewards_claimed = True
        return total

    def focus_subtask(self, task_id: str, subtask_id: str) -> bool:
        """将子目标设为 current（开始累计 ops/时长/奖励）。"""
        t = self.get(task_id)
        if not t or t.status != TaskStatus.ACTIVE:
            return False
        sub = self._get_subtask(t, subtask_id)
        if not sub or sub.done:
            return False
        t.current_subtask_id = subtask_id
        return True

    def pause_subtask_focus(self, task_id: str) -> bool:
        """取消子目标聚焦（暂停子目标累计，父 ops 仍增加）。"""
        t = self.get(task_id)
        if not t or t.status != TaskStatus.ACTIVE:
            return False
        if t.current_subtask_id is None:
            return False
        t.current_subtask_id = None
        return True

    def complete_and_claim_subtask(
        self, task_id: str, subtask_id: str,
    ) -> Optional[Reward]:
        """已可领则直接领；时长达标则 mark done 后立即领取。"""
        t = self.get(task_id)
        if not t:
            return None
        sub = self._get_subtask(t, subtask_id)
        if not sub:
            return None
        if sub.is_claimable():
            return self.claim_subtask_reward(task_id, subtask_id)
        if not sub.done and t.can_complete_sub(sub):
            self._mark_subtask_done(t, sub)
            return self.claim_subtask_reward(task_id, subtask_id)
        return None

    def delete_subtask(self, task_id: str, subtask_id: str) -> bool:
        t = self.get(task_id)
        if not t or t.status == TaskStatus.COMPLETED:
            return False
        before = len(t.subtasks)
        t.subtasks = [s for s in t.subtasks if s.id != subtask_id]
        if len(t.subtasks) != before:
            self._sync_current_subtask(t)
            self._sync_task_earned_from_subtasks(t)
            return True
        return False

    def tick_active_time(self) -> bool:
        """每秒调用：累加父/子任务时长（不自动完成子目标，须手动点完成）。"""
        active = self.state.active_task()
        if active is None:
            return False
        active.active_seconds += 1
        sub = active.current_subtask()
        if sub is None:
            return False
        sub.active_seconds += 1
        return False

    def _sync_task_earned_from_subtasks(self, task: Task) -> None:
        task.sync_earned_from_subtasks()

    def _apply_roll_to_subtask(self, task: Task, sub: Subtask, reward: Reward) -> None:
        sub.pending_rewards.append(reward)
        sub.earned_gold += reward.gold
        sub.earned_diamond += reward.diamond
        self._sync_task_earned_from_subtasks(task)
        self.state.since_roll.gold += reward.gold
        self.state.since_roll.diamond += reward.diamond

    # ----- 操作数与奖励 -----
    def record_operation(self, reward: Optional[Reward]) -> None:
        """处理一次操作：父/子 ops++；有 current 子目标时才积累开奖奖励。"""
        active = self.state.active_task()
        if active is None:
            return

        active.operations += 1
        sub = active.current_subtask()
        if sub is None:
            return

        sub.operations += 1
        if reward is not None and not reward.is_empty():
            self._apply_roll_to_subtask(active, sub, reward)
