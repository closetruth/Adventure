from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .models import AppState
from .runtime_intervals import (
    DaySlice,
    add_weeks,
    identity_color,
    local_week_start,
    slices_for_week,
)
from .task_manager import TaskManager
from .ui_qt import clear_layout
from .ui_styles import BORDER, FONT_FAMILY, TEXT_MUTED, TEXT_PRIMARY
from .ui_text import format_duration

WEEKDAYS = "一二三四五六日"
GUTTER = 28
HEADER = 22


def format_running_status(state: AppState) -> str:
    active = state.active_task()
    if active is None:
        return "当前没有运行中的目标"
    if active.subtasks:
        leaf = active.current_subtask()
        if leaf is None:
            return "当前没有运行中的目标"
        return f"正在运行  顶层「{active.title}」  ·  「{leaf.title}」"
    return f"正在运行  顶层「{active.title}」"


def format_clock_hours(hours: float) -> str:
    total = int(round(float(hours) * 3600))
    total = max(0, min(24 * 3600, total))
    h, rem = divmod(total, 3600)
    m = rem // 60
    if h >= 24:
        return "24:00"
    return f"{h:02d}:{m:02d}"


def format_slice_hover(sl: DaySlice) -> str:
    t0 = format_clock_hours(sl.t0)
    t1 = format_clock_hours(sl.t1)
    dur = format_duration((sl.t1 - sl.t0) * 3600)
    if sl.leaf_title:
        return f"{sl.title} · {sl.leaf_title}  {t0}–{t1}  （{dur}）"
    return f"{sl.title}  {t0}–{t1}  （{dur}）"


def format_legend_label(title: str, leaf_title: Optional[str], *, running: bool) -> str:
    base = f"{title} · {leaf_title}" if leaf_title else title
    if running:
        return f"{base}  运行中"
    return base


def legend_row_specs(
    slices: list[DaySlice],
    running_identity: Optional[tuple[str, Optional[str]]] = None,
) -> list[tuple[str, str]]:
    """Unique identities in first-seen order: (identity_color hex, legend label)."""
    seen: list[tuple[str, Optional[str]]] = []
    rows: list[tuple[str, str]] = []
    for sl in slices:
        key = sl.identity()
        if key in seen:
            continue
        seen.append(key)
        rows.append(
            (
                identity_color(sl.task_id, sl.leaf_id),
                format_legend_label(
                    sl.title, sl.leaf_title, running=running_identity == key
                ),
            )
        )
    return rows


class WeekGrid(QWidget):
    column_count = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slices: list[DaySlice] = []
        self._week_start = 0.0
        self._now = 0.0
        self._open_identity = None
        self._col_rects: list[QRect] = []
        self.setMouseTracking(True)

    def set_slices(self, slices, *, week_start, now, open_identity):
        self._slices = slices
        self._week_start = week_start
        self._now = now
        self._open_identity = open_identity
        self.update()

    def _body_rect(self) -> QRect:
        return QRect(
            GUTTER,
            HEADER,
            max(1, self.width() - GUTTER),
            max(1, self.height() - HEADER),
        )

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setFont(QFont("Microsoft YaHei UI", 8))
        body = self._body_rect()
        col_w = body.width() / 7.0
        self._col_rects = []
        for i in range(7):
            x = int(body.x() + i * col_w)
            w = int(body.x() + (i + 1) * col_w) - x
            self._col_rects.append(QRect(x, body.y(), w, body.height()))
        p.setPen(QColor(TEXT_MUTED))
        for hour in (0, 6, 12, 18, 24):
            y = body.y() + int(body.height() * (hour / 24.0))
            p.drawText(
                0,
                y - 6,
                GUTTER - 2,
                12,
                int(Qt.AlignRight | Qt.AlignVCenter),
                str(hour),
            )
        mon = datetime.fromtimestamp(self._week_start)
        today = datetime.fromtimestamp(self._now).date()
        for i, rect in enumerate(self._col_rects):
            day = mon + timedelta(days=i)
            p.setPen(QColor(TEXT_PRIMARY))
            p.drawText(
                rect.x(),
                0,
                rect.width(),
                HEADER,
                int(Qt.AlignCenter),
                f"{WEEKDAYS[i]} {day.day:02d}",
            )
            p.setPen(QColor("#2a2d38"))
            p.drawRect(rect.adjusted(0, 0, -1, -1))
        for sl in self._slices:
            idx = (datetime.strptime(sl.date, "%Y-%m-%d").date() - mon.date()).days
            if idx < 0 or idx > 6:
                continue
            rect = self._col_rects[idx]
            y0 = rect.y() + int(rect.height() * (sl.t0 / 24.0))
            y1 = rect.y() + int(rect.height() * (sl.t1 / 24.0))
            block = QRect(rect.x() + 2, y0, rect.width() - 4, max(2, y1 - y0))
            color = QColor(identity_color(sl.task_id, sl.leaf_id))
            p.fillRect(block, color)
            if (
                self._open_identity == sl.identity()
                and datetime.strptime(sl.date, "%Y-%m-%d").date() == today
            ):
                p.setPen(QPen(color.lighter(140), 2))
                p.drawRect(block.adjusted(0, 0, -1, -1))
        now_dt = datetime.fromtimestamp(self._now)
        if mon.date() <= now_dt.date() <= (mon + timedelta(days=6)).date():
            idx = (now_dt.date() - mon.date()).days
            rect = self._col_rects[idx]
            hour = now_dt.hour + now_dt.minute / 60.0 + now_dt.second / 3600.0
            y = rect.y() + int(rect.height() * (hour / 24.0))
            p.setPen(QPen(QColor("#e8eaf0"), 1))
            p.drawLine(rect.left(), y, rect.right(), y)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        mon = datetime.fromtimestamp(self._week_start)
        for sl in self._slices:
            idx = (datetime.strptime(sl.date, "%Y-%m-%d").date() - mon.date()).days
            if idx < 0 or idx > 6 or idx >= len(self._col_rects):
                continue
            rect = self._col_rects[idx]
            y0 = rect.y() + int(rect.height() * (sl.t0 / 24.0))
            y1 = rect.y() + int(rect.height() * (sl.t1 / 24.0))
            block = QRect(rect.x() + 2, y0, rect.width() - 4, max(2, y1 - y0))
            if block.contains(pos):
                QToolTip.showText(
                    event.globalPosition().toPoint(), format_slice_hover(sl), self
                )
                return
        QToolTip.hideText()


class WeekRuntimePanel(QWidget):
    def __init__(self, state: AppState, manager: TaskManager, parent=None):
        super().__init__(parent)
        self.state = state
        self.manager = manager
        self._week_start = local_week_start(time.time())
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("←")
        self.btn_next = QPushButton("→")
        self.lbl_range = QLabel("")
        self.lbl_range.setAlignment(Qt.AlignCenter)
        self.btn_prev.clicked.connect(self._prev_week)
        self.btn_next.clicked.connect(self._next_week)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.lbl_range, 1)
        nav.addWidget(self.btn_next)
        self.lbl_status = QLabel("")
        self.lbl_reset = QLabel("运行记录已重置")
        self.lbl_reset.setStyleSheet(f"color: {TEXT_MUTED};")
        self.lbl_reset.hide()
        self.grid = WeekGrid(self)
        self.grid.setMinimumHeight(280)
        self.grid.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.legend = QWidget(self)
        self.legend_layout = QVBoxLayout(self.legend)
        self.legend_layout.setContentsMargins(0, 4, 0, 0)
        self.legend_layout.setSpacing(4)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(nav)
        lay.addWidget(self.lbl_status)
        lay.addWidget(self.lbl_reset)
        lay.addWidget(self.grid, 1)
        lay.addWidget(self.legend)
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()
        self.refresh()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _prev_week(self) -> None:
        self._week_start = add_weeks(self._week_start, -1)
        self.refresh()

    def _next_week(self) -> None:
        nxt = add_weeks(self._week_start, 1)
        if nxt <= local_week_start(time.time()):
            self._week_start = nxt
            self.refresh()

    def refresh(self) -> None:
        now = time.time()
        current = local_week_start(now)
        self.btn_next.setEnabled(add_weeks(self._week_start, 1) <= current)
        mon = datetime.fromtimestamp(self._week_start)
        sun = mon + timedelta(days=6)
        self.lbl_range.setText(
            f"{mon.strftime('%Y-%m-%d')} ~ {sun.strftime('%Y-%m-%d')}"
        )
        self.lbl_status.setText(format_running_status(self.state))
        self.lbl_reset.setVisible(self.manager.runtime_log.load_reset)
        slices = slices_for_week(self.manager.runtime_log, self._week_start, now)
        ident = None
        rec, task_id, _t, leaf_id, _lt = self.manager.recording_identity()
        if rec and task_id:
            ident = (task_id, leaf_id)
        self.grid.set_slices(
            slices, week_start=self._week_start, now=now, open_identity=ident
        )
        self._fill_legend(legend_row_specs(slices, ident))

    def _fill_legend(self, rows: list[tuple[str, str]]) -> None:
        clear_layout(self.legend_layout)
        for color, text in rows:
            row = QWidget(self.legend)
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(8)
            swatch = QLabel(row)
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(
                f"background-color: {color}; border: 1px solid {BORDER};"
            )
            lbl = QLabel(text, row)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_FAMILY};")
            row_lay.addWidget(swatch, 0, Qt.AlignTop)
            row_lay.addWidget(lbl, 1)
            self.legend_layout.addWidget(row)
