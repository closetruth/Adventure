"""顶栏金币/钻石显示值：按每秒 1 点追上背包（仅内存，不入存档）。

小额（不到 1.2 点）用最短 1.2 秒，否则开奖 +0.2 一闪而过。
速率按「这一段追赶」锁定，不随剩余量变慢。
"""
from __future__ import annotations

FORMAT_EPS = 1e-4
RATE = 1.0
MIN_DURATION = 1.2


class CurrencyDisplay:
    def __init__(self, gold: float, diamond: float) -> None:
        self.gold = float(gold)
        self.diamond = float(diamond)
        self._gold_rate: float | None = None
        self._gold_target = float(gold)
        self._diamond_rate: float | None = None
        self._diamond_target = float(diamond)

    def snap_to(self, gold: float, diamond: float) -> None:
        self.gold = float(gold)
        self.diamond = float(diamond)
        self._gold_rate = None
        self._gold_target = self.gold
        self._diamond_rate = None
        self._diamond_target = self.diamond

    def caught_up(self, target_gold: float, target_diamond: float) -> bool:
        return (
            abs(self.gold - float(target_gold)) <= FORMAT_EPS
            and abs(self.diamond - float(target_diamond)) <= FORMAT_EPS
        )

    def step(self, target_gold: float, target_diamond: float, dt: float) -> bool:
        """向目标前进一步。变少立刻对齐。返回是否仍需继续 tick。"""
        self.gold, self._gold_rate, self._gold_target = _advance_lane(
            self.gold,
            float(target_gold),
            dt,
            self._gold_rate,
            self._gold_target,
        )
        self.diamond, self._diamond_rate, self._diamond_target = _advance_lane(
            self.diamond,
            float(target_diamond),
            dt,
            self._diamond_rate,
            self._diamond_target,
        )
        if self.caught_up(target_gold, target_diamond):
            self.snap_to(target_gold, target_diamond)
            return False
        return True


def _locked_rate(remaining: float) -> float:
    duration = max(remaining / RATE, MIN_DURATION)
    return remaining / duration


def _advance_lane(
    display: float,
    target: float,
    dt: float,
    rate: float | None,
    locked_target: float,
) -> tuple[float, float | None, float]:
    if display > target:
        return target, None, target
    if abs(display - target) <= FORMAT_EPS:
        return target, None, target
    remaining = target - display
    if rate is None or abs(target - locked_target) > FORMAT_EPS:
        rate = _locked_rate(remaining)
        locked_target = target
    dt = max(0.0, float(dt))
    nxt = min(target, display + rate * dt)
    if nxt >= target or abs(nxt - target) <= FORMAT_EPS:
        return target, None, target
    return nxt, rate, locked_target
