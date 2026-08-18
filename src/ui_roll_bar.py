"""开奖进度条控件。"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class EasedProgressBar(QWidget):
    """非分段的小型平滑进度条，视觉进度先快后慢。"""

    def __init__(self, parent=None, *, exponent: float = 2.2):
        super().__init__(parent)
        self._progress = 0
        self._span = 10
        self._exponent = max(1.0, exponent)
        self.setMinimumHeight(7)
        self.setMaximumHeight(7)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_progress(self, progress: int, span: int) -> None:
        span = max(1, span)
        progress = max(0, min(progress, span))
        if self._progress == progress and self._span == span:
            return
        self._progress = progress
        self._span = span
        self.update()

    def _eased_fraction(self) -> float:
        raw = self._progress / max(1, self._span)
        # 幂函数 ease-out：前段增长更快，尾段更平缓。
        return 1.0 - pow(1.0 - raw, self._exponent)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        radius = h / 2

        track = QRectF(0, 0, w, h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 22))
        painter.drawRoundedRect(track, radius, radius)

        fill_w = max(0.0, min(w, w * self._eased_fraction()))
        if fill_w > 0:
            fill = QRectF(0, 0, fill_w, h)
            painter.setBrush(QColor("#7aa2ff"))
            painter.drawRoundedRect(fill, radius, radius)

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
