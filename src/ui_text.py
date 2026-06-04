"""界面文案格式化（避免 emoji 在 Windows 默认字体下显示为方框）。"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Iterable, List

if TYPE_CHECKING:
    from .models import RollHistoryEntry


def format_duration(seconds: float) -> str:
    """进行中累计时长（秒 → 可读字符串）。"""
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def format_amount(value: float) -> str:
    """金额显示：最多 1 位小数，整数不带 .0。"""
    v = round(float(value), 1)
    if abs(v - int(v)) < 1e-9:
        return str(int(v))
    return f"{v:.1f}"


def format_pending(gold: float, diamond: float) -> str:
    """待领取奖励一行文案。"""
    parts = []
    if gold:
        parts.append(f"金币 {format_amount(gold)}")
    if diamond:
        parts.append(f"钻石 {format_amount(diamond)}")
    if not parts:
        return "待领 无"
    return "待领 " + " · ".join(parts)


def format_reward_gain(gold: float, diamond: float) -> str:
    """完成任务时的奖励说明。"""
    parts = []
    if gold:
        parts.append(f"{format_amount(gold)} 金币")
    if diamond:
        parts.append(f"{format_amount(diamond)} 钻石")
    if not parts:
        return "无奖励"
    return "、".join(parts)


def format_since_roll(gold: float, diamond: float) -> str:
    """上次开奖获得的奖励（单行）。"""
    parts = []
    if gold:
        parts.append(f"金币 {format_amount(gold)}")
    if diamond:
        parts.append(f"钻石 {format_amount(diamond)}")
    if not parts:
        return "未获得"
    return " · ".join(parts)


def format_roll_history_line(entry: "RollHistoryEntry", *, include_time: bool = False) -> str:
    """单条开奖历史。"""
    op = f"#{entry.op_at}"
    if not entry.hit:
        text = f"{op}  未中奖"
    else:
        parts = []
        if entry.gold:
            parts.append(f"+{format_amount(entry.gold)} 金币")
        if entry.diamond:
            parts.append(f"+{format_amount(entry.diamond)} 钻石")
        text = f"{op}  {' · '.join(parts)}"
    if include_time:
        ts = time.strftime("%m-%d %H:%M", time.localtime(entry.at))
        return f"{ts}  {text}"
    return text


def format_roll_history_lines(
    entries: Iterable["RollHistoryEntry"],
    *,
    limit: int | None = None,
    include_time: bool = False,
) -> List[str]:
    items = list(entries)
    if limit is not None:
        items = items[:limit]
    if not items:
        return ["暂无开奖记录"]
    return [format_roll_history_line(e, include_time=include_time) for e in items]
