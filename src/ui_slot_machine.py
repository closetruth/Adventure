"""开奖老虎机：三轴转轮，逐轴停轮揭晓。"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .models import Reward
from .ui_text import format_amount

_GOLD_POOL: List[str] = [
    "未中", "+0.1", "+0.3", "+0.5", "+0.8", "+1", "+1.2", "+1.5", "+2",
]
_CENTER_POOL: List[str] = [
    "未中", "—", "BAR", "7", "星", "金", "钻", "彩", "双响",
]
_DIAMOND_POOL: List[str] = [
    "未中", "+0.1", "+0.2", "+0.3", "+0.4", "+0.5",
]

# 逐轴停轮时机（tick）；总时长约 5s
_REEL_STOP_TICKS = (16, 28, 42)
_POST_STOP_TICKS = 6
_NEAR_MISS_CHANCE = 0.28


def _gold_label(reward: Reward, *, near_miss: bool) -> str:
    if reward.gold > 0:
        return f"+{format_amount(reward.gold)}"
    if near_miss:
        return random.choice(["+0.8", "+1", "+1.2"])
    return "未中"


def _center_label(reward: Reward, *, near_miss: bool) -> str:
    if reward.gold > 0 and reward.diamond > 0:
        return random.choice(["双响", "彩"])
    if reward.gold > 0:
        return random.choice(["7", "金"])
    if reward.diamond > 0:
        return random.choice(["星", "钻"])
    if near_miss:
        return random.choice(["7", "BAR", "彩"])
    return random.choice(["未中", "—", "BAR"])


def _diamond_label(reward: Reward, *, near_miss: bool) -> str:
    if reward.diamond > 0:
        return f"+{format_amount(reward.diamond)}"
    if near_miss:
        return random.choice(["+0.2", "+0.3"])
    return "未中"


@dataclass
class _Reel:
    title: str
    pool: List[str]
    target: str = "未中"
    idx: int = 0
    locked: bool = False
    accent: QColor = field(default_factory=lambda: QColor("#cfd3e0"))
    kind: str = "neutral"  # gold | center | diamond | neutral


class SlotMachineWidget(QWidget):
    """三轴老虎机：金 - 运 - 钻，从左到右依次停轮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spinning = False
        self._tick = 0
        self._reels: List[_Reel] = []
        self._on_done: Optional[Callable[[], None]] = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

        self.setMinimumHeight(56)
        self.setMaximumHeight(56)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def is_spinning(self) -> bool:
        return self._spinning

    def start_spin(self, reward: Reward, on_finished: Callable[[], None]) -> None:
        if self._spinning:
            return
        near_miss = reward.is_empty() and random.random() < _NEAR_MISS_CHANCE
        self._reels = [
            _Reel("金", _GOLD_POOL, _gold_label(reward, near_miss=near_miss),
                  accent=QColor("#ffd54f"), kind="gold"),
            _Reel("运", _CENTER_POOL, _center_label(reward, near_miss=near_miss),
                  accent=QColor("#c4b5fd"), kind="center"),
            _Reel("钻", _DIAMOND_POOL,
                  _diamond_label(reward, near_miss=near_miss and reward.diamond <= 0),
                  accent=QColor("#7dd3fc"), kind="diamond"),
        ]
        for reel in self._reels:
            reel.idx = random.randrange(len(reel.pool))
            reel.locked = False

        self._on_done = on_finished
        self._spinning = True
        self._tick = 0
        self.show()
        self._timer.start(self._timer_interval_for_tick(0))

    def _timer_interval_for_tick(self, tick: int) -> int:
        """前快后慢，临近停轴再放慢。"""
        if tick < 10:
            return 90
        if tick < 24:
            return 105
        if tick < 40:
            return 125
        return 145

    def _on_tick(self) -> None:
        self._tick += 1
        for i, reel in enumerate(self._reels):
            stop_at = _REEL_STOP_TICKS[i]
            if not reel.locked:
                reel.idx = (reel.idx + 1) % len(reel.pool)
                if self._tick >= stop_at:
                    reel.locked = True
                    reel.idx = self._pool_index(reel.pool, reel.target)

        if (
            all(r.locked for r in self._reels)
            and self._tick >= _REEL_STOP_TICKS[-1] + _POST_STOP_TICKS
        ):
            self._finish()
            return

        self._timer.setInterval(self._timer_interval_for_tick(self._tick))
        self.update()

    @staticmethod
    def _pool_index(pool: List[str], label: str) -> int:
        if label in pool:
            return pool.index(label)
        return 0

    def _finish(self) -> None:
        self._timer.stop()
        self._spinning = False
        self.update()
        cb = self._on_done
        self._on_done = None
        if cb is not None:
            cb()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        gap = 5.0
        reel_w = (w - gap * 2) / 3

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 18))
        painter.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)

        for i, reel in enumerate(self._reels):
            spinning = self._spinning and not reel.locked
            text = reel.pool[reel.idx] if not reel.locked else reel.target
            self._paint_reel(
                painter,
                QRectF(i * (reel_w + gap), 0, reel_w, h),
                reel=reel,
                text=text,
                spinning=spinning,
            )

        painter.end()

    def _paint_reel(
        self,
        painter: QPainter,
        rect: QRectF,
        *,
        reel: _Reel,
        text: str,
        spinning: bool,
    ) -> None:
        inner = rect.adjusted(2, 2, -2, -2)
        bg = QColor(12, 14, 22, 200)
        if reel.locked and text not in ("未中", "—", "BAR"):
            bg = QColor(reel.accent.red(), reel.accent.green(), reel.accent.blue(), 40)
        painter.setBrush(bg)

        border = QColor(255, 255, 255, 50)
        if spinning:
            border = reel.accent
            border.setAlpha(150)
        elif reel.locked:
            border = reel.accent
            border.setAlpha(200 if text not in ("未中", "—", "BAR") else 90)
        painter.setPen(QPen(border, 1.2))
        painter.drawRoundedRect(inner, 7, 7)

        cap_font = QFont("Microsoft YaHei UI", 7)
        cap_font.setBold(True)
        painter.setFont(cap_font)
        painter.setPen(QPen(reel.accent if reel.locked else QColor("#9aa3b5")))
        painter.drawText(
            QRectF(inner.left(), inner.top() + 2, inner.width(), 13),
            Qt.AlignHCenter | Qt.AlignTop,
            reel.title,
        )

        sym_font = QFont("Microsoft YaHei UI", 8)
        sym_font.setBold(True)
        painter.setFont(sym_font)
        sym_color = self._symbol_color(reel, text, spinning)
        painter.setPen(QPen(sym_color))
        painter.drawText(
            QRectF(inner.left(), inner.top() + 14, inner.width(), inner.height() - 16),
            Qt.AlignCenter,
            text,
        )

    def _symbol_color(self, reel: _Reel, text: str, spinning: bool) -> QColor:
        if text in ("未中", "—", "BAR"):
            base = QColor("#8a909e")
        elif reel.kind == "gold" or text == "金":
            base = QColor("#ffd54f")
        elif reel.kind == "diamond" or text == "钻":
            base = QColor("#7dd3fc")
        elif text in ("7", "彩", "双响", "星"):
            base = QColor("#c4b5fd")
        else:
            base = reel.accent
        return base.lighter(115) if spinning else base
