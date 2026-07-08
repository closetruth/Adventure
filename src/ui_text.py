"""界面文案格式化（避免 emoji 在 Windows 默认字体下显示为方框）。"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Iterable, List

if TYPE_CHECKING:
    from .models import RollHistoryEntry, Subtask, Task
else:
    from .models import Subtask, Task


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


def format_duration_compact(seconds: float, target_seconds: float) -> str:
    """悬浮窗子目标行：短时长，如 3/10m。"""
    sec = int(max(0, seconds))
    tgt = int(max(1, target_seconds))
    m_sec = sec // 60
    m_tgt = max(1, (tgt + 59) // 60)
    return f"{m_sec}/{m_tgt}m"


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# 子目标区：深色底 + 彩色数据（避免一片白）
_COLOR_OPS = "#6ee7a0"
_COLOR_GOLD = "#f5c842"
_COLOR_DIAM = "#5ec8f2"
_COLOR_TIME = "#8b93a8"
_COLOR_TEXT = "#c8ceda"
_COLOR_MUTED = "#6e7588"
_COLOR_CURRENT = "#7eb4ff"
_COLOR_MARKER = "#5a6175"
_COLOR_WARN = "#e6a830"
_COLOR_CLAIM = "#f0c040"

_BASE_FONT = "font-family:'Microsoft YaHei UI','Microsoft YaHei','Segoe UI',sans-serif;"


def _font(size: int) -> str:
    return f"font-size:{size}px;{_BASE_FONT}"


def _muted_sep() -> str:
    return f'<span style="color:{_COLOR_MUTED}"> · </span>'


def format_global_summary_html(
    total_ops: int,
    gold: float,
    diamond: float,
    *,
    ops_1min: int | None = None,
) -> str:
    """悬浮窗顶栏：总操作 / 背包金币 / 钻石（RichText）。"""
    parts: list[str] = []
    if ops_1min is not None:
        parts.append(
            f'<span style="color:{_COLOR_MUTED}">近1分 </span>'
            f'<span style="color:{_COLOR_OPS};font-weight:700">{ops_1min}</span>'
        )
    parts.extend([
        f'<span style="color:{_COLOR_MUTED}">总操作 </span>'
        f'<span style="color:{_COLOR_OPS};font-weight:700">{total_ops:,}</span>',
        f'<span style="color:{_COLOR_MUTED}">金币 </span>'
        f'<span style="color:{_COLOR_GOLD};font-weight:700">{format_amount(gold)}</span>',
        f'<span style="color:{_COLOR_MUTED}">钻石 </span>'
        f'<span style="color:{_COLOR_DIAM if diamond else _COLOR_MUTED};font-weight:700">'
        f"{format_amount(diamond)}</span>",
    ])
    return f'<span style="{_font(11)}">' + _muted_sep().join(parts) + "</span>"


def format_roll_history_line_html(
    entry: "RollHistoryEntry",
    *,
    compact: bool = True,
) -> str:
    """单条开奖历史（RichText）。"""
    op = f'<span style="color:{_COLOR_MUTED}">#{entry.op_at}</span>'
    if not entry.hit:
        miss = "-" if compact else "未中奖"
        return f'{op} <span style="color:{_COLOR_MUTED}">{miss}</span>'
    reward_parts: list[str] = []
    if entry.gold:
        suffix = "金" if compact else " 金币"
        reward_parts.append(
            f'<span style="color:{_COLOR_GOLD};font-weight:700">'
            f"+{format_amount(entry.gold)}{suffix}</span>"
        )
    if entry.diamond:
        suffix = "钻" if compact else " 钻石"
        reward_parts.append(
            f'<span style="color:{_COLOR_DIAM};font-weight:700">'
            f"+{format_amount(entry.diamond)}{suffix}</span>"
        )
    gap = " " if compact else f' <span style="color:{_COLOR_MUTED}">·</span> '
    return f"{op} {gap.join(reward_parts)}"


def format_roll_history_lines_html(
    entries: Iterable["RollHistoryEntry"],
    *,
    limit: int | None = None,
    compact: bool = True,
) -> str:
    """悬浮窗开奖历史多行 HTML。"""
    items = list(entries)
    if limit is not None:
        items = items[:limit]
    if not items:
        return (
            f'<span style="{_font(10)}color:{_COLOR_MUTED}">'
            f"暂无开奖记录</span>"
        )
    lines = [
        format_roll_history_line_html(e, compact=compact) for e in items
    ]
    return f'<span style="{_font(10)}">' + "<br/>".join(lines) + "</span>"


def format_subgoal_runtime_html(sub: Subtask) -> str:
    """子目标运行时长（RichText）。"""
    runtime = format_duration(sub.active_seconds)
    if sub.done:
        return (
            f'<span style="color:{_COLOR_MUTED}">运行 </span>'
            f'<span style="color:{_COLOR_TIME};font-weight:700">{runtime}</span>'
        )
    target = format_duration(sub.target_seconds)
    runtime_color = _COLOR_OPS if sub.time_target_met() else _COLOR_TIME
    return (
        f'<span style="color:{_COLOR_MUTED}">运行 </span>'
        f'<span style="color:{runtime_color};font-weight:700">{runtime}</span>'
        f'<span style="color:{_COLOR_MUTED}"> / </span>'
        f'<span style="color:{_COLOR_MUTED}">{target}</span>'
    )


def format_widget_runtime_html(
    since_gold: float,
    since_diamond: float,
    duration: str = "",
    *,
    sub_duration: str = "",
) -> str:
    """悬浮窗目标区副行：上次获得 / 目标运行 / 子目标运行。"""
    parts: list[str] = []
    since_parts: list[str] = []
    if since_gold:
        since_parts.append(
            f'<span style="color:{_COLOR_GOLD};font-weight:700">'
            f"金币 {format_amount(since_gold)}</span>"
        )
    if since_diamond:
        since_parts.append(
            f'<span style="color:{_COLOR_DIAM};font-weight:700">'
            f"钻石 {format_amount(since_diamond)}</span>"
        )
    if since_parts:
        since_body = f'<span style="color:{_COLOR_MUTED}"> · </span>'.join(since_parts)
        parts.append(
            f'<span style="color:{_COLOR_MUTED}">上次 </span>{since_body}'
        )
    else:
        parts.append(
            f'<span style="color:{_COLOR_MUTED}">上次 </span>'
            f'<span style="color:{_COLOR_MUTED}">未获得</span>'
        )
    if duration:
        parts.append(
            f'<span style="color:{_COLOR_MUTED}">目标运行 </span>'
            f'<span style="color:{_COLOR_TIME};font-weight:700">'
            f"{_html_escape(duration)}</span>"
        )
    if sub_duration:
        parts.append(
            f'<span style="color:{_COLOR_MUTED}">子目标 </span>'
            f'<span style="color:{_COLOR_TIME};font-weight:700">'
            f"{_html_escape(sub_duration)}</span>"
        )
    return f'<span style="{_font(12)}">' + _muted_sep().join(parts) + "</span>"


def format_timestamp_short(ts: float | None) -> str:
    """短日期时间，用于子目标行。"""
    if ts is None:
        return ""
    return time.strftime("%m-%d %H:%M", time.localtime(ts))


def _format_subgoal_dates_html(sub: Subtask) -> str:
    parts: list[str] = []
    created = format_timestamp_short(sub.created_at)
    if created:
        parts.append(f"创 {created}")
    completed = format_timestamp_short(sub.completed_at)
    if completed:
        parts.append(f"完 {completed}")
    if not parts:
        return ""
    joined = " · ".join(parts)
    return (
        f'<br/><span style="color:{_COLOR_MUTED};font-size:11px;">'
        f"&nbsp;&nbsp;{joined}</span>"
    )


def format_subgoal_line_html(sub: Subtask, *, is_current: bool) -> str:
    """悬浮窗子目标行（RichText HTML）。"""
    if sub.done:
        marker = "●" if sub.is_claimable() else "✓"
    elif is_current:
        marker = "●"
    else:
        marker = "○"

    title = _html_escape(sub.title)
    title_weight = "font-weight:600;" if is_current and not sub.done else "font-weight:500;"
    if sub.is_claimable():
        title_color = _COLOR_CLAIM
        title_weight = "font-weight:700;"
    elif is_current and not sub.done:
        title_color = _COLOR_CURRENT
    else:
        title_color = _COLOR_TEXT

    if (
        not sub.done
        and sub.active_seconds <= 0
        and not is_current
        and sub.operations <= 0
    ):
        inner = (
            f'<span style="color:{_COLOR_MUTED}">{marker}</span> '
            f'<span style="color:{_COLOR_MUTED};font-weight:500;">{title}</span>  '
            f'<span style="color:{_COLOR_MUTED}">未开始</span>'
            f"{_format_subgoal_dates_html(sub)}"
        )
        return f'<span style="{_font(13)}">{inner}</span>'

    stats: list[str] = [
        f'<span style="color:{_COLOR_OPS};font-weight:700">操作{sub.operations}</span>',
        f'<span style="color:{_COLOR_GOLD};font-weight:700">金{format_amount(sub.earned_gold)}</span>',
    ]
    if sub.earned_diamond:
        stats.append(
            f'<span style="color:{_COLOR_DIAM};font-weight:700">'
            f"钻{format_amount(sub.earned_diamond)}</span>"
        )
    else:
        stats.append(
            f'<span style="color:{_COLOR_MUTED};font-weight:600">钻0</span>'
        )
    stat_html = "  ".join(stats)

    runtime_html = ""
    if sub.active_seconds > 0 or sub.done or is_current:
        runtime_html = f'  {format_subgoal_runtime_html(sub)}'

    marker_color = _COLOR_CURRENT if is_current and not sub.done else (
        _COLOR_CLAIM if sub.is_claimable() else _COLOR_MARKER
    )
    inner = (
        f'<span style="color:{marker_color};font-weight:700">{marker}</span> '
        f'<span style="color:{title_color};{title_weight}">{title}</span>'
        f'<br/>'
        f'<span style="color:{_COLOR_MUTED};font-size:11px;">&nbsp;&nbsp;</span>'
        f"{stat_html}{runtime_html}"
        f"{_format_subgoal_dates_html(sub)}"
    )
    return f'<span style="{_font(13)}">{inner}</span>'


def format_subgoals_focus_hint_html(active: Task) -> str:
    """有未完成子目标但未聚焦时的提示。"""
    if not active.subtasks:
        return ""
    if active.current_subtask() is not None:
        return ""
    if all(s.done for s in active.subtasks):
        return ""
    return (
        f'<span style="{_font(12)}color:{_COLOR_WARN};font-weight:600">'
        f"未聚焦子目标，奖励暂停累计</span>"
    )


def format_subgoals_list_html(active: Task) -> str:
    """悬浮窗：全部子目标 HTML 列表。"""
    if not active.subtasks:
        return (
            f'<span style="{_font(12)}color:{_COLOR_MUTED}">'
            f"添加子目标后开始累计奖励</span>"
        )

    current = active.current_subtask()
    current_id = current.id if current is not None else None
    lines = [
        format_subgoal_line_html(sub, is_current=sub.id == current_id)
        for sub in active.subtasks
    ]
    if active.has_unclaimed_subtasks():
        lines.append(
            f'<span style="{_font(12)}color:{_COLOR_CLAIM};font-weight:700">'
            f"有子目标奖励待领取</span>"
        )
    return "<br>".join(lines)


def format_goal_compact_html(operations: int, gold: float, diamond: float) -> str:
    """悬浮窗父目标紧凑统计一行。"""
    parts = [
        f'<span style="color:{_COLOR_OPS};font-weight:700">操作 {operations}</span>',
        f'<span style="color:{_COLOR_GOLD};font-weight:700">金 {format_amount(gold)}</span>',
        f'<span style="color:{_COLOR_DIAM if diamond else _COLOR_MUTED};font-weight:700">'
        f"钻 {format_amount(diamond)}</span>",
    ]
    sep = f'<span style="color:{_COLOR_MUTED}"> · </span>'
    return f'<span style="{_font(13)}">' + sep.join(parts) + "</span>"


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


def format_roll_history_line(
    entry: "RollHistoryEntry",
    *,
    include_time: bool = False,
    compact: bool = False,
) -> str:
    """单条开奖历史。"""
    op = f"#{entry.op_at}"
    if not entry.hit:
        text = f"{op} -" if compact else f"{op}  未中奖"
    elif compact:
        parts = []
        if entry.gold:
            parts.append(f"+{format_amount(entry.gold)}金")
        if entry.diamond:
            parts.append(f"+{format_amount(entry.diamond)}钻")
        text = f"{op} {' '.join(parts)}"
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
    compact: bool = False,
) -> List[str]:
    items = list(entries)
    if limit is not None:
        items = items[:limit]
    if not items:
        return ["暂无开奖记录"]
    return [
        format_roll_history_line(e, include_time=include_time, compact=compact)
        for e in items
    ]
