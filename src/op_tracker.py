"""近 N 秒内的操作计数（滚动窗口）。"""
from __future__ import annotations

import time
from collections import deque


class OpRateTracker:
    """记录每次操作时间戳，统计最近 window_sec 内的操作数。"""

    def __init__(self, window_sec: float = 60.0):
        self.window_sec = window_sec
        self._times: deque[float] = deque()

    def record(self) -> None:
        now = time.time()
        self._times.append(now)
        self._prune(now)

    def count_recent(self) -> int:
        now = time.time()
        self._prune(now)
        return len(self._times)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_sec
        while self._times and self._times[0] < cutoff:
            self._times.popleft()
