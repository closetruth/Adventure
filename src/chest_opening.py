"""皇室战争式开宝箱:解锁倒计时 + 概率开出字母收藏与货币。

纯逻辑模块,不依赖 Qt。所有函数接受 state / chest 操作,或纯 RNG 生成结果
(可传 rng=random.Random(seed) 以便测试确定性)。
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import AppState, ChestItem

# 各稀有度解锁时长(秒):普通 30 分 / 罕见 1 小时 / 稀有 2 小时 / 史诗 4 小时 / 传奇 8 小时
UNLOCK_SPANS = (1800, 3600, 7200, 14400, 28800)
MAX_UNLOCK_SLOTS = 4

# 字母稀有度权重:行=宝箱稀有度,列=字母稀有度(普通..传奇)。
# 宝箱越稀有,开出高稀有度字母的分布越偏向高档。
LETTER_RARITY_WEIGHTS = (
    (70, 20, 7, 2, 1),   # 普通箱
    (50, 28, 15, 5, 2),  # 罕见箱
    (30, 30, 25, 12, 3), # 稀有箱
    (15, 25, 30, 22, 8), # 史诗箱
    (5, 12, 28, 30, 25), # 传奇箱
)

# 伴生货币:(命中概率, 金额下限, 金额上限);概率分布:先按概率判断是否掉落,命中后均匀抽金额
GOLD_COMPANION = (
    (0.50, 1.0, 3.0),
    (0.50, 2.0, 5.0),
    (0.50, 3.0, 8.0),
    (0.50, 5.0, 15.0),
    (0.50, 10.0, 30.0),
)
DIAMOND_COMPANION = (
    (0.20, 0.1, 0.5),
    (0.20, 0.2, 1.0),
    (0.20, 0.5, 2.0),
    (0.20, 1.0, 4.0),
    (0.20, 2.0, 8.0),
)

# 每箱开出字母数范围(按宝箱稀有度)
LETTERS_PER_CHEST = ((3, 4), (3, 4), (3, 5), (4, 5), (4, 5))

# 保底:每箱至少 1 个字母稀有度 ≥ 此值(避免整箱全普通)
MIN_LETTER_RARITY_GUARANTEE = 1


@dataclass
class OpenResult:
    """一次开箱的结果(已由概率分布生成,提交前可预览)。"""
    letters: List[Tuple[str, int]] = field(default_factory=list)  # (字母, 稀有度)
    gold: float = 0.0
    diamond: float = 0.0


def unlock_span_seconds(rarity: int) -> int:
    rarity = max(0, min(4, int(rarity)))
    return UNLOCK_SPANS[rarity]


def is_ready(chest: ChestItem, now: Optional[float] = None) -> bool:
    """解锁倒计时是否结束。"""
    if chest.unlock_started_at is None:
        return False
    now = time.time() if now is None else now
    return now - chest.unlock_started_at >= unlock_span_seconds(chest.rarity)


def remaining_seconds(chest: ChestItem, now: Optional[float] = None) -> int:
    """剩余解锁秒数(向上取整);未解锁按完整时长计,已就绪为 0。"""
    span = unlock_span_seconds(chest.rarity)
    if chest.unlock_started_at is None:
        return span
    now = time.time() if now is None else now
    return max(0, int(-(-(chest.unlock_started_at + span - now) // 1)))


def unlocking_chests(state: AppState, now: Optional[float] = None) -> List[ChestItem]:
    """解锁中(已开始、未就绪)的箱子。"""
    return [
        c for c in state.inventory.chests
        if c.unlock_started_at is not None and not is_ready(c, now=now)
    ]


def ready_chests(state: AppState, now: Optional[float] = None) -> List[ChestItem]:
    """倒计时结束、可开箱的箱子。"""
    return [c for c in state.inventory.chests if is_ready(c, now=now)]


def locked_chests(state: AppState) -> List[ChestItem]:
    """未开始解锁的箱子。"""
    return [c for c in state.inventory.chests if c.unlock_started_at is None]


def slots_available(state: AppState, now: Optional[float] = None) -> bool:
    """是否有空解锁槽位(最多 MAX_UNLOCK_SLOTS 个同时解锁)。"""
    return len(unlocking_chests(state, now=now)) < MAX_UNLOCK_SLOTS


def start_unlock(state: AppState, chest: ChestItem, now: Optional[float] = None) -> bool:
    """开始解锁一个未解锁的箱子;槽位已满或已在解锁/已就绪则失败。"""
    if chest not in state.inventory.chests:
        return False
    if chest.unlock_started_at is not None:
        return False
    if not slots_available(state, now=now):
        return False
    chest.unlock_started_at = time.time() if now is None else now
    return True


def _weighted_rarity(weights: Tuple[int, int, int, int, int], rng: random.Random) -> int:
    total = sum(weights)
    roll = rng.randrange(total)
    acc = 0
    for r, w in enumerate(weights):
        acc += w
        if roll < acc:
            return r
    return len(weights) - 1


def generate_open_result(rarity: int, rng: Optional[random.Random] = None) -> OpenResult:
    """按概率分布生成一次开箱结果(纯 RNG,不修改任何状态)。

    - 字母 3-5 个槽,每槽独立按权重表抽稀有度
    - 保底:至少 1 个字母稀有度 ≥ MIN_LETTER_RARITY_GUARANTEE
    - 本轮字母不重复(26 池内)
    - 伴生货币:金币/钻石各自独立按概率判断,命中则均匀抽金额
    """
    rng = rng if rng is not None else random.Random()
    rarity = max(0, min(4, int(rarity)))
    weights = LETTER_RARITY_WEIGHTS[rarity]

    count = rng.randint(*LETTERS_PER_CHEST[rarity])
    pool = [chr(ord("A") + i) for i in range(26)]
    rng.shuffle(pool)

    letters: List[Tuple[str, int]] = []
    for _ in range(count):
        rar = _weighted_rarity(weights, rng)
        letters.append((pool[len(letters)], rar))

    # 保底:至少一个字母 ≥ 保底稀有度
    if not any(r >= MIN_LETTER_RARITY_GUARANTEE for _, r in letters):
        idx = rng.randrange(len(letters))
        rar = _weighted_rarity(
            tuple(weights[r] if r >= MIN_LETTER_RARITY_GUARANTEE else 0
                  for r in range(5)),
            rng,
        )
        letters[idx] = (letters[idx][0], rar)

    gold_p, gold_min, gold_max = GOLD_COMPANION[rarity]
    diamond_p, diamond_min, diamond_max = DIAMOND_COMPANION[rarity]
    gold = rng.uniform(gold_min, gold_max) if rng.random() < gold_p else 0.0
    diamond = rng.uniform(diamond_min, diamond_max) if rng.random() < diamond_p else 0.0

    return OpenResult(letters=letters, gold=round(gold, 2), diamond=round(diamond, 2))


def open_chest(state: AppState, chest: ChestItem, result: OpenResult) -> None:
    """提交开箱:移除宝箱、入账字母与货币。结果由调用方先 generate_open_result 生成。"""
    if chest in state.inventory.chests:
        state.inventory.chests.remove(chest)
    for letter, rar in result.letters:
        state.inventory.add_letter(letter, rar)
    state.inventory.gold += result.gold
    state.inventory.diamond += result.diamond
