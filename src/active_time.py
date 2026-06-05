"""任务进行中时长：有进行中任务时，定时器每触发一次 +1 秒。"""
from __future__ import annotations

from .models import AppState


class ActiveTimeTracker:
    def tick(self, state: AppState) -> None:
        active = state.active_task()
        if active is not None:
            active.active_seconds += 1
