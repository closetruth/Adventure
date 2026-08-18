"""开奖进度条控件。"""
from __future__ import annotations

import random
from typing import List, Tuple

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

# 每段 ease-out 指数：越大越「前冲后磨」。
_EASE_EXPONENT = 2.6
_POINT_P1 = (0.18, 0.32)
_POINT_P2 = (0.52, 0.78)
_POINT_MIN_GAP = 0.22
# 独立于开奖的视觉周期：约 540～708 秒一轮（空闲时接近 10 分钟）。
_EASE_SPAN_MIN = 540
_EASE_SPAN_STEP = 12
_EASE_SPAN_RANGE = 15
_EASE_CYCLES_PER_BLOCK = 15


def _ease_span_for_cycle(cycle_id: int) -> int:
    # 7 与 15 互质，15 轮里 span 走遍 540、552、…、708。
    return _EASE_SPAN_MIN + ((max(0, cycle_id) * 7) % _EASE_SPAN_RANGE) * _EASE_SPAN_STEP


def _ease_block_ops() -> int:
    return sum(_ease_span_for_cycle(i) for i in range(_EASE_CYCLES_PER_BLOCK))


def _independent_cycle(units: int) -> Tuple[int, int, int]:
    """把运行中目标的 units（操作数+秒）映射到独立视觉周期。"""
    total_ops = max(0, int(units))
    block = _ease_block_ops()
    blocks, rem = divmod(total_ops, block)
    cycle_id = blocks * _EASE_CYCLES_PER_BLOCK
    for i in range(_EASE_CYCLES_PER_BLOCK):
        cid = cycle_id + i
        span = _ease_span_for_cycle(cid)
        if rem <= span:
            return rem, span, cid
        rem -= span
    nxt = cycle_id + _EASE_CYCLES_PER_BLOCK
    return 0, _ease_span_for_cycle(nxt), nxt


def _cycle_checkpoints(span: int, cycle_id: int = 0) -> Tuple[float, float, float]:
    """每个视觉周期一组检查点：第一点偏早，第二点拉开，终点固定 1.0。"""
    rng = random.Random(f"ease:{max(1, span)}:{int(cycle_id)}")
    p1 = rng.uniform(*_POINT_P1)
    p2 = rng.uniform(max(_POINT_P2[0], p1 + _POINT_MIN_GAP), _POINT_P2[1])
    return (p1, p2, 1.0)


def _segment_eased(raw: float, points: Tuple[float, float, float], exponent: float) -> float:
    """分段幂函数 ease-out：到每个点前都先快后慢。"""
    if raw <= 0.0:
        return 0.0
    if raw >= 1.0:
        return 1.0
    prev = 0.0
    for pt in points:
        if raw <= pt:
            width = pt - prev
            if width <= 1e-9:
                return pt
            local = (raw - prev) / width
            eased_local = 1.0 - pow(1.0 - local, exponent)
            return prev + eased_local * width
        prev = pt
    return 1.0


class EasedProgressBar(QWidget):
    """非格子的小型平滑进度条：三节点、每段先快后慢。"""

    point_reached = Signal()

    def __init__(self, parent=None, *, exponent: float = _EASE_EXPONENT):
        super().__init__(parent)
        self._progress = 0
        self._span = 10
        self._cycle_id = 0
        self._exponent = max(1.0, exponent)
        self._points = _cycle_checkpoints(self._span, self._cycle_id)
        self._have_baseline = False
        self._flash_on = True
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(400)
        self._flash_timer.timeout.connect(self._toggle_dot_flash)
        self.setMinimumHeight(9)
        self.setMaximumHeight(9)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_progress(self, units: int) -> None:
        """按运行中目标的 units 刷新。周期与开奖间隔互相独立。"""
        progress, span, cycle_id = _independent_cycle(units)
        cycle_changed = span != self._span or cycle_id != self._cycle_id
        if cycle_changed:
            points = _cycle_checkpoints(span, cycle_id)
        else:
            points = self._points
        if (
            self._progress == progress
            and self._span == span
            and self._cycle_id == cycle_id
            and points == self._points
        ):
            return
        old_eased = self._eased_fraction()
        emit_chime = (
            self._have_baseline
            and not cycle_changed
            and self._newly_reached(old_eased, progress, span, points)
        )
        self._progress = progress
        self._span = span
        self._cycle_id = cycle_id
        self._points = points
        self._have_baseline = True
        self._sync_flash_timer()
        self.update()
        if emit_chime:
            self.point_reached.emit()

    def _newly_reached(
        self,
        old_eased: float,
        progress: int,
        span: int,
        points: Tuple[float, float, float],
    ) -> bool:
        raw = progress / max(1, span)
        new_eased = _segment_eased(raw, points, self._exponent)
        return any(
            old_eased + 1e-6 < pt <= new_eased + 1e-6
            for pt in points
        )

    def _raw_fraction(self) -> float:
        return self._progress / max(1, self._span)

    def _eased_fraction(self) -> float:
        return _segment_eased(self._raw_fraction(), self._points, self._exponent)

    def _any_point_reached(self) -> bool:
        eased = self._eased_fraction()
        return any(eased + 1e-6 >= pt for pt in self._points)

    def _sync_flash_timer(self) -> None:
        if self._any_point_reached():
            if not self._flash_timer.isActive():
                self._flash_on = True
                self._flash_timer.start()
        elif self._flash_timer.isActive():
            self._flash_timer.stop()
            self._flash_on = True

    def _toggle_dot_flash(self) -> None:
        self._flash_on = not self._flash_on
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        radius = h / 2
        inset = radius

        track = QRectF(0, 0, w, h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 22))
        painter.drawRoundedRect(track, radius, radius)

        eased = self._eased_fraction()
        fill_w = inset + eased * (w - 2 * inset) + inset if eased > 0 else 0.0
        fill_w = max(0.0, min(w, fill_w))
        if fill_w > 0:
            painter.setBrush(QColor("#7aa2ff"))
            painter.drawRoundedRect(QRectF(0, 0, fill_w, h), radius, radius)

        base_r = max(2.2, h * 0.42)
        for pt in self._points:
            cx = inset + pt * (w - 2 * inset)
            reached = eased + 1e-6 >= pt
            dot_r = base_r
            if reached:
                if self._flash_on:
                    painter.setPen(QPen(QColor("#ffffff"), 1.1))
                    painter.setBrush(QColor("#c5d8ff"))
                    dot_r = base_r + 0.8
                else:
                    painter.setPen(QPen(QColor("#7aa2ff"), 1.0))
                    painter.setBrush(QColor("#7aa2ff"))
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 255, 255, 72))
            painter.drawEllipse(QPointF(cx, h / 2), dot_r, dot_r)

        painter.end()


class SegmentedRollBar(QWidget):
    """每格随机颜色的分段进度条，中央显示进度与当前概率。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0
        self._span = 10
        self._colors: List[str] = []
        self._chance_label = ""
        self._flash = False
        self._near_full_steps = 0
        self._op_flash = False
        self._op_flash_timer = QTimer(self)
        self._op_flash_timer.setSingleShot(True)
        self._op_flash_timer.timeout.connect(self._end_op_flash)
        self.setMinimumHeight(18)
        self.setMaximumHeight(18)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_cycle(
        self,
        progress: int,
        span: int,
        colors: List[str],
        chance_label: str = "",
        near_full_steps: int = 0,
    ) -> None:
        progress = max(0, min(progress, max(1, span)))
        span = max(1, span)
        norm_colors = (
            colors if len(colors) == span else (colors + ["#6c8cff"] * span)[:span]
        )
        changed = (
            self._progress != progress
            or self._span != span
            or self._colors != norm_colors
            or self._chance_label != chance_label
            or self._near_full_steps != near_full_steps
        )
        self._progress = progress
        self._span = span
        self._colors = norm_colors
        self._chance_label = chance_label
        self._near_full_steps = max(0, near_full_steps)
        if changed:
            self.update()

    def set_flash(self, active: bool) -> None:
        if self._flash != active:
            self._flash = active
            self.update()

    def pulse_operation(self) -> None:
        """按键闪光：用定时器收尾，禁止在 paintEvent 里再 update（半透明置顶窗会卡死）。"""
        if not self._op_flash:
            self._op_flash = True
            self.update()
        self._op_flash_timer.start(180)

    def _end_op_flash(self) -> None:
        if self._op_flash:
            self._op_flash = False
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        radius = h / 2
        op_flash = self._op_flash

        bg = QColor(255, 255, 255, 16)
        border = QColor(255, 255, 255, 28)
        if self._near_full_steps > 0:
            strength = 5 - min(4, self._near_full_steps)
            bg = QColor(255, 214, 102, 18 + strength * 6)
            border = QColor(255, 214, 102, 60 + strength * 30)
        if op_flash:
            bg = bg.lighter(120)
            border = border.lighter(120)
        painter.setPen(QPen(border, 1.2 if self._near_full_steps > 0 else 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        span = self._span
        gap = 2
        seg_w = (w - gap * (span - 1)) / span if span > 0 else w

        for i in range(span):
            x = i * (seg_w + gap)
            color_hex = self._colors[i] if i < len(self._colors) else "#6c8cff"
            base = QColor(color_hex)
            filled = i < self._progress
            dist_to_roll = span - i
            if filled:
                c = base
                if self._flash:
                    c = c.lighter(140)
                elif op_flash:
                    c = c.lighter(118)
            else:
                c = QColor(base)
                c.setAlpha(40)
                if (
                    0 < self._near_full_steps <= 4
                    and dist_to_roll <= self._near_full_steps
                ):
                    boost = 18 + (self._near_full_steps - dist_to_roll + 1) * 12
                    c.setAlpha(min(120, c.alpha() + boost))
                    if dist_to_roll == 1:
                        c = c.lighter(138)
                    elif dist_to_roll == 2:
                        c = c.lighter(125)
            painter.setPen(Qt.NoPen)
            painter.setBrush(c)
            painter.drawRoundedRect(QRectF(x, 0, seg_w, h), 3, 3)

        text_color = QColor("#cfd3e0")
        if self._near_full_steps > 0:
            text_color = QColor("#ffe08a")
        painter.setPen(QPen(text_color))
        font = QFont("Microsoft YaHei UI", 8)
        font.setBold(True)
        painter.setFont(font)
        main_text = f"{self._progress}/{self._span}"
        if self._chance_label:
            main_text = f"{main_text}  {self._chance_label}"
        if self._near_full_steps > 0:
            main_text = f"{main_text}  即将开奖"
        painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, main_text)

        painter.end()
