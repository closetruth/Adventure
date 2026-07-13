"""奖励抽奖逻辑：内置随机开奖间隔与参数，每 10 分钟重抽概率/范围。"""
from __future__ import annotations

import colorsys
import logging
import random
import time
from typing import List, Optional

from .models import AppState, Reward, RollAccum, RollHistoryEntry

logger = logging.getLogger(__name__)

# 内置随机范围（无设置 UI）
INTERVAL_MIN = 6
INTERVAL_MAX = 14
CHANCE_MIN = 0.22
CHANCE_MAX = 0.48
DIAMOND_CHANCE_MIN = 0.05
DIAMOND_CHANCE_MAX = 0.14
GOLD_MIN_RANGE = (0.08, 0.15)
GOLD_MAX_RANGE = (0.8, 1.2)
DIAMOND_MIN_RANGE = (0.01, 0.03)
DIAMOND_MAX_RANGE = (0.08, 0.15)
SHUFFLE_INTERVAL_SEC = 600


def _rand_float(lo: float, hi: float) -> float:
    return random.uniform(lo, hi)


def generate_segment_colors(span: int) -> List[str]:
    """为本周期每格生成随机色相（固定饱和度/亮度）。"""
    colors: List[str] = []
    for _ in range(max(1, span)):
        hue = random.random()
        r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.75)
        colors.append(
            f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
        )
    return colors


def reshuffle_roll_params(state: AppState) -> None:
    """在内置范围内重抽概率与奖励数值。"""
    rt = state.roll_runtime
    rt.roll_chance = round(_rand_float(CHANCE_MIN, CHANCE_MAX), 3)
    rt.diamond_chance = round(_rand_float(DIAMOND_CHANCE_MIN, DIAMOND_CHANCE_MAX), 3)
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
        "重抽开奖参数: chance=%.1f%% diamond=%.1f%% gold=%.2f~%.2f diam=%.2f~%.2f",
        rt.roll_chance * 100,
        rt.diamond_chance * 100,
        rt.gold_min,
        rt.gold_max,
        rt.diamond_min,
        rt.diamond_max,
    )


def start_new_roll_cycle(state: AppState) -> None:
    """开奖后开启新周期：随机间隔 + 新颜色片段。"""
    rt = state.roll_runtime
    rt.roll_span = random.randint(INTERVAL_MIN, INTERVAL_MAX)
    rt.next_roll_at = state.total_operations + rt.roll_span
    rt.segment_colors = generate_segment_colors(rt.roll_span)
    logger.debug(
        "新开奖周期: span=%d next_at=%d",
        rt.roll_span,
        rt.next_roll_at,
    )


def _migrate_roll_runtime(state: AppState) -> None:
    """旧存档迁移：用 settings 初始化 roll_runtime。"""
    s = state.settings
    interval = max(1, int(s.get("roll_interval", 10)))
    rt = state.roll_runtime

    if rt.next_roll_at <= state.last_roll_at:
        rt.roll_span = interval
        rt.next_roll_at = state.last_roll_at + interval
    else:
        expected_span = max(1, rt.next_roll_at - state.last_roll_at)
        if rt.roll_span != expected_span:
            rt.roll_span = expected_span

    if not rt.segment_colors or len(rt.segment_colors) != rt.roll_span:
        rt.segment_colors = generate_segment_colors(rt.roll_span)

    if rt.last_shuffle_at <= 0:
        rt.roll_chance = float(s.get("roll_chance", 0.35))
        rt.diamond_chance = float(s.get("diamond_chance", 0.08))
        rt.gold_min = float(s.get("gold_min", 0.1))
        rt.gold_max = max(rt.gold_min, float(s.get("gold_max", 1.0)))
        rt.diamond_min = float(s.get("diamond_min", 0.01))
        rt.diamond_max = max(rt.diamond_min, float(s.get("diamond_max", 0.1)))
        reshuffle_roll_params(state)


def ensure_roll_runtime(state: AppState) -> None:
    """启动/加载时补齐 roll_runtime；超时则立即重抽。"""
    _migrate_roll_runtime(state)
    rt = state.roll_runtime
    if time.time() - rt.last_shuffle_at >= SHUFFLE_INTERVAL_SEC:
        reshuffle_roll_params(state)


def roll_progress(state: AppState) -> tuple[int, int]:
    """返回 (当前进度, 本周期总格数)。"""
    rt = state.roll_runtime
    span = max(1, rt.next_roll_at - state.last_roll_at)
    progress = max(0, min(state.total_operations - state.last_roll_at, span))
    return progress, span


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
    """根据 roll_runtime 判断是否到达开奖点，到达则开奖并开启新周期。

    返回值：
        - 当本次没到开奖点时返回 None；
        - 到达间隔但未命中返回 ``Reward()`` 空对象；
        - 命中则返回包含金币/钻石的 Reward。
    """
    ensure_roll_runtime(state)
    rt = state.roll_runtime

    if state.total_operations < rt.next_roll_at:
        return None

    state.last_roll_at = state.total_operations
    state.since_roll = RollAccum()

    if random.random() >= rt.roll_chance:
        reward = Reward(op_at=state.total_operations)
        logger.debug("开奖落空 (ops=%d)", state.total_operations)
        _append_roll_history(state, reward)
        start_new_roll_cycle(state)
        return reward

    if random.random() < rt.diamond_chance:
        dmin = rt.diamond_min
        dmax = max(dmin, rt.diamond_max)
        reward = Reward(
            diamond=round(random.uniform(dmin, dmax), 1),
            op_at=state.total_operations,
        )
        logger.info("开奖命中钻石 %.1f (ops=%d)", reward.diamond, state.total_operations)
        _append_roll_history(state, reward)
        start_new_roll_cycle(state)
        return reward

    gold_min = rt.gold_min
    gold_max = max(gold_min, rt.gold_max)
    reward = Reward(
        gold=round(random.uniform(gold_min, gold_max), 1),
        op_at=state.total_operations,
    )
    logger.info("开奖命中金币 %.1f (ops=%d)", reward.gold, state.total_operations)
    _append_roll_history(state, reward)
    start_new_roll_cycle(state)
    return reward
