"""彩色分段开奖进度条。"""
from __future__ import annotations

import time
from typing import List

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


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
        self._op_flash_until = 0.0
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
        self._op_flash_until = time.monotonic() + 0.18
        self.update()

    def _op_flash_active(self) -> bool:
        active = time.monotonic() < self._op_flash_until
        if not active and self._op_flash_until:
            self._op_flash_until = 0.0
        return active

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        radius = h / 2
        op_flash = self._op_flash_active()

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
        if op_flash:
            self.update()
