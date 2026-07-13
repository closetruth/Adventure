"""彩色分段开奖进度条。"""
from __future__ import annotations

from typing import List, Optional

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
        self.setMinimumHeight(18)
        self.setMaximumHeight(18)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_cycle(
        self,
        progress: int,
        span: int,
        colors: List[str],
        chance_label: str = "",
    ) -> None:
        progress = max(0, min(progress, max(1, span)))
        span = max(1, span)
        norm_colors = colors if len(colors) == span else (colors + ["#6c8cff"] * span)[:span]
        changed = (
            self._progress != progress
            or self._span != span
            or self._colors != norm_colors
            or self._chance_label != chance_label
        )
        self._progress = progress
        self._span = span
        self._colors = norm_colors
        self._chance_label = chance_label
        if changed:
            self.update()

    def set_flash(self, active: bool) -> None:
        if self._flash != active:
            self._flash = active
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        radius = h / 2

        # 背景槽
        bg = QColor(255, 255, 255, 16)
        painter.setPen(Qt.NoPen)
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
            if filled:
                c = base
                if self._flash:
                    c = c.lighter(140)
            else:
                c = QColor(base)
                c.setAlpha(40)
            painter.setBrush(c)
            painter.drawRoundedRect(QRectF(x, 0, seg_w, h), 3, 3)

        # 中央文字
        painter.setPen(QPen(QColor("#cfd3e0")))
        font = QFont("Microsoft YaHei UI", 8)
        font.setBold(True)
        painter.setFont(font)
        main_text = f"{self._progress}/{self._span}"
        if self._chance_label:
            main_text = f"{main_text}  {self._chance_label}"
        painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, main_text)

        painter.end()
