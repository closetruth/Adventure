"""任务 CRUD 与状态变更逻辑。"""
from __future__ import annotations

import time
from typing import List, Optional

from .models import AppState, Reward, Task, TaskStatus


class TaskManager:
    def __init__(self, state: AppState):
        self.state = state

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

    # ----- 变更 -----
    def create(self, title: str, note: str = "") -> Task:
        title = (title or "").strip() or "未命名任务"
        # 若已有 active 任务，新任务默认 paused (一次只允许一个活动任务)
        has_active = self.state.active_task() is not None
        status = TaskStatus.PAUSED if has_active else TaskStatus.ACTIVE
        task = Task(title=title, note=note, status=status)
        self.state.tasks.insert(0, task)
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
        # 先把当前 active 任务暂停
        current = self.state.active_task()
        if current and current.id != t.id:
            current.status = TaskStatus.PAUSED
        t.status = TaskStatus.ACTIVE
        return t

    def complete(self, task_id: str) -> Optional[Reward]:
        """完成任务并把待领取奖励转入背包，返回本次结算的总奖励。"""
        t = self.get(task_id)
        if not t or t.status == TaskStatus.COMPLETED:
            return None
        total = t.pending_summary()
        self.state.inventory.add(total)
        t.pending_rewards.clear()
        t.status = TaskStatus.COMPLETED
        t.completed_at = time.time()
        return total

    def delete(self, task_id: str) -> bool:
        before = len(self.state.tasks)
        self.state.tasks = [t for t in self.state.tasks if t.id != task_id]
        return len(self.state.tasks) != before

    # ----- 操作数与奖励 -----
    def record_operation(self, reward: Optional[Reward]) -> None:
        """处理一次操作：累加 active 任务的操作数，若有奖励则压入其待领取队列。"""
        active = self.state.active_task()
        if active is not None:
            active.operations += 1
            if reward is not None and not reward.is_empty():
                active.pending_rewards.append(reward)
