"""任务进行中时长：有进行中任务时，定时器每触发一次 +1 秒。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import AppState

if TYPE_CHECKING:
    from .task_manager import TaskManager


class ActiveTimeTracker:
    def tick(self, state: AppState, manager: "TaskManager") -> bool:
        """返回 True 表示有子任务因时长达标而自动完成。"""
        return manager.tick_active_time()
