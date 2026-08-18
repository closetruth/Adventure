"""主悬浮小部件：常驻桌面，显示操作数 / 奖励 / 开奖进度。

目标树区域已拆到 ui_goal_tree_area.GoalTreeArea；本文件负责窗口框架、
顶栏拖动、全局区、右键菜单与开奖 UI。
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
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
from .ui_roll_bar import SegmentedRollBar
from .ui_task_tree import GOAL_TREE_PANEL_QSS, TREE_DETAIL_QSS
from .ui_text import (
    format_global_summary_html,
    format_roll_history_lines_html,
    format_roll_toast_html,
)
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


class DragHandleBar(QWidget):
    """顶栏拖动手柄：交给系统拖动，不用 QWidget.move()。"""

    def __init__(self, window: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self.setObjectName("DragHandle")
        self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            begin = getattr(self._window, "begin_user_move", None)
            if callable(begin):
                begin()
            event.accept()
            return
        super().mousePressEvent(event)


class WindowDragHelper(QObject):
    """全局区左键拖动：同样只走系统拖动。"""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window

    def attach(self, root: QWidget) -> None:
        root.installEventFilter(self)
        for child in root.findChildren(QWidget):
            if isinstance(child, (QPushButton,)):
                continue
            child.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            me = event
            if isinstance(me, QMouseEvent) and me.button() == Qt.LeftButton:
                begin = getattr(self._window, "begin_user_move", None)
                if callable(begin):
                    begin()
                return True
        return False


WIDGET_STYLESHEET = """
QWidget#WidgetWindow {
    background-color: #1c1c26;
}
QWidget#WidgetRoot {
    background-color: #1c1c26;
    border-radius: 12px;
    border: 1px solid #3a3f52;
}
QLabel { color: #f5f5f7; font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; }
QWidget#DragHandle { background: transparent; }
QLabel#Title { font-size: 15px; font-weight: 700; background: transparent; }
QLabel#Subtle { color: #d0d4e0; font-size: 12px; }
QLabel#SectionTitle {
    font-size: 12px; font-weight: 700; color: #b8c0d4;
    padding-bottom: 2px;
}
QLabel#GlobalSummary { font-size: 11px; font-weight: 500; }
QLabel#RollHistCap { color: #a8b0c4; font-size: 10px; }
QLabel#RollHist { color: #b8c0d4; font-size: 9px; line-height: 1.25; }
QLabel#TaskTitle { font-size: 14px; font-weight: 700; color: #ffffff; }
QWidget#SubGoalRow {
    background-color: #1a1b24;
    border-radius: 6px;
    border: 1px solid #2a2d38;
}
QWidget#SubGoalRow[nested="true"] {
    border-left: 3px solid #3a4a68;
    background-color: #181a22;
}
QWidget#SubGoalRow[current="true"] {
    background-color: #152038;
    border: 1px solid #3a5080;
}
QWidget#SubGoalRow[claimable="true"] {
    background-color: #241e14;
    border: 1px solid #6a5020;
}
QWidget#SubGoalPinned {
    background-color: #152038;
    border-radius: 6px;
    border: 1px solid #3a5080;
}
QPushButton#SubClaimBtn {
    background-color: #3a5cff;
    border-color: #3a5cff;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 10px;
    min-height: 22px;
}
QPushButton#SubClaimBtn:hover { background-color: #4d6dff; }
QPushButton#GoalAddBtn {
    font-size: 12px;
    padding: 4px 10px;
    background-color: #252833;
    border: 1px solid #404558;
    color: #b8c8e8;
}
QPushButton#GoalAddBtn:hover {
    background-color: #303448;
}
QPushButton#SubActionBtn {
    background-color: #252833;
    border: 1px solid #404558;
    color: #a8c4ff;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 8px;
    min-height: 20px;
    border-radius: 5px;
}
QPushButton#SubActionBtn:hover { background-color: #303448; border-color: #5a6a90; }
QPushButton#SubFoldBtn {
    background-color: #252833;
    border: 1px solid #404558;
    color: #c8ceda;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 6px;
    min-width: 20px;
    min-height: 20px;
    border-radius: 5px;
}
QPushButton#SubFoldBtn:hover { background-color: #303448; border-color: #5a6a90; }
QPushButton#SubDelBtn {
    font-size: 11px;
    padding: 3px 8px;
    min-height: 20px;
    border-radius: 5px;
    color: #a87070;
    background-color: #252833;
    border: 1px solid #503838;
}
QPushButton#SubDelBtn:hover {
    color: #d09090;
    background-color: #302525;
    border-color: #704040;
}
QPushButton#Primary {
    background-color: #3a5cff;
    border: 1px solid #3a5cff;
    color: #ffffff;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
    min-height: 22px;
    border-radius: 5px;
}
QPushButton#Primary:hover { background-color: #4d6dff; border-color: #4d6dff; }
QPushButton#Ghost {
    background-color: transparent;
    color: #b8bfd0;
    border: 1px solid #404558;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
    min-height: 22px;
    border-radius: 5px;
}
QPushButton#Ghost:hover { background-color: #252833; color: #e8eaf0; }
QPushButton#Danger {
    color: #d09090;
    border: 1px solid #503838;
    background: #2a2222;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
    min-height: 22px;
    border-radius: 5px;
}
QPushButton#Danger:hover {
    background-color: #3a2828;
    border-color: #704040;
    color: #ffb0b0;
}
QScrollArea#SubGoalScroll { background-color: #1c1c26; border: none; }
QWidget#SubGoalViewport { background-color: #1c1c26; }
QWidget#SubGoalContainer { background-color: #1c1c26; }
QScrollBar#SubGoalHBar:horizontal {
    height: 10px;
    background-color: #1c1c26;
    border: none;
    margin: 4px 4px 0 4px;
}
QScrollBar#SubGoalHBar::groove:horizontal {
    background-color: #1c1c26;
    border: none;
    height: 10px;
    border-radius: 5px;
}
QScrollBar#SubGoalHBar::sub-page:horizontal,
QScrollBar#SubGoalHBar::add-page:horizontal {
    background-color: #1c1c26;
    border: none;
}
QScrollBar#SubGoalHBar::handle:horizontal {
    background-color: #e8e8e8;
    min-width: 64px;
    border-radius: 5px;
    margin: 0;
    border: none;
}
QScrollBar#SubGoalHBar::handle:horizontal:hover {
    background-color: #ffffff;
}
QScrollBar#SubGoalHBar::handle:horizontal:disabled {
    background-color: #5a5a62;
}
QScrollBar#SubGoalHBar::add-line:horizontal,
QScrollBar#SubGoalHBar::sub-line:horizontal {
    width: 0;
    height: 0;
    border: none;
    background: none;
}
QScrollArea#SubGoalScroll QScrollBar:vertical {
    width: 10px;
    background-color: #1c1c26;
    border: none;
    margin: 2px 2px 2px 0;
}
QScrollArea#SubGoalScroll QScrollBar::groove:vertical {
    background-color: #1c1c26;
    border: none;
    width: 10px;
    border-radius: 5px;
}
QScrollArea#SubGoalScroll QScrollBar::sub-page:vertical,
QScrollArea#SubGoalScroll QScrollBar::add-page:vertical {
    background-color: #1c1c26;
    border: none;
}
QScrollArea#SubGoalScroll QScrollBar::handle:vertical {
    background-color: #e8e8e8;
    min-height: 40px;
    border-radius: 5px;
    margin: 0;
    border: none;
}
QScrollArea#SubGoalScroll QScrollBar::handle:vertical:hover {
    background-color: #ffffff;
}
QScrollArea#SubGoalScroll QScrollBar::handle:vertical:disabled {
    background-color: #5a5a62;
}
QScrollArea#SubGoalScroll QScrollBar::add-line:vertical,
QScrollArea#SubGoalScroll QScrollBar::sub-line:vertical {
    width: 0;
    height: 0;
    border: none;
    background: none;
}
QWidget#SubGoalActions { background: transparent; }
QPushButton {
    background-color: #2a2d3a;
    color: #f5f5f7;
    border: 1px solid #404558;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
}
QPushButton:hover { background-color: #343848; }
QPushButton:pressed { background-color: #222530; }
QPushButton#CloseBtn, QPushButton#MinBtn {
    background-color: transparent;
    border: none;
    padding: 0px 6px;
    font-size: 14px;
    color: #c0c4d0;
}
QPushButton#CloseBtn:hover { color: #ff7474; }
QLabel#RollToast {
    font-size: 12px;
    font-weight: 700;
    padding: 2px 0;
    background: transparent;
}
QLabel#RollToast[toast="miss"] { color: #8a909e; }
QFrame#Divider { background-color: #2a2d38; max-height: 1px; min-height: 1px; }
""" + TREE_DETAIL_QSS + GOAL_TREE_PANEL_QSS


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
        global_lay.addWidget(self._make_section_title("全局"))

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
        self._drag_helper = WindowDragHelper(self)
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

    @staticmethod
    def _make_section_title(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SectionTitle")
        return lbl

    # ---------- 右键菜单（拖动见 DragHandleBar / WindowDragHelper）----------
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

    def _set_text(self, label: QLabel, text: str) -> None:
        if label.text() != text:
            label.setText(text)

    def _set_html(self, label: QLabel, html: str) -> None:
        if label.text() != html:
            label.setText(html)

    def _format_global_summary_html(self, ops_1min: int) -> str:
        s = self.state
        return format_global_summary_html(
            s.total_operations,
            s.inventory.gold,
            s.inventory.diamond,
            ops_1min=ops_1min,
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
        self._set_text(self.roll_toast, text)
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

    def refresh_light(self, *, roll_changed: bool = False, reward: Optional[Reward] = None) -> None:
        """按键后的轻量刷新：跳过未变化字段，开奖历史仅在开奖时更新。"""
        s = self.state
        ops_1min = self._op_tracker.count_recent()

        self._set_html(
            self.global_summary,
            self._format_global_summary_html(ops_1min),
        )

        self._update_roll_bar()

        if roll_changed:
            self._set_html(
                self.roll_history_lbl,
                format_roll_history_lines_html(
                    s.roll_history, limit=3, compact=True,
                ),
            )
            if reward is not None:
                self.show_roll_result(reward)

        self.goal_tree.refresh_stats(
            since_gold=s.since_roll.gold,
            since_diamond=s.since_roll.diamond,
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
        s = self.state
        ops_1min = self._op_tracker.count_recent()

        self._set_html(
            self.global_summary,
            self._format_global_summary_html(ops_1min),
        )

        self._update_roll_bar()

        self._set_html(
            self.roll_history_lbl,
            format_roll_history_lines_html(
                s.roll_history, limit=3, compact=True,
            ),
        )

        self.goal_tree.refresh(
            since_gold=s.since_roll.gold,
            since_diamond=s.since_roll.diamond,
        )

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
        if self._window_dragging:
            return
        if QGuiApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return
        self._tick_count = getattr(self, '_tick_count', 0) + 1
        if self._tick_count % 60 == 0:
            logger.debug("运行中 (ops=%d)", self.state.total_operations)
        ops_1min = self._op_tracker.count_recent()

        self._set_html(
            self.global_summary,
            self._format_global_summary_html(ops_1min),
        )

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
