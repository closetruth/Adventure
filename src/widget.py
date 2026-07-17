"""主悬浮小部件：常驻桌面，显示操作数 / 奖励 / 当前目标。"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .op_tracker import OpRateTracker
from .models import AppState, Reward, Subtask, Task, TaskStatus
from .reward_system import roll_progress
from .storage import save_state
from .task_manager import TaskManager
from .ui_roll_bar import SegmentedRollBar
from .ui_task_stats import TaskRewardStrip
from .ui_text import (
    format_amount,
    format_duration,
    format_global_summary_html,
    format_roll_history_lines_html,
    format_subgoal_line_html,
    format_subgoals_focus_hint_html,
)
from .win_utils import (
    is_windows,
    pin_window_to_all_desktops,
    set_startup,
    unpin_window_from_all_desktops,
)

logger = logging.getLogger(__name__)


WIDGET_STYLESHEET = """
QWidget#WidgetRoot {
    background-color: rgba(28, 28, 38, 235);
    border-radius: 14px;
    border: 1px solid rgba(255,255,255,30);
}
QLabel { color: #f5f5f7; font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; }
QLabel#Title { font-size: 15px; font-weight: 700; }
QLabel#Subtle { color: #b8bcc8; font-size: 12px; }
QLabel#SectionTitle {
    font-size: 12px; font-weight: 700; color: #8b93a8;
    padding-bottom: 2px;
}
QLabel#GlobalSummary { color: #7a8090; font-size: 11px; font-weight: 500; }
QLabel#RollHistCap { color: #7a8090; font-size: 10px; }
QLabel#RollHist { color: #8b90a8; font-size: 9px; line-height: 1.25; }
QLabel#TaskTitle { font-size: 14px; font-weight: 700; }
QLabel#SubGoalList { color: #c8ceda; font-size: 13px; font-weight: 500; line-height: 1.35; background: transparent; }
QWidget#SubGoalRow {
    background-color: #1a1b24;
    border-radius: 6px;
    border: 1px solid #2a2d38;
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
QLineEdit#SubGoalInput {
    background-color: #1a1b24;
    color: #d8dce8;
    border: 1px solid #3a3d4a;
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 12px;
}
QSpinBox#SubtaskMinSpin {
    background-color: #1a1b24;
    color: #d8dce8;
    border: 1px solid #3a3d4a;
    border-radius: 6px;
    padding: 3px 4px;
    font-size: 11px;
    min-height: 22px;
}
QSpinBox#SubtaskMinSpin:focus { border-color: #4a6ad0; }
QPushButton#SubClaimBtn {
    background-color: #3a5cff;
    border-color: #3a5cff;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 10px;
    min-height: 22px;
}
QPushButton#SubClaimBtn:hover { background-color: #4d6dff; }
QPushButton#SubAddBtn, QPushButton#GoalAddBtn {
    font-size: 12px;
    padding: 4px 10px;
    background-color: #252833;
    border: 1px solid #404558;
    color: #b8c8e8;
}
QPushButton#SubAddBtn:hover, QPushButton#GoalAddBtn:hover {
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
QPushButton#GoalPauseBtn, QPushButton#GoalResumeBtn {
    background-color: #252833;
    border: 1px solid #404558;
    color: #a8c4ff;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
    min-height: 22px;
    border-radius: 5px;
}
QPushButton#GoalPauseBtn:hover, QPushButton#GoalResumeBtn:hover {
    background-color: #303448;
    border-color: #5a6a90;
}
QSlider#GoalBrowseSlider {
    height: 22px;
    margin: 0px 2px;
}
QSlider#GoalBrowseSlider::groove:horizontal {
    height: 4px;
    background: #2a2d38;
    border-radius: 2px;
}
QSlider#GoalBrowseSlider::sub-page:horizontal {
    background: #3a5cff;
    border-radius: 2px;
}
QSlider#GoalBrowseSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    margin: -5px 0;
    background: #c8d0e8;
    border: 1px solid #6a7aa0;
    border-radius: 7px;
}
QSlider#GoalBrowseSlider::handle:horizontal:hover {
    background: #e0e6f8;
    border-color: #8a9ac0;
}
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
QScrollArea#SubGoalScroll { background: transparent; border: none; }
QScrollArea#SubGoalScroll QWidget#SubGoalContainer { background: transparent; }
QWidget#SubGoalActions { background: transparent; }
QLabel#SubGoalHint { color: #e6a830; font-size: 12px; font-weight: 600; background: transparent; }
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
QLabel#RollToast {
    font-size: 12px;
    font-weight: 700;
    padding: 2px 0;
    background: transparent;
}
QLabel#RollToastGold { color: #ffd54f; }
QLabel#RollToastDiam { color: #7dd3fc; }
QLabel#RollToastMiss { color: #8a909e; }
QFrame#Divider { background-color: rgba(255,255,255,18); max-height: 1px; min-height: 1px; }
"""


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
        self.setFixedWidth(308)
        self.setMinimumHeight(460)

        self._op_tracker = OpRateTracker(window_sec=60.0)
        self._browse_index: int = 0
        self._subgoal_structure_sig: tuple | None = None
        self._subgoal_line_labels: dict[str, QLabel] = {}
        self._subgoal_pinned_line: QLabel | None = None
        self._roll_toast_timer: Optional[QTimer] = None

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

        divider = QFrame()
        divider.setObjectName("Divider")
        v.addWidget(divider)

        # --- 目标区 ---
        self.goal_section = QWidget()
        self.goal_section.setObjectName("GoalSection")
        goal_lay = QVBoxLayout(self.goal_section)
        goal_lay.setContentsMargins(0, 0, 0, 0)
        goal_lay.setSpacing(6)
        goal_lay.addWidget(self._make_section_title("当前目标"))

        goal_head = QHBoxLayout()
        goal_head.setSpacing(6)
        self.task_title = QLabel("暂无进行中的目标")
        self.task_title.setObjectName("TaskTitle")
        self.task_title.setWordWrap(True)
        goal_head.addWidget(self.task_title, 1)
        self.goal_pause_btn = QPushButton("暂停")
        self.goal_pause_btn.setObjectName("GoalPauseBtn")
        self.goal_pause_btn.setCursor(Qt.PointingHandCursor)
        self.goal_pause_btn.clicked.connect(self._on_goal_pause)
        self.goal_pause_btn.hide()
        goal_head.addWidget(self.goal_pause_btn)
        self.goal_resume_btn = QPushButton("恢复")
        self.goal_resume_btn.setObjectName("GoalResumeBtn")
        self.goal_resume_btn.setCursor(Qt.PointingHandCursor)
        self.goal_resume_btn.clicked.connect(self._on_goal_resume)
        self.goal_resume_btn.hide()
        goal_head.addWidget(self.goal_resume_btn)
        goal_lay.addLayout(goal_head)

        self.goal_browse_slider = QSlider(Qt.Orientation.Horizontal)
        self.goal_browse_slider.setObjectName("GoalBrowseSlider")
        self.goal_browse_slider.setMinimum(0)
        self.goal_browse_slider.setMaximum(0)
        self.goal_browse_slider.setSingleStep(1)
        self.goal_browse_slider.setPageStep(1)
        self.goal_browse_slider.setCursor(Qt.PointingHandCursor)
        self.goal_browse_slider.valueChanged.connect(self._on_goal_browse_changed)
        self.goal_browse_slider.hide()
        goal_lay.addWidget(self.goal_browse_slider)

        self.task_stats = TaskRewardStrip()
        goal_lay.addWidget(self.task_stats)

        self.goal_add_btn = QPushButton("新建目标")
        self.goal_add_btn.setObjectName("GoalAddBtn")
        self.goal_add_btn.setCursor(Qt.PointingHandCursor)
        self.goal_add_btn.clicked.connect(self._on_add_goal)
        goal_lay.addWidget(self.goal_add_btn)
        v.addWidget(self.goal_section)

        divider2 = QFrame()
        divider2.setObjectName("Divider")
        v.addWidget(divider2)

        # --- 子目标区 ---
        self.subgoal_section = QWidget()
        self.subgoal_section.setObjectName("SubGoalSection")
        sub_lay = QVBoxLayout(self.subgoal_section)
        sub_lay.setContentsMargins(0, 0, 0, 0)
        sub_lay.setSpacing(6)
        sub_lay.addWidget(self._make_section_title("子目标"))

        self.subgoals_hint = QLabel("")
        self.subgoals_hint.setObjectName("SubGoalHint")
        self.subgoals_hint.setWordWrap(True)
        self.subgoals_hint.hide()
        sub_lay.addWidget(self.subgoals_hint)

        self.subgoal_pinned = QWidget()
        self.subgoal_pinned.setObjectName("SubGoalPinnedHost")
        self.subgoal_pinned_layout = QVBoxLayout(self.subgoal_pinned)
        self.subgoal_pinned_layout.setContentsMargins(0, 0, 0, 0)
        self.subgoal_pinned_layout.setSpacing(0)
        self.subgoal_pinned.hide()
        sub_lay.addWidget(self.subgoal_pinned)

        self.subgoals_scroll = QScrollArea()
        self.subgoals_scroll.setObjectName("SubGoalScroll")
        self.subgoals_scroll.setFrameShape(QFrame.NoFrame)
        self.subgoals_scroll.setWidgetResizable(True)
        self.subgoals_scroll.setMaximumHeight(140)
        self.subgoals_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.subgoals_container = QWidget()
        self.subgoals_container.setObjectName("SubGoalContainer")
        self.subgoals_container.setAutoFillBackground(False)
        self.subgoals_scroll.viewport().setAutoFillBackground(False)
        self.subgoals_layout = QVBoxLayout(self.subgoals_container)
        self.subgoals_layout.setContentsMargins(0, 0, 0, 0)
        self.subgoals_layout.setSpacing(8)
        self.subgoals_scroll.setWidget(self.subgoals_container)
        sub_lay.addWidget(self.subgoals_scroll)

        self.subgoals_empty = QLabel("添加子目标后开始累计奖励")
        self.subgoals_empty.setObjectName("SubGoalList")
        self.subgoals_empty.setWordWrap(True)
        sub_lay.addWidget(self.subgoals_empty)

        self.subgoal_actions = QWidget()
        self.subgoal_actions.setObjectName("SubGoalActions")
        actions_layout = QVBoxLayout(self.subgoal_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(4)

        add_sub_row = QHBoxLayout()
        add_sub_row.setSpacing(4)
        self.subgoal_input = QLineEdit()
        self.subgoal_input.setObjectName("SubGoalInput")
        self.subgoal_input.setPlaceholderText("添加子目标…")
        self.subgoal_input.returnPressed.connect(self._on_add_subgoal)
        add_sub_row.addWidget(self.subgoal_input, 1)
        default_min = max(
            1, int(self.state.settings.get("subtask_default_target_minutes", 10)),
        )
        self.subgoal_min_spin = QSpinBox()
        self.subgoal_min_spin.setObjectName("SubtaskMinSpin")
        self.subgoal_min_spin.setRange(1, 999)
        self.subgoal_min_spin.setValue(default_min)
        self.subgoal_min_spin.setPrefix("最少 ")
        self.subgoal_min_spin.setSuffix(" 分")
        self.subgoal_min_spin.setToolTip("新子目标需运行的最短时间（完成后可领取）")
        self.subgoal_min_spin.setFixedWidth(96)
        self.subgoal_min_spin.valueChanged.connect(self._on_subtask_min_changed)
        add_sub_row.addWidget(self.subgoal_min_spin)
        self.sub_add_btn = QPushButton("添加")
        self.sub_add_btn.setObjectName("SubAddBtn")
        self.sub_add_btn.setCursor(Qt.PointingHandCursor)
        self.sub_add_btn.clicked.connect(self._on_add_subgoal)
        add_sub_row.addWidget(self.sub_add_btn)
        self.add_sub_row = QWidget()
        self.add_sub_row.setLayout(add_sub_row)
        actions_layout.addWidget(self.add_sub_row)

        sub_lay.addWidget(self.subgoal_actions)
        v.addWidget(self.subgoal_section)

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

    @staticmethod
    def _make_section_title(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SectionTitle")
        return lbl

    # ---------- 拖动 ----------
    def _is_interactive_child(self, pos: QPoint) -> bool:
        w = self.childAt(pos)
        while w is not None and w is not self:
            if isinstance(w, (QPushButton, QLineEdit, QScrollArea, QSpinBox, QSlider)):
                return True
            w = w.parentWidget()
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            if self._is_interactive_child(event.position().toPoint()):
                super().mousePressEvent(event)
                return
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
        save_state(self.state)
        logger.info("窗口置顶: %s", checked)

    def _toggle_pin_all(self, checked: bool) -> None:
        self.state.settings["pin_all_desktops"] = checked
        hwnd = int(self.winId())
        if checked:
            pin_window_to_all_desktops(hwnd)
        else:
            unpin_window_from_all_desktops(hwnd)
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

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _format_task_title(self, active: Task) -> str:
        if not active.subtasks:
            return active.title
        done, total = active.subtask_progress()
        return f"{active.title}  ({done}/{total})"

    def _make_sub_action_btn(self, text: str, *, primary: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("SubClaimBtn" if primary else "SubActionBtn")
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _clear_subgoal_pinned(self) -> None:
        self._clear_layout(self.subgoal_pinned_layout)
        self._subgoal_pinned_line = None
        self.subgoal_pinned.hide()

    def _make_subgoal_row(
        self,
        active: Task,
        sub: Subtask,
        *,
        is_current: bool,
        pinned: bool = False,
    ) -> tuple[QWidget, QLabel]:
        row = QWidget()
        row.setObjectName("SubGoalPinned" if pinned else "SubGoalRow")
        if not pinned:
            if sub.is_claimable():
                row.setProperty("claimable", True)
            elif is_current and not sub.done:
                row.setProperty("current", True)
        row_lay = QVBoxLayout(row)
        row_lay.setContentsMargins(8, 5, 8, 5)
        row_lay.setSpacing(4)

        line = QLabel(format_subgoal_line_html(sub, is_current=is_current))
        line.setObjectName("SubGoalList")
        line.setWordWrap(True)
        line.setTextFormat(Qt.RichText)
        row_lay.addWidget(line)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(3)
        task_id = active.id

        if sub.is_claimable():
            btn_claim = self._make_sub_action_btn("领取", primary=True)
            btn_claim.clicked.connect(
                lambda _c=False, sid=sub.id: self._on_sub_claim(sid)
            )
            btn_row.addWidget(btn_claim)
        elif sub.done and sub.rewards_claimed:
            pass
        elif is_current:
            btn_pause = self._make_sub_action_btn("暂停")
            btn_pause.clicked.connect(
                lambda _c=False, tid=task_id: self._on_sub_pause(tid)
            )
            btn_row.addWidget(btn_pause)
            if sub.time_target_met():
                btn_done = self._make_sub_action_btn("完成")
                btn_done.clicked.connect(
                    lambda _c=False, sid=sub.id: self._on_sub_complete(sid)
                )
                btn_row.addWidget(btn_done)
        else:
            btn_start = self._make_sub_action_btn("开始")
            btn_start.clicked.connect(
                lambda _c=False, sid=sub.id: self._on_sub_focus(sid)
            )
            btn_row.addWidget(btn_start)

        if not (sub.done and sub.rewards_claimed):
            btn_del = QPushButton("删")
            btn_del.setObjectName("SubDelBtn")
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.clicked.connect(
                lambda _c=False, sid=sub.id: self._on_sub_delete(sid)
            )
            btn_row.addWidget(btn_del)

        btn_row.addStretch(1)
        row_lay.addLayout(btn_row)
        row.style().unpolish(row)
        row.style().polish(row)
        return row, line

    def _subgoal_structure_signature(self, active: Task) -> tuple:
        current_id = active.current_subtask_id
        return tuple(
            (
                s.id,
                s.done,
                s.rewards_claimed,
                s.is_claimable(),
                s.id == current_id,
                (not s.done and s.id == current_id and s.time_target_met()),
            )
            for s in active.subtasks
        )

    def _refresh_subgoal_section(self, active: Task | None) -> None:
        if (
            active is None
            or active.status != TaskStatus.ACTIVE
            or not active.subtasks
        ):
            self._rebuild_subgoal_rows(active)
            return
        sig = self._subgoal_structure_signature(active)
        if sig != self._subgoal_structure_sig:
            self._rebuild_subgoal_rows(active)
        else:
            self._update_subgoal_lines(active)

    def _update_subgoal_lines(self, active: Task) -> None:
        hint = format_subgoals_focus_hint_html(active)
        if hint:
            self.subgoals_hint.setTextFormat(Qt.RichText)
            self._set_html(self.subgoals_hint, hint)
            self.subgoals_hint.show()
        else:
            self.subgoals_hint.hide()

        current = active.current_subtask()
        current_id = current.id if current is not None else None
        if self._subgoal_pinned_line is not None and current is not None:
            self._set_html(
                self._subgoal_pinned_line,
                format_subgoal_line_html(current, is_current=True),
            )
        for sub in active.subtasks:
            if sub.id == current_id and current is not None:
                continue
            line = self._subgoal_line_labels.get(sub.id)
            if line is None:
                continue
            self._set_html(
                line,
                format_subgoal_line_html(sub, is_current=False),
            )

    def _rebuild_subgoal_rows(self, active: Task | None) -> None:
        self._clear_layout(self.subgoals_layout)
        self._clear_subgoal_pinned()
        self._subgoal_line_labels.clear()
        self._subgoal_structure_sig = None

        if active is None or active.status != TaskStatus.ACTIVE:
            self.subgoals_scroll.hide()
            self.subgoals_hint.hide()
            self.subgoals_empty.hide()
            if active is not None and not active.subtasks:
                self.subgoals_empty.setText("添加子目标后开始累计奖励")
                self.subgoals_empty.show()
            return

        if not active.subtasks:
            self.subgoals_scroll.hide()
            self.subgoals_hint.hide()
            self.subgoals_empty.show()
            self.subgoals_empty.setText("添加子目标后开始累计奖励")
            return

        self.subgoals_empty.hide()
        self.subgoals_scroll.show()

        hint = format_subgoals_focus_hint_html(active)
        if hint:
            self.subgoals_hint.setTextFormat(Qt.RichText)
            self._set_html(self.subgoals_hint, hint)
            self.subgoals_hint.show()
        else:
            self.subgoals_hint.hide()

        current = active.current_subtask()
        current_id = current.id if current is not None else None

        if current is not None:
            row, line = self._make_subgoal_row(
                active, current, is_current=True, pinned=True,
            )
            self.subgoal_pinned_layout.addWidget(row)
            self._subgoal_pinned_line = line
            self._subgoal_line_labels[current.id] = line
            self.subgoal_pinned.show()

        scroll_subs = [
            s for s in active.subtasks
            if current_id is None or s.id != current_id
        ]
        for sub in scroll_subs:
            is_current = False
            row, line = self._make_subgoal_row(
                active, sub, is_current=is_current, pinned=False,
            )
            self._subgoal_line_labels[sub.id] = line
            self.subgoals_layout.addWidget(row)

        self.subgoals_layout.addStretch(1)
        self._subgoal_structure_sig = self._subgoal_structure_signature(active)

    def _confirm_subgoal_delete(self, sub: Subtask, *, has_rewards: bool) -> bool:
        if has_rewards:
            text = f"「{sub.title}」有未领取奖励，确定删除吗？"
        else:
            text = f"确定删除「{sub.title}」吗？"
        box = QMessageBox(QMessageBox.Question, "删除子目标", text)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.setWindowModality(Qt.ApplicationModal)
        box.setWindowFlags(
            Qt.Dialog
            | Qt.WindowStaysOnTopHint
            | Qt.WindowTitleHint
            | Qt.MSWindowsFixedSizeDialogHint
        )
        box.adjustSize()
        anchor = self.frameGeometry()
        box.move(
            anchor.center().x() - box.width() // 2,
            anchor.center().y() - box.height() // 2,
        )
        box.raise_()
        box.activateWindow()
        return box.exec() == QMessageBox.Yes

    def _update_action_visibility(self, active: Task | None) -> None:
        has_active = active is not None and active.status == TaskStatus.ACTIVE
        self.subgoal_section.setVisible(has_active)
        self.add_sub_row.setVisible(has_active)

    def _update_goal_actions(
        self,
        active: Task | None,
        paused: list[Task] | None = None,
    ) -> None:
        if active is not None and active.status == TaskStatus.ACTIVE:
            self.goal_pause_btn.show()
            self.goal_resume_btn.hide()
            return
        if paused is None:
            paused = self.manager.by_status(TaskStatus.PAUSED)
        if paused:
            self.goal_pause_btn.hide()
            self.goal_resume_btn.show()
        else:
            self.goal_pause_btn.hide()
            self.goal_resume_btn.hide()

    def _paused_tasks(self) -> list[Task]:
        return self.manager.by_status(TaskStatus.PAUSED)

    def _clamp_browse_index(self, paused: list[Task]) -> int:
        if not paused:
            self._browse_index = 0
            return 0
        self._browse_index = max(0, min(self._browse_index, len(paused) - 1))
        return self._browse_index

    def _sync_goal_browse_slider(self, paused: list[Task], *, visible: bool) -> None:
        if not visible or len(paused) <= 1:
            self.goal_browse_slider.hide()
            return
        idx = self._clamp_browse_index(paused)
        self.goal_browse_slider.blockSignals(True)
        self.goal_browse_slider.setMaximum(len(paused) - 1)
        self.goal_browse_slider.setValue(idx)
        self.goal_browse_slider.blockSignals(False)
        self.goal_browse_slider.show()

    def _on_goal_browse_changed(self, value: int) -> None:
        paused = self._paused_tasks()
        if len(paused) <= 1:
            return
        self._browse_index = max(0, min(int(value), len(paused) - 1))
        self.refresh()

    def _on_goal_pause(self) -> None:
        active = self.state.active_task()
        if active is None:
            return
        paused_id = active.id
        self.manager.pause(paused_id)
        paused = self._paused_tasks()
        for i, t in enumerate(paused):
            if t.id == paused_id:
                self._browse_index = i
                break
        self.state_changed.emit()
        self.refresh()

    def _on_goal_resume(self) -> None:
        paused = self._paused_tasks()
        if not paused:
            return
        idx = self._clamp_browse_index(paused)
        self.manager.resume(paused[idx].id)
        self.state_changed.emit()
        self.refresh()

    def _on_sub_focus(self, subtask_id: str) -> None:
        active = self.state.active_task()
        if active is None:
            return
        if self.manager.focus_subtask(active.id, subtask_id):
            self.state_changed.emit()
            self.refresh()

    def _on_sub_pause(self, task_id: str) -> None:
        if self.manager.pause_subtask_focus(task_id):
            self.state_changed.emit()
            self.refresh()

    def _on_sub_complete(self, subtask_id: str) -> None:
        active = self.state.active_task()
        if active is None:
            return
        if self.manager.confirm_manual_complete_subtask(active.id, subtask_id):
            self.state_changed.emit()
            self.refresh()

    def _on_sub_claim(self, subtask_id: str) -> None:
        active = self.state.active_task()
        if active is None:
            return
        sub = next((s for s in active.subtasks if s.id == subtask_id), None)
        if sub is None:
            return
        reward = self.manager.complete_and_claim_subtask(active.id, subtask_id)
        if reward is not None:
            self.subtask_claimed.emit(sub.title, reward)
        self.state_changed.emit()
        self.refresh()

    def _on_sub_delete(self, subtask_id: str) -> None:
        active = self.state.active_task()
        if active is None:
            return
        sub = next((s for s in active.subtasks if s.id == subtask_id), None)
        if sub is None:
            return
        if sub.is_claimable() or (sub.done and not sub.rewards_claimed):
            if not self._confirm_subgoal_delete(sub, has_rewards=True):
                return
        elif not sub.done and (sub.pending_rewards or sub.operations > 0):
            if not self._confirm_subgoal_delete(sub, has_rewards=False):
                return
        if not self.manager.delete_subtask(active.id, subtask_id):
            return
        self.state_changed.emit()
        self.refresh()

    def _on_subtask_min_changed(self, value: int) -> None:
        self.state.settings["subtask_default_target_minutes"] = max(1, int(value))
        save_state(self.state)

    def _on_add_subgoal(self) -> None:
        active = self.state.active_task()
        if active is None:
            return
        title = self.subgoal_input.text().strip()
        if not title:
            return
        target_minutes = self.subgoal_min_spin.value()
        self.state.settings["subtask_default_target_minutes"] = target_minutes
        self.manager.add_subtask(active.id, title, target_minutes=target_minutes)
        self.subgoal_input.clear()
        self.state_changed.emit()
        self.refresh()

    def _on_add_goal(self) -> None:
        title, ok = QInputDialog.getText(self, "新建目标", "目标标题：")
        if not ok:
            return
        title = title.strip()
        if not title:
            return
        self.manager.create(title)
        self.state_changed.emit()
        self.refresh()

    def _refresh_task_actions(self, active: Task | None) -> None:
        self._refresh_subgoal_section(active)
        self._update_action_visibility(active)

    def _apply_task_section(
        self,
        active: Task | None,
        *,
        since_gold: float,
        since_diamond: float,
    ) -> None:
        paused = self._paused_tasks()
        if active is None:
            self._refresh_task_actions(None)
            self._update_goal_actions(None, paused)
            if paused:
                idx = self._clamp_browse_index(paused)
                p = paused[idx]
                title = p.title
                if p.subtasks:
                    done, total = p.subtask_progress()
                    title = f"{p.title}  ({done}/{total})"
                suffix = f" (已暂停)  {idx + 1}/{len(paused)}"
                self._set_text(self.task_title, f"{title}{suffix}")
                earned_gold, earned_diamond = p.earned_totals()
                self.task_stats.show_active_compact(
                    p.operations,
                    earned_gold,
                    earned_diamond,
                    since_roll_gold=since_gold,
                    since_roll_diamond=since_diamond,
                )
                self._sync_goal_browse_slider(paused, visible=True)
            else:
                self._set_text(self.task_title, "还没有目标")
                self.task_stats.show_hint("点击「目标管理」创建第一个目标")
                self._sync_goal_browse_slider(paused, visible=False)
            return

        self._sync_goal_browse_slider(paused, visible=False)
        self._set_text(self.task_title, self._format_task_title(active))
        self._refresh_task_actions(active)
        self._update_goal_actions(active, paused)
        duration = format_duration(active.active_duration_seconds())
        sub = active.current_subtask()
        sub_duration = format_duration(sub.active_seconds) if sub is not None else ""
        earned_gold, earned_diamond = active.earned_totals()
        self.task_stats.show_active_compact(
            active.operations,
            earned_gold,
            earned_diamond,
            since_roll_gold=since_gold,
            since_roll_diamond=since_diamond,
            duration=duration,
            sub_duration=sub_duration,
        )

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
        chance_label = (
            f"金 {rt.gold_chance:.0%}  钻 {rt.diamond_chance:.0%}"
        )
        self.roll_bar.set_cycle(
            progress,
            span,
            rt.segment_colors,
            chance_label=chance_label,
        )

    def refresh_roll_meta(self) -> None:
        """仅更新进度条概率/颜色元数据（10 分钟重抽后调用）。"""
        self._update_roll_bar()

    def show_roll_result(self, reward: Reward) -> None:
        """开奖结果轻量 Toast + 进度条闪动。"""
        if reward.is_empty():
            self.roll_toast.setObjectName("RollToast RollToastMiss")
            self.roll_toast.setStyleSheet(WIDGET_STYLESHEET)
            self.roll_toast.setText("未中")
            hide_ms = 1200
        elif reward.gold > 0 and reward.diamond > 0:
            self.roll_toast.setObjectName("RollToast RollToastDiam")
            self.roll_toast.setStyleSheet(WIDGET_STYLESHEET)
            self.roll_toast.setText(
                f"+{format_amount(reward.gold)} 金 +{format_amount(reward.diamond)} 钻"
            )
            hide_ms = 2200
        elif reward.diamond > 0:
            self.roll_toast.setObjectName("RollToast RollToastDiam")
            self.roll_toast.setStyleSheet(WIDGET_STYLESHEET)
            self.roll_toast.setText(f"+{format_amount(reward.diamond)} 钻石")
            hide_ms = 2000
        else:
            self.roll_toast.setObjectName("RollToast RollToastGold")
            self.roll_toast.setStyleSheet(WIDGET_STYLESHEET)
            self.roll_toast.setText(f"+{format_amount(reward.gold)} 金币")
            hide_ms = 2000

        self.roll_toast.show()
        self._flash_roll_bar()

        if self._roll_toast_timer is not None:
            self._roll_toast_timer.stop()
        self._roll_toast_timer = QTimer(self)
        self._roll_toast_timer.setSingleShot(True)
        self._roll_toast_timer.setInterval(hide_ms)
        self._roll_toast_timer.timeout.connect(self.roll_toast.hide)
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
        active = s.active_task()

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

        self._apply_task_section(
            active,
            since_gold=s.since_roll.gold,
            since_diamond=s.since_roll.diamond,
        )

    # ---------- 刷新 ----------
    def refresh(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        s = self.state
        ops_1min = self._op_tracker.count_recent()
        active = s.active_task()

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

        self._apply_task_section(
            active,
            since_gold=s.since_roll.gold,
            since_diamond=s.since_roll.diamond,
        )

    def _refresh_runtime(self) -> None:
        """仅刷新与时间相关的字段，避免整窗口频繁重绘。"""
        self.manager.tick_active_time()
        self._tick_count = getattr(self, '_tick_count', 0) + 1
        if self._tick_count % 60 == 0:
            logger.debug("运行中 (ops=%d)", self.state.total_operations)
        ops_1min = self._op_tracker.count_recent()
        active = self.state.active_task()

        self._set_html(
            self.global_summary,
            self._format_global_summary_html(ops_1min),
        )

        if active is None:
            return

        self._set_text(self.task_title, self._format_task_title(active))
        self._refresh_task_actions(active)
        duration = format_duration(active.active_duration_seconds())
        sub = active.current_subtask()
        sub_duration = format_duration(sub.active_seconds) if sub is not None else ""
        earned_gold, earned_diamond = active.earned_totals()
        since = self.state.since_roll
        self.task_stats.show_active_compact(
            active.operations,
            earned_gold,
            earned_diamond,
            since_roll_gold=since.gold,
            since_roll_diamond=since.diamond,
            duration=duration,
            sub_duration=sub_duration,
        )

    # ---------- 显示时初始化窗口属性 ----------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.state.settings.get("pin_all_desktops", True):
            pin_window_to_all_desktops(int(self.winId()))
