"""皇室战争式开宝箱:解锁倒计时 + 概率开出字母收藏与货币。

纯逻辑模块,不依赖 Qt。所有函数接受 state / chest 操作,或纯 RNG 生成结果
(可传 rng=random.Random(seed) 以便测试确定性)。
"""
from __future__ import annotations

import math
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

# 字母数量:几何分布 p=0.5,0-∞ 右偏(P(1)=50%, P(2)=25%, P(3)=12.5%…,均值 2)
GEOMETRIC_P = 0.5
LETTER_COUNT_MAX = 20  # 数量截断(21+ 概率 ~1e-6,可忽略)

# 伴生货币:命中概率 + 命中后的对数正态均值(0-∞ 右偏,无上限)
GOLD_HIT_P = 0.50
DIAMOND_HIT_P = 0.20
GOLD_MEAN = (2.0, 4.0, 7.0, 12.0, 18.0)      # 普通..传奇
DIAMOND_MEAN = (0.2, 0.4, 0.9, 2.0, 4.0)
CURRENCY_SIGMA = 0.6                          # 对数正态 σ(形状参数)


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


def _unbounded_right_skewed(mean: float, rng: random.Random, sigma: float = CURRENCY_SIGMA) -> float:
    """对数正态右偏，0-∞ 无上限，期望≈mean。

    E[X] = e^(μ+σ²/2) = mean → μ = ln(mean) − σ²/2。
    众数 ≈ 0.7·mean，中位数 ≈ 0.84·mean；P(X > 10·mean) ≈ 0.02%（彩蛋尾值）。
    """
    mu = math.log(max(mean, 1e-9)) - sigma * sigma / 2
    return rng.lognormvariate(mu, sigma)


def generate_open_result(rarity: int, rng: Optional[random.Random] = None) -> OpenResult:
    """按概率分布生成一次开箱结果(纯 RNG,不修改任何状态)。

    - 字母数量:几何分布 p=0.5,0-∞ 右偏(1 个最常见)
    - 每个字母独立按权重表抽稀有度;本轮字母不重复(26 池内)
    - 伴生货币:金币/钻石各自独立按概率判断命中,命中后对数正态右偏抽金额(0-∞)
    """
    rng = rng if rng is not None else random.Random()
    rarity = max(0, min(4, int(rarity)))
    weights = LETTER_RARITY_WEIGHTS[rarity]

    count = 1
    while rng.random() >= GEOMETRIC_P and count < LETTER_COUNT_MAX:
        count += 1

    pool = [chr(ord("A") + i) for i in range(26)]
    rng.shuffle(pool)

    letters: List[Tuple[str, int]] = []
    for _ in range(count):
        rar = _weighted_rarity(weights, rng)
        letters.append((pool[len(letters)], rar))

    gold = round(_unbounded_right_skewed(GOLD_MEAN[rarity], rng), 2) if rng.random() < GOLD_HIT_P else 0.0
    diamond = round(_unbounded_right_skewed(DIAMOND_MEAN[rarity], rng), 2) if rng.random() < DIAMOND_HIT_P else 0.0

    return OpenResult(letters=letters, gold=gold, diamond=diamond)


def open_chest(state: AppState, chest: ChestItem, result: OpenResult) -> None:
    """提交开箱:移除宝箱、入账字母与货币。结果由调用方先 generate_open_result 生成。"""
    if chest in state.inventory.chests:
        state.inventory.chests.remove(chest)
    for letter, rar in result.letters:
        state.inventory.add_letter(letter, rar)
    state.inventory.gold += result.gold
    state.inventory.diamond += result.diamond
