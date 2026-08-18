"""主悬浮小部件：常驻桌面，显示操作数 / 奖励 / 开奖进度。

目标树区域已拆到 ui_goal_tree_area.GoalTreeArea；本文件负责窗口框架、
顶栏拖动、全局区、右键菜单与开奖 UI。
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QGuiApplication, QMouseEvent, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .models import AppState, Reward
from .op_tracker import OpRateTracker
from .reward_system import roll_progress
from .storage import save_state
from .task_manager import TaskManager
from .ui_goal_tree_area import GoalTreeArea
from .ui_qt import make_section_title, set_label_html, set_label_text
from .ui_roll_bar import SegmentedRollBar
from .ui_text import (
    format_global_summary_html,
    format_roll_history_lines_html,
    format_roll_toast_html,
)
from .ui_widget_qss import WIDGET_STYLESHEET
from .ui_window_drag import DragHandleBar, SystemMoveFilter
from .win_utils import (
    WM_ENTERSIZEMOVE,
    WM_EXITSIZEMOVE,
    is_windows,
    pin_window_to_all_desktops,
    prepare_overlay_hwnd,
    set_startup,
    unpin_window_from_all_desktops,
    win32_message_id,
)

logger = logging.getLogger(__name__)


class FloatingWidget(QWidget):
    """常驻桌面的悬浮小部件。"""

    request_task_dialog = Signal()
    request_inventory_dialog = Signal()
    request_quit = Signal()
    subtask_claimed = Signal(str, object)  # (title, Reward)
    state_changed = Signal()

    def __init__(self, state: AppState, manager: TaskManager):
        super().__init__()
        self.state = state
        self.manager = manager

        self.setWindowTitle("Adventure")
        self.setObjectName("WidgetWindow")
        # 不透明顶层窗：避免 WS_EX_LAYERED 点穿。圆角只是视觉，HWND 仍是矩形。
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#1c1c26"))
        self.setPalette(pal)
        flags = (
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setFixedWidth(308)
        self.setMinimumHeight(600)
        # 高度上限 = 初始高度：任何布局重算都不得把窗口撑过 680
        self.setMaximumHeight(680)
        self.resize(308, 680)

        self._op_tracker = OpRateTracker(window_sec=60.0)
        self._roll_toast_timer: Optional[QTimer] = None
        self._refreshing = False
        self._window_dragging = False
        self._drag_end_timer = QTimer(self)
        self._drag_end_timer.setSingleShot(True)
        self._drag_end_timer.timeout.connect(self.end_user_move)

        self._build_ui()
        # 控件默认是 0/10；立刻用存档进度画一次，否则要等第一次按键才刷新
        self._paint_global_stats()
        self._paint_roll_history()
        self._update_roll_bar()

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
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

        v = QVBoxLayout(root)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)

        # 顶栏（拖动手柄 + 窗口按钮）
        top = QHBoxLayout()
        top.setSpacing(4)
        drag_handle = DragHandleBar(self)
        drag_lay = QHBoxLayout(drag_handle)
        drag_lay.setContentsMargins(0, 0, 0, 0)
        drag_lay.setSpacing(4)
        title = QLabel("Adventure")
        title.setObjectName("Title")
        drag_lay.addWidget(title)
        drag_lay.addStretch(1)
        top.addWidget(drag_handle, 1)
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

        # --- 全局区 ---
        self.global_section = QWidget()
        self.global_section.setObjectName("GlobalSection")
        global_lay = QVBoxLayout(self.global_section)
        global_lay.setContentsMargins(0, 0, 0, 0)
        global_lay.setSpacing(6)
        global_lay.addWidget(make_section_title("全局"))

        self.global_summary = QLabel("")
        self.global_summary.setObjectName("GlobalSummary")
        self.global_summary.setAlignment(Qt.AlignCenter)
        self.global_summary.setTextFormat(Qt.RichText)
        global_lay.addWidget(self.global_summary)

        bar_row = QVBoxLayout()
        bar_row.setSpacing(3)
        cap = QLabel("距下次开奖")
        cap.setObjectName("Subtle")
        self.roll_bar = SegmentedRollBar()
        self.roll_toast = QLabel("")
        self.roll_toast.setObjectName("RollToast")
        self.roll_toast.setTextFormat(Qt.RichText)
        self.roll_toast.hide()
        bar_row.addWidget(cap)
        bar_row.addWidget(self.roll_bar)
        bar_row.addWidget(self.roll_toast)
        global_lay.addLayout(bar_row)

        hist_row = QVBoxLayout()
        hist_row.setSpacing(1)
        hist_cap = QLabel("开奖历史")
        hist_cap.setObjectName("RollHistCap")
        self.roll_history_lbl = QLabel("暂无开奖记录")
        self.roll_history_lbl.setObjectName("RollHist")
        self.roll_history_lbl.setWordWrap(True)
        self.roll_history_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.roll_history_lbl.setTextFormat(Qt.RichText)
        hist_row.addWidget(hist_cap)
        hist_row.addWidget(self.roll_history_lbl)
        global_lay.addLayout(hist_row)

        v.addWidget(self.global_section)
        self._drag_helper = SystemMoveFilter(self, self)
        self._drag_helper.attach(self.global_section)

        divider = QFrame()
        divider.setObjectName("Divider")
        v.addWidget(divider)

        # --- 目标树区域（独立类） ---
        self.goal_tree = GoalTreeArea(self.state, self.manager, parent=root)
        self.goal_tree.subtask_claimed.connect(self.subtask_claimed)
        self.goal_tree.state_changed.connect(self.state_changed)
        v.addWidget(self.goal_tree, 1)

        # 按钮
        btns = QHBoxLayout()
        btns.setSpacing(6)
        self.task_btn = QPushButton("目标管理")
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
        self.roll_bar.pulse_operation()

    # ---------- 右键菜单（拖动见 ui_window_drag）----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.RightButton:
            self._show_context_menu()
            event.accept()
        else:
            super().mousePressEvent(event)

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

        act_sound = QAction("开奖音效", self, checkable=True)
        act_sound.setChecked(bool(s.get("sound_enabled", True)))
        act_sound.toggled.connect(self._toggle_sound)
        menu.addAction(act_sound)

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
        prepare_overlay_hwnd(int(self.winId()))
        save_state(self.state)
        logger.info("窗口置顶: %s", checked)

    def _toggle_pin_all(self, checked: bool) -> None:
        self.state.settings["pin_all_desktops"] = checked
        hwnd = int(self.winId())
        if checked:
            pin_window_to_all_desktops(hwnd)
        else:
            unpin_window_from_all_desktops(hwnd)
        prepare_overlay_hwnd(hwnd)
        save_state(self.state)
        logger.info("固定所有桌面: %s", checked)

    def _toggle_startup(self, checked: bool) -> None:
        self.state.settings["startup"] = checked
        set_startup(checked)
        save_state(self.state)
        logger.info("开机自启: %s", checked)

    def _toggle_sound(self, checked: bool) -> None:
        self.state.settings["sound_enabled"] = checked
        save_state(self.state)
        logger.info("开奖音效: %s", checked)

    def _format_global_summary_html(self, ops_1min: int) -> str:
        s = self.state
        return format_global_summary_html(
            s.total_operations,
            s.inventory.gold,
            s.inventory.diamond,
            ops_1min=ops_1min,
        )

    def _paint_global_stats(self) -> None:
        ops_1min = self._op_tracker.count_recent()
        set_label_html(
            self.global_summary,
            self._format_global_summary_html(ops_1min),
        )

    def _paint_roll_history(self) -> None:
        set_label_html(
            self.roll_history_lbl,
            format_roll_history_lines_html(
                self.state.roll_history, limit=3, compact=True,
            ),
        )

    def _update_roll_bar(self) -> None:
        rt = self.state.roll_runtime
        progress, span = roll_progress(self.state)
        remaining = max(0, span - progress)
        near_full_steps = remaining if 0 < remaining <= 4 else 0
        chance_label = (
            f"金 {rt.gold_chance:.0%}  钻 {rt.diamond_chance:.0%}"
        )
        self.roll_bar.set_cycle(
            progress,
            span,
            rt.segment_colors,
            chance_label=chance_label,
            near_full_steps=near_full_steps,
        )

    def refresh_roll_meta(self) -> None:
        """仅更新进度条概率/颜色元数据（10 分钟重抽后调用）。"""
        self._update_roll_bar()

    def show_roll_result(self, reward: Reward) -> None:
        """开奖结果轻量 Toast + 进度条闪动。"""
        if reward.is_empty():
            self._set_roll_toast("miss", "未中", 1200)
        else:
            dual = reward.gold > 0 and reward.diamond > 0
            if dual and reward.has_crit():
                hide_ms = 2800
            elif dual:
                hide_ms = 2200
            else:
                hide_ms = 2000
            self._set_roll_toast("hit", format_roll_toast_html(reward), hide_ms)
        self._flash_roll_bar()

    def _set_roll_toast(self, kind: str, text: str, hide_ms: int) -> None:
        """更新开奖 Toast；未中走灰色属性，命中用 RichText 分色。"""
        if self.roll_toast.property("toast") != kind:
            self.roll_toast.setProperty("toast", kind)
            self.roll_toast.style().unpolish(self.roll_toast)
            self.roll_toast.style().polish(self.roll_toast)
        self.roll_toast.setTextFormat(
            Qt.PlainText if kind == "miss" else Qt.RichText
        )
        set_label_text(self.roll_toast, text)
        self.roll_toast.show()

        if self._roll_toast_timer is None:
            self._roll_toast_timer = QTimer(self)
            self._roll_toast_timer.setSingleShot(True)
            self._roll_toast_timer.timeout.connect(self.roll_toast.hide)
        self._roll_toast_timer.setInterval(hide_ms)
        self._roll_toast_timer.start()

    def _flash_roll_bar(self) -> None:
        self.roll_bar.set_flash(True)

        def _off() -> None:
            self.roll_bar.set_flash(False)

        QTimer.singleShot(300, _off)
        QTimer.singleShot(600, lambda: self.roll_bar.set_flash(True))
        QTimer.singleShot(900, _off)

    def refresh_stats(self, *, roll_changed: bool = False, reward: Optional[Reward] = None) -> None:
        """按键后的轻量刷新：只改数字，不重建目标树。"""
        self._paint_global_stats()
        self._update_roll_bar()

        if roll_changed:
            self._paint_roll_history()
            if reward is not None:
                self.show_roll_result(reward)

        since = self.state.since_roll
        self.goal_tree.refresh_stats(
            since_gold=since.gold,
            since_diamond=since.diamond,
        )

    # ---------- 刷新 ----------
    def refresh(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._refresh()
        finally:
            self._refreshing = False

    def _refresh(self) -> None:
        self._paint_global_stats()
        self._update_roll_bar()
        self._paint_roll_history()
        since = self.state.since_roll
        self.goal_tree.refresh(
            since_gold=since.gold,
            since_diamond=since.diamond,
        )

    def is_user_moving(self) -> bool:
        return self._window_dragging

    def begin_user_move(self) -> None:
        """交给系统拖动；Windows 上不用 QWidget.move()。"""
        self._window_dragging = True
        self._drag_end_timer.start(2000)
        handle = self.windowHandle()
        if handle is None:
            return
        try:
            handle.startSystemMove()
        except Exception:
            logger.debug("startSystemMove 失败", exc_info=True)

    def end_user_move(self) -> None:
        self._drag_end_timer.stop()
        grabber = QWidget.mouseGrabber()
        if grabber is not None:
            grabber.releaseMouse()
        self._window_dragging = False

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self._window_dragging:
            self._drag_end_timer.start(400)

    def _refresh_runtime(self) -> None:
        """仅刷新与时间相关的字段，避免整窗口频繁重绘。"""
        self.manager.tick_active_time()
        if self.is_user_moving():
            return
        if QGuiApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return
        self._tick_count = getattr(self, "_tick_count", 0) + 1
        if self._tick_count % 60 == 0:
            logger.debug("运行中 (ops=%d)", self.state.total_operations)
        self._paint_global_stats()
        self._update_roll_bar()

        if self.state.active_task() is None:
            return

        since = self.state.since_roll
        self.goal_tree.refresh_stats(
            since_gold=since.gold,
            since_diamond=since.diamond,
        )

    def nativeEvent(self, eventType, message):
        self.manager.power_monitor.handle_native_event(eventType, message)
        msg_id = win32_message_id(eventType, message)
        if msg_id == WM_ENTERSIZEMOVE:
            self._window_dragging = True
            self._drag_end_timer.start(2000)
        elif msg_id == WM_EXITSIZEMOVE:
            self.end_user_move()
        return super().nativeEvent(eventType, message)

    # ---------- 显示时初始化窗口属性 ----------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.manager.power_monitor.install_on(self)
        hwnd = int(self.winId())
        if self.state.settings.get("pin_all_desktops", True):
            pin_window_to_all_desktops(hwnd)
        prepare_overlay_hwnd(hwnd)
