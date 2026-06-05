"""主悬浮小部件：常驻桌面，显示操作数 / 奖励 / 当前任务。"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .active_time import ActiveTimeTracker
from .op_tracker import OpRateTracker
from .models import AppState, Task, TaskStatus
from .storage import save_state
from .task_manager import TaskManager
from .ui_task_stats import TaskRewardStrip
from .ui_text import format_amount, format_duration, format_roll_history_lines
from .win_utils import (
    is_windows,
    pin_window_to_all_desktops,
    set_startup,
    unpin_window_from_all_desktops,
)


WIDGET_STYLESHEET = """
QWidget#WidgetRoot {
    background-color: rgba(28, 28, 38, 235);
    border-radius: 14px;
    border: 1px solid rgba(255,255,255,30);
}
QLabel { color: #f5f5f7; font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; }
QLabel#Title { font-size: 15px; font-weight: 700; }
QLabel#Subtle { color: #b8bcc8; font-size: 12px; }
QLabel#GlobalSummary { color: #7a8090; font-size: 11px; font-weight: 500; }
QLabel#RollHist { color: #aeb4c4; font-size: 11px; font-weight: 500; line-height: 1.35; }
QLabel#TaskTitle { font-size: 14px; font-weight: 700; }
QPushButton {
    background-color: rgba(255,255,255,18);
    color: #f5f5f7;
    border: 1px solid rgba(255,255,255,30);
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
}
QPushButton:hover { background-color: rgba(255,255,255,36); }
QPushButton:pressed { background-color: rgba(255,255,255,12); }
QPushButton#CloseBtn, QPushButton#MinBtn {
    background-color: transparent;
    border: none;
    padding: 0px 6px;
    font-size: 14px;
    color: #c0c4d0;
}
QPushButton#CloseBtn:hover { color: #ff7474; }
QProgressBar {
    background-color: rgba(255,255,255,16);
    border: none;
    border-radius: 7px;
    text-align: center;
    color: #cfd3e0;
    font-size: 10px;
    min-height: 14px;
    max-height: 14px;
}
QProgressBar::chunk {
    background-color: #6c8cff;
    border-radius: 7px;
}
QFrame#Divider { background-color: rgba(255,255,255,18); max-height: 1px; min-height: 1px; }
"""


class FloatingWidget(QWidget):
    """常驻桌面的悬浮小部件。"""

    request_task_dialog = Signal()
    request_inventory_dialog = Signal()
    request_quit = Signal()

    def __init__(self, state: AppState, manager: TaskManager):
        super().__init__()
        self.state = state
        self.manager = manager
        self._drag_offset: Optional[QPoint] = None

        self.setWindowTitle("Adventure")
        self.setObjectName("WidgetWindow")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        flags = (
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setFixedWidth(300)
        self.setMinimumHeight(340)

        self._op_tracker = OpRateTracker(window_sec=60.0)
        self._active_ticker = ActiveTimeTracker()

        self._build_ui()
        self._refresh()

        # 自动刷新 (用于 active 任务的计时显示)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._refresh_runtime)
        self._tick.start()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        self.setStyleSheet(WIDGET_STYLESHEET)
        root = QWidget(self)
        root.setObjectName("WidgetRoot")
        root.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(root)

        v = QVBoxLayout(root)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)

        # 顶栏
        top = QHBoxLayout()
        top.setSpacing(4)
        title = QLabel("Adventure")
        title.setObjectName("Title")
        top.addWidget(title)
        top.addStretch(1)
        self.min_btn = QPushButton("—")
        self.min_btn.setObjectName("MinBtn")
        self.min_btn.setFixedSize(22, 22)
        self.min_btn.setCursor(Qt.PointingHandCursor)
        self.min_btn.clicked.connect(self.showMinimized)
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("CloseBtn")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.request_quit)
        top.addWidget(self.min_btn)
        top.addWidget(self.close_btn)
        v.addLayout(top)

        self.global_summary = QLabel("")
        self.global_summary.setObjectName("GlobalSummary")
        self.global_summary.setAlignment(Qt.AlignCenter)
        v.addWidget(self.global_summary)

        # 开奖进度
        bar_row = QVBoxLayout()
        bar_row.setSpacing(3)
        cap = QLabel("距下次开奖")
        cap.setObjectName("Subtle")
        self.roll_bar = QProgressBar()
        self.roll_bar.setRange(0, 10)
        self.roll_bar.setValue(0)
        self.roll_bar.setTextVisible(True)
        bar_row.addWidget(cap)
        bar_row.addWidget(self.roll_bar)
        v.addLayout(bar_row)

        hist_row = QVBoxLayout()
        hist_row.setSpacing(2)
        hist_cap = QLabel("开奖历史")
        hist_cap.setObjectName("Subtle")
        self.roll_history_lbl = QLabel("暂无开奖记录")
        self.roll_history_lbl.setObjectName("RollHist")
        self.roll_history_lbl.setWordWrap(True)
        self.roll_history_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        hist_row.addWidget(hist_cap)
        hist_row.addWidget(self.roll_history_lbl)
        v.addLayout(hist_row)

        divider = QFrame()
        divider.setObjectName("Divider")
        v.addWidget(divider)

        # 当前任务
        self.task_title = QLabel("暂无进行中的任务")
        self.task_title.setObjectName("TaskTitle")
        self.task_title.setWordWrap(True)
        v.addWidget(self.task_title)
        self.task_stats = TaskRewardStrip()
        v.addWidget(self.task_stats)

        # 按钮
        btns = QHBoxLayout()
        btns.setSpacing(6)
        self.task_btn = QPushButton("任务管理")
        self.task_btn.setCursor(Qt.PointingHandCursor)
        self.task_btn.clicked.connect(self.request_task_dialog)
        self.inv_btn = QPushButton("奖励背包")
        self.inv_btn.setCursor(Qt.PointingHandCursor)
        self.inv_btn.clicked.connect(self.request_inventory_dialog)
        btns.addWidget(self.task_btn)
        btns.addWidget(self.inv_btn)
        v.addLayout(btns)

    def note_operation(self) -> None:
        """记录一次全局操作（用于近1分钟计数）。"""
        self._op_tracker.record()

    # ---------- 拖动 ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.RightButton:
            self._show_context_menu()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    # ---------- 右键菜单 ----------
    def _show_context_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #25262e; color: #f0f0f6; border: 1px solid #404252; }"
            "QMenu::item:selected { background-color: #3a5cff; }"
        )

        s = self.state.settings

        act_top = QAction("窗口置顶", self, checkable=True)
        act_top.setChecked(bool(s.get("always_on_top", True)))
        act_top.toggled.connect(self._toggle_top)
        menu.addAction(act_top)

        act_pin = QAction("固定到所有虚拟桌面", self, checkable=True)
        act_pin.setChecked(bool(s.get("pin_all_desktops", True)))
        act_pin.setEnabled(is_windows())
        act_pin.toggled.connect(self._toggle_pin_all)
        menu.addAction(act_pin)

        menu.addSeparator()

        act_startup = QAction("开机自启", self, checkable=True)
        act_startup.setChecked(bool(s.get("startup", False)))
        act_startup.setEnabled(is_windows())
        act_startup.toggled.connect(self._toggle_startup)
        menu.addAction(act_startup)

        menu.addSeparator()
        act_exit = QAction("退出 Adventure", self)
        act_exit.triggered.connect(self.request_quit)
        menu.addAction(act_exit)

        menu.exec(QCursor.pos())

    def _toggle_top(self, checked: bool) -> None:
        self.state.settings["always_on_top"] = checked
        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        save_state(self.state)

    def _toggle_pin_all(self, checked: bool) -> None:
        self.state.settings["pin_all_desktops"] = checked
        hwnd = int(self.winId())
        if checked:
            pin_window_to_all_desktops(hwnd)
        else:
            unpin_window_from_all_desktops(hwnd)
        save_state(self.state)

    def _toggle_startup(self, checked: bool) -> None:
        self.state.settings["startup"] = checked
        set_startup(checked)
        save_state(self.state)

    # ---------- 刷新 ----------
    def refresh(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        s = self.state
        ops_1min = self._op_tracker.count_recent()
        active = s.active_task()

        if active is None:
            self.global_summary.setText(
                f"近1分钟 {ops_1min} · 总操作 {s.total_operations:,} · "
                f"金币 {format_amount(s.inventory.gold)} · "
                f"钻石 {format_amount(s.inventory.diamond)}"
            )
        else:
            self.global_summary.setText(
                f"总操作 {s.total_operations:,} · 金币 {format_amount(s.inventory.gold)} · "
                f"钻石 {format_amount(s.inventory.diamond)}"
            )

        interval = int(s.settings.get("roll_interval", 10))
        self.roll_bar.setRange(0, interval)
        progress = s.total_operations - s.last_roll_at
        progress = max(0, min(progress, interval))
        self.roll_bar.setValue(progress)
        self.roll_bar.setFormat(f"{progress}/{interval}")

        hist_lines = format_roll_history_lines(s.roll_history, limit=5)
        self.roll_history_lbl.setText("\n".join(hist_lines))

        since = s.since_roll

        if active is None:
            paused = self.manager.by_status(TaskStatus.PAUSED)
            if paused:
                self.task_title.setText("无进行中任务")
                self.task_stats.show_hint(
                    f"已暂停 {len(paused)} 个任务，点击「任务管理」继续"
                )
            else:
                self.task_title.setText("还没有任务")
                self.task_stats.show_hint("点击「任务管理」创建第一个任务")
        else:
            self.task_title.setText(active.title)
            summary = active.pending_summary()
            duration = format_duration(active.active_duration_seconds())
            self.task_stats.show_active(
                active.operations,
                summary.gold,
                summary.diamond,
                ops_1min=ops_1min,
                since_roll_gold=since.gold,
                since_roll_diamond=since.diamond,
                duration=duration,
            )

    def _refresh_runtime(self) -> None:
        """仅刷新与时间相关的字段，避免整窗口频繁重绘。"""
        self._active_ticker.tick(self.state)
        ops_1min = self._op_tracker.count_recent()
        active = self.state.active_task()
        if active is None:
            s = self.state
            self.global_summary.setText(
                f"近1分钟 {ops_1min} · 总操作 {s.total_operations:,} · "
                f"金币 {format_amount(s.inventory.gold)} · "
                f"钻石 {format_amount(s.inventory.diamond)}"
            )
            return

        summary = active.pending_summary()
        duration = format_duration(active.active_duration_seconds())
        since = self.state.since_roll
        self.task_stats.show_active(
            active.operations,
            summary.gold,
            summary.diamond,
            ops_1min=ops_1min,
            since_roll_gold=since.gold,
            since_roll_diamond=since.diamond,
            duration=duration,
        )

    # ---------- 显示时初始化窗口属性 ----------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.state.settings.get("pin_all_desktops", True):
            pin_window_to_all_desktops(int(self.winId()))
