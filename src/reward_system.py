"""奖励抽奖逻辑。每经过 N 次操作 (默认 10) 进行一次开奖。"""
from __future__ import annotations

import random
from typing import Optional

from .models import AppState, Reward


def maybe_roll(state: AppState) -> Optional[Reward]:
    """根据当前操作总数判断是否到达开奖点，若到达则进行一次开奖。

    返回值：
        - 当本次没到开奖间隔时返回 None；
        - 到达间隔但未命中返回 ``Reward()`` 空对象；
        - 命中则返回包含金币/钻石的 Reward。
    """
    s = state.settings
    interval = max(1, int(s.get("roll_interval", 10)))

    # 判断是否跨过了下一次开奖点
    next_threshold = state.last_roll_at + interval
    if state.total_operations < next_threshold:
        return None

    state.last_roll_at = (state.total_operations // interval) * interval

    chance = float(s.get("roll_chance", 0.35))
    if random.random() >= chance:
        return Reward(op_at=state.total_operations)

    diamond_chance = float(s.get("diamond_chance", 0.08))
    if random.random() < diamond_chance:
        return Reward(diamond=1, op_at=state.total_operations)

    gold_min = int(s.get("gold_min", 1))
    gold_max = max(gold_min, int(s.get("gold_max", 10)))
    return Reward(gold=random.randint(gold_min, gold_max), op_at=state.total_operations)
