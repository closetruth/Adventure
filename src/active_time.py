"""活跃时长累加：关屏期间跳过，恢复后不跳秒。"""
from __future__ import annotations

import time
from typing import Optional


class ActiveTimeTracker:
    """基于 monotonic 差值计算每次 tick 应累加的秒数。"""

    def __init__(self) -> None:
        self._last_mono: Optional[float] = None

    def tick(self, *, counting_enabled: bool) -> float:
        now = time.monotonic()
        if self._last_mono is None:
            self._last_mono = now
            return 0.0
        delta = min(max(0.0, now - self._last_mono), 1.0)
        self._last_mono = now
        if not counting_enabled:
            return 0.0
        return delta
