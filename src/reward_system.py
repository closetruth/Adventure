"""奖励抽奖逻辑：内置随机开奖间隔与参数，每 10 分钟重抽概率/范围。"""
from __future__ import annotations

import colorsys
import logging
import math
import random
import time
from typing import List, Optional, Sequence, Tuple

from .models import AppState, Reward, RollAccum, RollHistoryEntry, RollPoint

logger = logging.getLogger(__name__)

# 内置随机范围（无设置 UI）
INTERVAL_MIN = 6
INTERVAL_MAX = 14
# 金币/钻石掉落概率互相独立（到开奖点时各自判定）
GOLD_CHANCE_MIN = 0.22
GOLD_CHANCE_MAX = 0.48
DIAMOND_CHANCE_MIN = 0.03
DIAMOND_CHANCE_MAX = 0.10
GOLD_MIN_RANGE = (0.08, 0.15)
GOLD_MAX_RANGE = (1.0, 2.0)
DIAMOND_MIN_RANGE = (0.01, 0.03)
DIAMOND_MAX_RANGE = (0.12, 0.35)
SHUFFLE_INTERVAL_SEC = 600

# 落点连通画布
CONNECT_DIST = 0.24
POINT_MARGIN = 0.10


def _rand_float(lo: float, hi: float) -> float:
    return random.uniform(lo, hi)


def _right_skewed(lo: float, hi: float, *, sigma: float = 0.55) -> float:
    """多数靠近 lo，偶发靠近 hi（截断对数正态）。"""
    if hi <= lo:
        return float(lo)
    # 使对数正态中位数落在区间偏左（约 25% 分位）
    median = lo + 0.25 * (hi - lo)
    mu = math.log(max(median, 1e-9))
    x = median
    for _ in range(24):
        x = random.lognormvariate(mu, sigma)
        if lo <= x <= hi:
            return x
    return max(lo, min(hi, x))


def _random_point_color() -> str:
    """生成高饱和随机色相。"""
    hue = random.random()
    r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.85)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _random_roll_point() -> RollPoint:
    lo = POINT_MARGIN
    hi = 1.0 - POINT_MARGIN
    return RollPoint(
        x=random.uniform(lo, hi),
        y=random.uniform(lo, hi),
        color=_random_point_color(),
    )


def _largest_cluster_size(points: Sequence[RollPoint]) -> int:
    """返回落点中最大连通簇的大小。"""
    n = len(points)
    if n == 0:
        return 0
    if n == 1:
        return 1

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    dist_sq = CONNECT_DIST * CONNECT_DIST
    for i in range(n):
        pi = points[i]
        for j in range(i + 1, n):
            pj = points[j]
            dx = pi.x - pj.x
            dy = pi.y - pj.y
            if dx * dx + dy * dy <= dist_sq:
                union(i, j)

    sizes: dict[int, int] = {}
    for i in range(n):
        root = find(i)
        sizes[root] = sizes.get(root, 0) + 1
    return max(sizes.values())


def largest_cluster_indices(points: Sequence[RollPoint]) -> List[int]:
    """返回最大连通簇内各落点的下标。"""
    n = len(points)
    if n == 0:
        return []
    if n == 1:
        return [0]

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    dist_sq = CONNECT_DIST * CONNECT_DIST
    for i in range(n):
        pi = points[i]
        for j in range(i + 1, n):
            pj = points[j]
            dx = pi.x - pj.x
            dy = pi.y - pj.y
            if dx * dx + dy * dy <= dist_sq:
                union(i, j)

    sizes: dict[int, int] = {}
    members: dict[int, List[int]] = {}
    for i in range(n):
        root = find(i)
        sizes[root] = sizes.get(root, 0) + 1
        members.setdefault(root, []).append(i)

    best_root = max(sizes, key=lambda r: sizes[r])
    return members[best_root]


def add_roll_point(state: AppState) -> None:
    """每次操作在画布上追加一个随机落点。"""
    state.roll_runtime.roll_points.append(_random_roll_point())


def _backfill_roll_points(state: AppState) -> None:
    """旧存档迁移：用本周期操作数补齐落点（仅执行一次）。"""
    rt = state.roll_runtime
    if rt.roll_points_backfilled:
        return
    rt.roll_points_backfilled = True
    if rt.roll_points:
        return
    progress = max(0, state.total_operations - state.last_roll_at)
    if progress <= 0:
        return
    rt.roll_points = [_random_roll_point() for _ in range(progress)]
    logger.debug("迁移补齐落点: count=%d", progress)


def reshuffle_roll_params(state: AppState) -> None:
    """在内置范围内重抽概率与奖励数值。"""
    rt = state.roll_runtime
    rt.gold_chance = round(_right_skewed(GOLD_CHANCE_MIN, GOLD_CHANCE_MAX), 3)
    rt.diamond_chance = round(_right_skewed(DIAMOND_CHANCE_MIN, DIAMOND_CHANCE_MAX), 3)
    rt.gold_min = round(_rand_float(*GOLD_MIN_RANGE), 2)
    rt.gold_max = round(_rand_float(*GOLD_MAX_RANGE), 2)
    if rt.gold_max < rt.gold_min:
        rt.gold_min, rt.gold_max = rt.gold_max, rt.gold_min
    rt.diamond_min = round(_rand_float(*DIAMOND_MIN_RANGE), 2)
    rt.diamond_max = round(_rand_float(*DIAMOND_MAX_RANGE), 2)
    if rt.diamond_max < rt.diamond_min:
        rt.diamond_min, rt.diamond_max = rt.diamond_max, rt.diamond_min
    rt.last_shuffle_at = time.time()
    logger.info(
        "重抽开奖参数: gold=%.1f%% diamond=%.1f%% gold_amt=%.2f~%.2f diam_amt=%.2f~%.2f",
        rt.gold_chance * 100,
        rt.diamond_chance * 100,
        rt.gold_min,
        rt.gold_max,
        rt.diamond_min,
        rt.diamond_max,
    )


def start_new_roll_cycle(state: AppState) -> None:
    """开奖后开启新周期：随机间隔 + 清空落点。"""
    rt = state.roll_runtime
    rt.roll_span = random.randint(INTERVAL_MIN, INTERVAL_MAX)
    rt.next_roll_at = state.total_operations + rt.roll_span
    rt.roll_points = []
    logger.debug(
        "新开奖周期: span=%d",
        rt.roll_span,
    )


def _migrate_roll_runtime(state: AppState) -> None:
    """旧存档迁移：用 settings 初始化 roll_runtime。"""
    s = state.settings
    interval = max(1, int(s.get("roll_interval", 10)))
    rt = state.roll_runtime

    if rt.roll_span < 1:
        rt.roll_span = interval

    if rt.last_shuffle_at <= 0:
        if "gold_chance" in s:
            rt.gold_chance = float(s.get("gold_chance", 0.35))
        else:
            rt.gold_chance = float(s.get("roll_chance", 0.35))
        rt.diamond_chance = float(s.get("diamond_chance", 0.06))
        rt.gold_min = float(s.get("gold_min", 0.1))
        rt.gold_max = max(rt.gold_min, float(s.get("gold_max", 1.0)))
        rt.diamond_min = float(s.get("diamond_min", 0.01))
        rt.diamond_max = max(rt.diamond_min, float(s.get("diamond_max", 0.1)))
        reshuffle_roll_params(state)

    _backfill_roll_points(state)


def ensure_roll_runtime(state: AppState) -> None:
    """启动/加载时补齐 roll_runtime；超时则立即重抽。"""
    _migrate_roll_runtime(state)
    rt = state.roll_runtime
    if time.time() - rt.last_shuffle_at >= SHUFFLE_INTERVAL_SEC:
        reshuffle_roll_params(state)


def roll_progress(state: AppState) -> Tuple[int, int]:
    """返回 (最大连通簇大小, 本周期目标格数)。"""
    rt = state.roll_runtime
    span = max(1, rt.roll_span)
    cluster = _largest_cluster_size(rt.roll_points)
    return min(cluster, span), span


def _append_roll_history(state: AppState, reward: Reward) -> None:
    active = state.active_task()
    entry = RollHistoryEntry(
        op_at=state.total_operations,
        hit=not reward.is_empty(),
        gold=reward.gold,
        diamond=reward.diamond,
        task_title=active.title if active else "",
    )
    state.roll_history.insert(0, entry)
    max_len = max(10, int(state.settings.get("roll_history_max", 100)))
    if len(state.roll_history) > max_len:
        del state.roll_history[max_len:]


def maybe_roll(state: AppState) -> Optional[Reward]:
    """根据最大连通簇是否达到 roll_span 判断是否开奖。

    金币与钻石概率互相独立：同一次开奖可同时掉落、只掉一种、或都不掉。

    返回值：
        - 当本次没到开奖点时返回 None；
        - 到达间隔但未命中返回 ``Reward()`` 空对象；
        - 命中则返回包含金币和/或钻石的 Reward。
    """
    ensure_roll_runtime(state)
    rt = state.roll_runtime
    cluster_size = _largest_cluster_size(rt.roll_points)

    if cluster_size < rt.roll_span:
        return None

    state.last_roll_at = state.total_operations
    state.since_roll = RollAccum()

    gold = 0.0
    diamond = 0.0
    if random.random() < rt.gold_chance:
        gold_min = rt.gold_min
        gold_max = max(gold_min, rt.gold_max)
        gold = round(_right_skewed(gold_min, gold_max), 1)
    if random.random() < rt.diamond_chance:
        dmin = rt.diamond_min
        dmax = max(dmin, rt.diamond_max)
        # 金额界面只显示 1 位小数；命中后至少保留 0.1，避免 0.01～0.04
        # 被四舍五入成 0，继而被误记为“未中奖”且不触发钻石音效。
        diamond = max(0.1, round(_right_skewed(dmin, dmax), 1))

    reward = Reward(gold=gold, diamond=diamond, op_at=state.total_operations)
    if reward.is_empty():
        logger.debug("开奖落空 (ops=%d cluster=%d)", state.total_operations, cluster_size)
    else:
        logger.info(
            "开奖命中 gold=%.1f diamond=%.1f (ops=%d cluster=%d)",
            reward.gold,
            reward.diamond,
            state.total_operations,
            cluster_size,
        )
    _append_roll_history(state, reward)
    start_new_roll_cycle(state)
    return reward
