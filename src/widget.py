"""主悬浮小部件：常驻桌面，显示操作数 / 奖励 / 当前目标。"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt, QPoint, QRect, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QHelpEvent, QMouseEvent, QTextDocument
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
    QScrollBar,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionSlider,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .goal_actions import try_complete_goal, try_delete_goal
from .op_tracker import OpRateTracker
from .models import AppState, Reward, Subtask, Task, TaskStatus
from .reward_system import roll_progress
from .storage import save_state
from .task_manager import TaskManager
from .ui_roll_bar import SegmentedRollBar
from .ui_confirm import ask_yes_no
from .ui_task_tree import (
    GOAL_TREE_PANEL_QSS,
    TREE_DETAIL_QSS,
    TREE_INDENT_PX,
    SubtaskActionCallbacks,
    TreeRow,
    append_subtask_detail_actions,
    apply_goal_block_hover,
    apply_goal_block_ui,
    apply_goal_root_row_state,
    apply_subtask_block_ui,
    build_subtask_action_buttons,
)
from .ui_text import (
    format_global_summary_html,
    format_goal_root_line_html,
    format_roll_history_lines_html,
    format_roll_toast_html,
    format_subgoals_focus_hint_html,
    format_tree_detail_html,
    format_tree_node_html,
)
from .win_utils import (
    is_windows,
    pin_window_to_all_desktops,
    set_startup,
    unpin_window_from_all_desktops,
)

logger = logging.getLogger(__name__)

SUBGOAL_INDENT_PX = TREE_INDENT_PX

_DRAG_BLOCK_TYPES = (QPushButton, QLineEdit, QSpinBox, QScrollArea)


class DragHandleBar(QWidget):
    """顶栏拖动手柄：拖动移动顶层窗口。"""

    def __init__(self, window: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._drag_offset: QPoint | None = None
        self.setObjectName("DragHandle")
        self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            )
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class WindowDragHelper(QObject):
    """为全局区等区域安装拖动：左键拖动移动顶层窗口。"""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._drag_offset: QPoint | None = None

    def attach(self, root: QWidget) -> None:
        root.installEventFilter(self)
        for child in root.findChildren(QWidget):
            if isinstance(child, _DRAG_BLOCK_TYPES):
                continue
            child.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if isinstance(obj, _DRAG_BLOCK_TYPES):
            return False
        if event.type() == QEvent.Type.MouseButtonPress:
            me = event
            if isinstance(me, QMouseEvent) and me.button() == Qt.LeftButton:
                self._drag_offset = (
                    me.globalPosition().toPoint()
                    - self._window.frameGeometry().topLeft()
                )
                return True
        elif event.type() == QEvent.Type.MouseMove:
            me = event
            if (
                isinstance(me, QMouseEvent)
                and self._drag_offset is not None
                and me.buttons() & Qt.LeftButton
            ):
                self._window.move(
                    me.globalPosition().toPoint() - self._drag_offset
                )
                return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            self._drag_offset = None
        return False


WIDGET_STYLESHEET = """
QWidget#WidgetRoot {
    background-color: rgba(28, 28, 38, 235);
    border-radius: 14px;
    border: 1px solid rgba(255,255,255,30);
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
QLabel#RollToast[toast="miss"] { color: #8a909e; }
QFrame#Divider { background-color: rgba(255,255,255,18); max-height: 1px; min-height: 1px; }
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
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        flags = (
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setFixedWidth(308)
        self.setMinimumHeight(600)
        # 高度上限：内容再多也只在窗口内滚动，不让布局把窗口越顶越高
        self.setMaximumHeight(760)
        self.resize(308, 680)

        self._op_tracker = OpRateTracker(window_sec=60.0)
        self._subgoal_structure_sig: tuple | None = None
        self._subgoal_line_labels: dict[str, QLabel] = {}
        self._tree_row_widgets: dict[str, TreeRow] = {}
        self._subtask_blocks: dict[str, QWidget] = {}
        self._goal_root_rows: dict[str, TreeRow] = {}
        self._goal_root_lines: dict[str, QLabel] = {}
        self._goal_blocks: dict[str, QWidget] = {}
        self._expanded_goal_ids: set[str] = set()
        self._sub_add_parent_id: Optional[str] = None
        self._selected_task_id: str = ""
        self._selected_subtask_id: str = ""
        self._goal_detail_actions_sig: tuple | None = None
        self._subgoals_content_size: tuple[int, int] = (0, 0)
        self._hovered_goal_id: str = ""
        self._state_sync_pending = False
        self._local_refresh_pending = False
        self._geometry_sync_pending = False
        self._geometry_syncing = False
        self._refreshing = False
        self._roll_toast_timer: Optional[QTimer] = None

        self._drag_helper: WindowDragHelper | None = None

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

        # --- 目标树（父目标 + 子目标目录） ---
        self.task_tree_section = QWidget()
        self.task_tree_section.setObjectName("TaskTreeSection")
        self.task_tree_section.setSizePolicy(
            QSizePolicy.Preferred,
            QSizePolicy.Expanding,
        )
        tree_lay = QVBoxLayout(self.task_tree_section)
        tree_lay.setContentsMargins(0, 0, 0, 0)
        tree_lay.setSpacing(6)
        tree_lay.addWidget(self._make_section_title("目标"))

        self.subgoals_scroll = QScrollArea()
        self.subgoals_scroll.setObjectName("SubGoalScroll")
        self.subgoals_scroll.setFrameShape(QFrame.NoFrame)
        self.subgoals_scroll.setWidgetResizable(False)
        # 最小高度保持在窗口 600 预算内，避免固定部分(顶栏+全局+按钮)把窗口顶高
        self.subgoals_scroll.setMinimumHeight(160)
        self.subgoals_scroll.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )
        self.subgoals_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.subgoals_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.subgoals_container = QWidget()
        self.subgoals_container.setObjectName("SubGoalContainer")
        self.subgoals_container.setAutoFillBackground(True)
        self.subgoals_scroll.viewport().setObjectName("SubGoalViewport")
        self.subgoals_scroll.viewport().setAutoFillBackground(True)
        self.subgoals_layout = QVBoxLayout(self.subgoals_container)
        self.subgoals_layout.setContentsMargins(0, 0, 0, 0)
        self.subgoals_layout.setSpacing(2)
        self.subgoals_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.subgoals_hbar = QScrollBar(Qt.Orientation.Horizontal)
        self.subgoals_hbar.setObjectName("SubGoalHBar")
        self.subgoals_hbar.setCursor(Qt.PointingHandCursor)
        self.subgoals_hbar.setAttribute(Qt.WA_Hover, True)
        self.subgoals_hbar.setAutoFillBackground(True)
        self.subgoals_hbar.installEventFilter(self)
        self.subgoals_hbar.hide()
        self.subgoals_vbar = self.subgoals_scroll.verticalScrollBar()
        self.subgoals_vbar.setAttribute(Qt.WA_Hover, True)
        self.subgoals_vbar.setAutoFillBackground(True)
        self.subgoals_vbar.installEventFilter(self)
        inner_hbar = self.subgoals_scroll.horizontalScrollBar()
        inner_hbar.rangeChanged.connect(self._sync_subgoals_hbar)
        inner_hbar.valueChanged.connect(self._on_subgoals_inner_hscroll)
        self.subgoals_hbar.valueChanged.connect(self._on_subgoals_outer_hscroll)

        self.subgoals_scroll.viewport().installEventFilter(self)
        self.subgoals_scroll.setWidget(self.subgoals_container)
        tree_lay.addWidget(self.subgoals_scroll, 1)
        tree_lay.addWidget(self.subgoals_hbar)

        self.subgoals_hint = QLabel("")
        self.subgoals_hint.setObjectName("SubGoalHint")
        self.subgoals_hint.setWordWrap(True)
        self.subgoals_hint.hide()
        tree_lay.addWidget(self.subgoals_hint)

        self.subgoals_empty = QLabel("还没有目标")
        self.subgoals_empty.setObjectName("SubGoalList")
        self.subgoals_empty.setWordWrap(True)
        tree_lay.addWidget(self.subgoals_empty)

        self.subgoal_actions = QWidget()
        self.subgoal_actions.setObjectName("SubGoalActions")
        actions_layout = QVBoxLayout(self.subgoal_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(4)

        actions_layout.addWidget(self._make_section_title("添加子目标"))

        add_sub_row = QHBoxLayout()
        add_sub_row.setSpacing(4)
        self.subgoal_input = QLineEdit()
        self.subgoal_input.setObjectName("SubGoalInput")
        self.subgoal_input.setPlaceholderText("子目标标题…")
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
        self.subgoal_min_spin.setToolTip("新目标需运行的最短时间（达标后可完成领奖）")
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

        self.subgoal_add_context = QLabel("")
        self.subgoal_add_context.setObjectName("SubGoalHint")
        self.subgoal_add_context.setWordWrap(True)
        self.subgoal_add_context.hide()
        actions_layout.addWidget(self.subgoal_add_context)

        self.goal_detail_panel = QWidget()
        self.goal_detail_panel.setObjectName("GoalDetailPanel")
        # 面板内容随选中变化；忽略其垂直尺寸贡献，让外层布局分配面板高度，
        # 否则点击目标树后详情面板的最小高度会把整个悬浮窗顶高
        self.goal_detail_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        detail_lay = QVBoxLayout(self.goal_detail_panel)
        detail_lay.setContentsMargins(8, 6, 8, 6)
        detail_lay.setSpacing(4)

        self.goal_detail_title = QLabel("")
        self.goal_detail_title.setObjectName("GoalDetailTitle")
        self.goal_detail_title.setWordWrap(True)
        detail_lay.addWidget(self.goal_detail_title)

        self.goal_detail_stats = QLabel("")
        self.goal_detail_stats.setObjectName("GoalDetailStats")
        self.goal_detail_stats.setWordWrap(True)
        self.goal_detail_stats.setTextFormat(Qt.RichText)
        detail_lay.addWidget(self.goal_detail_stats)

        self.goal_detail_btn_row = QWidget()
        self.goal_detail_btn_row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.goal_detail_btn_lay = QHBoxLayout(self.goal_detail_btn_row)
        self.goal_detail_btn_lay.setContentsMargins(0, 0, 0, 0)
        self.goal_detail_btn_lay.setSpacing(6)
        detail_lay.addWidget(self.goal_detail_btn_row)

        self.goal_detail_panel.hide()

        v.addWidget(self.task_tree_section, 1)

        self.subgoal_actions.hide()
        v.addWidget(self.subgoal_actions)
        v.addWidget(self.goal_detail_panel)

        self.goal_add_btn = QPushButton("新建顶层目标")
        self.goal_add_btn.setObjectName("GoalAddBtn")
        self.goal_add_btn.setCursor(Qt.PointingHandCursor)
        self.goal_add_btn.setToolTip("创建与当前列表并列的新目标（非子目标）")
        self.goal_add_btn.clicked.connect(self._on_add_goal)
        v.addWidget(self.goal_add_btn)

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
    def _html_label_width(label: QLabel) -> int:
        doc = QTextDocument()
        doc.setDefaultFont(label.font())
        doc.setHtml(label.text())
        return max(int(doc.idealWidth()) + 8, 0)

    def _pin_tree_label_width(self, label: QLabel) -> None:
        width = self._html_label_width(label)
        if label.minimumWidth() != width:
            label.setMinimumWidth(width)

    def _sync_subgoals_hbar(self, *_args) -> None:
        if not hasattr(self, "subgoals_hbar"):
            return
        inner = self.subgoals_scroll.horizontalScrollBar()
        need_hbar = (
            self.subgoals_scroll.isVisible() and inner.maximum() > 0
        )
        self.subgoals_hbar.blockSignals(True)
        self.subgoals_hbar.setRange(inner.minimum(), inner.maximum())
        self.subgoals_hbar.setPageStep(max(inner.pageStep(), 1))
        self.subgoals_hbar.setSingleStep(max(inner.singleStep(), 1))
        self.subgoals_hbar.setValue(inner.value())
        self.subgoals_hbar.blockSignals(False)
        # 仅在需要横向滚动时显示，避免显隐抖动触发视口 Resize 死循环
        if self.subgoals_hbar.isVisible() != need_hbar:
            self.subgoals_hbar.setVisible(need_hbar)
        self.subgoals_hbar.setEnabled(need_hbar)

    def _on_subgoals_inner_hscroll(self, value: int) -> None:
        if self.subgoals_hbar.value() != value:
            self.subgoals_hbar.blockSignals(True)
            self.subgoals_hbar.setValue(value)
            self.subgoals_hbar.blockSignals(False)

    def _on_subgoals_outer_hscroll(self, value: int) -> None:
        inner = self.subgoals_scroll.horizontalScrollBar()
        if inner.value() != value:
            inner.setValue(value)

    def _widget_goals(self) -> list[Task]:
        goals = [
            t
            for t in self.state.tasks
            if t.status in (TaskStatus.ACTIVE, TaskStatus.PAUSED)
        ]
        return sorted(goals, key=lambda t: float(t.created_at or 0), reverse=True)

    @staticmethod
    def _sub_line_key(task_id: str, sub_id: str) -> str:
        return f"{task_id}:{sub_id}"

    def _sync_expanded_goals(self, active: Task | None) -> None:
        valid = {t.id for t in self._widget_goals()}
        self._expanded_goal_ids &= valid

    def _is_goal_expanded(self, task_id: str) -> bool:
        return task_id in self._expanded_goal_ids

    def _reveal_subtask_path(self, task_id: str, subtask_id: str) -> None:
        """展开顶层目标并展开到子项的路径（不全树展开）。"""
        self._expanded_goal_ids.add(task_id)
        self.manager.expand_subtask_path(task_id, subtask_id)

    def _request_state_sync(self) -> None:
        """延迟到点击处理结束后再存档+刷新，避免销毁当前按钮导致卡死。"""
        self._goal_detail_actions_sig = None
        if self._state_sync_pending:
            return
        self._state_sync_pending = True
        QTimer.singleShot(0, self._flush_state_sync)

    def _flush_state_sync(self) -> None:
        self._state_sync_pending = False
        self.state_changed.emit()

    def _request_local_refresh(self) -> None:
        """仅刷新悬浮窗，不写盘。"""
        if self._local_refresh_pending:
            return
        self._local_refresh_pending = True
        QTimer.singleShot(0, self._flush_local_refresh)

    def _flush_local_refresh(self) -> None:
        self._local_refresh_pending = False
        self.refresh()

    def _measure_subgoals_content_size(self) -> tuple[int, int]:
        """按标题自然宽度测量内容区，便于横向滚动。"""
        block_pad = 12
        row_pad = 8
        fold_extra = 22
        margins = self.subgoals_layout.contentsMargins()
        spacing = self.subgoals_layout.spacing()
        max_w = 0
        total_h = margins.top() + margins.bottom()
        count = 0

        for task_id, block in self._goal_blocks.items():
            task = self.manager.get(task_id)
            block_w = block_pad
            root_line = self._goal_root_lines.get(task_id)
            root_row = self._goal_root_rows.get(task_id)
            if root_line is not None:
                self._pin_tree_label_width(root_line)
                row_w = row_pad + self._html_label_width(root_line)
                if root_row is not None and root_row.layout().count() > 1:
                    row_w += fold_extra
                block_w = max(block_w, block_pad + row_w)

            if task is not None and self._is_goal_expanded(task_id):
                for depth, sub in self.manager.iter_visible_subtasks(task):
                    key = self._sub_line_key(task_id, sub.id)
                    sub_line = self._subgoal_line_labels.get(key)
                    if sub_line is None:
                        continue
                    self._pin_tree_label_width(sub_line)
                    indent = (depth + 1) * SUBGOAL_INDENT_PX
                    row_w = block_pad + indent + row_pad + self._html_label_width(sub_line)
                    row = self._tree_row_widgets.get(key)
                    if row is not None:
                        row_w = max(row_w, row.sizeHint().width() + indent)
                    if sub.is_container():
                        row_w += fold_extra
                    block_w = max(block_w, row_w)

            max_w = max(max_w, block_w)
            block.adjustSize()
            total_h += max(block.sizeHint().height(), block.height(), 1)
            count += 1

        if count > 1:
            total_h += spacing * (count - 1)
        return (
            max(max_w + margins.left() + margins.right(), 1),
            max(total_h, 1),
        )

    def _request_geometry_sync(self, *, remeasure: bool = False) -> None:
        """延迟几何同步，避免 Resize 事件重入卡死。"""
        if remeasure:
            self._subgoals_content_size = (0, 0)
        if self._geometry_sync_pending:
            return
        self._geometry_sync_pending = True
        QTimer.singleShot(0, self._flush_geometry_sync)

    def _flush_geometry_sync(self) -> None:
        self._geometry_sync_pending = False
        self._sync_subgoals_container_geometry(remeasure=True)

    def _sync_subgoals_container_geometry(self, *, remeasure: bool = False) -> None:
        """按内容实际宽度撑开容器，超出时出现横向/纵向滚动条。"""
        if self._geometry_syncing:
            return
        if not self.subgoals_scroll.isVisible():
            self.subgoals_hbar.hide()
            return
        self._geometry_syncing = True
        try:
            if remeasure or self._subgoals_content_size == (0, 0):
                self._subgoals_content_size = self._measure_subgoals_content_size()
            content_w, content_h = self._subgoals_content_size
            viewport = self.subgoals_scroll.viewport()
            vw = max(viewport.width(), 1)
            w = max(content_w, vw)
            h = max(content_h, 1)
            if (
                self.subgoals_container.width() != w
                or self.subgoals_container.height() != h
            ):
                self.subgoals_container.resize(w, h)
            self._sync_subgoals_hbar()
        finally:
            self._geometry_syncing = False

    def _goal_id_for_widget(self, widget: QWidget) -> str:
        for task_id, block in self._goal_blocks.items():
            if widget is block or block.isAncestorOf(widget):
                return task_id
        return ""

    def _apply_goal_hover_ui(self) -> None:
        for task_id, block in self._goal_blocks.items():
            apply_goal_block_hover(
                block,
                hovered=task_id == self._hovered_goal_id,
            )

    def _sync_goal_block_hover(self) -> None:
        pos = QCursor.pos()
        hovered_id = ""
        for task_id, block in self._goal_blocks.items():
            if not block.isVisible():
                continue
            if block.rect().contains(block.mapFromGlobal(pos)):
                hovered_id = task_id
                break
        if hovered_id != self._hovered_goal_id:
            self._hovered_goal_id = hovered_id
            self._apply_goal_hover_ui()

    def _install_goal_hover_filters(self, block: QWidget) -> None:
        # 只装在 GoalBlock 上，不要递归装到每个子控件（否则悬停事件风暴会卡死）
        block.setAttribute(Qt.WA_Hover, True)
        block.installEventFilter(self)

    @staticmethod
    def _scrollbar_handle_rect(bar: QScrollBar) -> QRect:
        opt = QStyleOptionSlider()
        bar.initStyleOption(opt)
        return bar.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar,
            opt,
            QStyle.SubControl.SC_ScrollBarSlider,
            bar,
        )

    def _scrollbar_handle_tooltip(self, bar: QScrollBar) -> str:
        if bar is self.subgoals_hbar:
            return "左右拖动查看完整标题"
        return "上下滚动目标列表"

    def _show_scrollbar_handle_tooltip(self, bar: QScrollBar, event: QHelpEvent) -> bool:
        if not bar.isEnabled():
            QToolTip.hideText()
            return True
        handle = self._scrollbar_handle_rect(bar)
        if handle.contains(event.position().toPoint()):
            QToolTip.showText(
                event.globalPosition().toPoint(),
                self._scrollbar_handle_tooltip(bar),
                bar,
                handle,
            )
            return True
        QToolTip.hideText()
        return True

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if isinstance(obj, QWidget):
            task_id = self._goal_id_for_widget(obj)
            if task_id:
                if event.type() in (
                    QEvent.Type.Enter,
                    QEvent.Type.HoverEnter,
                ):
                    if self._hovered_goal_id != task_id:
                        self._hovered_goal_id = task_id
                        self._apply_goal_hover_ui()
                elif event.type() in (
                    QEvent.Type.Leave,
                    QEvent.Type.HoverLeave,
                ):
                    QTimer.singleShot(0, self._sync_goal_block_hover)
        hbar = getattr(self, "subgoals_hbar", None)
        vbar = getattr(self, "subgoals_vbar", None)
        if hbar is not None and vbar is not None and obj in (hbar, vbar):
            if event.type() == QEvent.Type.ToolTip:
                if isinstance(event, QHelpEvent):
                    return self._show_scrollbar_handle_tooltip(obj, event)
            elif event.type() == QEvent.Type.Leave:
                QToolTip.hideText()
        if (
            obj is self.subgoals_scroll.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._request_geometry_sync(remeasure=False)
        return super().eventFilter(obj, event)

    @staticmethod
    def _goal_detail_actions_signature(
        task: Task,
        sub: Subtask | None,
    ) -> tuple:
        if sub is None:
            has_unfocused_subs = bool(
                task.subtasks
                and task.status == TaskStatus.ACTIVE
                and task.current_subtask() is None
            )
            return ("goal", task.id, task.status, has_unfocused_subs)
        return (
            "sub",
            task.id,
            sub.id,
            sub.done,
            sub.rewards_claimed,
            sub.is_leaf(),
            sub.is_container(),
            sub.is_claimable(),
            sub.can_claim_pending(),
            sub.can_finish(),
            sub.is_legacy_progress(),
            sub.time_target_met(),
            task.current_subtask_id,
            task.status,
        )

    def _apply_tree_selection_chrome(self) -> None:
        """选中/聚焦描边（不更新文本，开销低）。"""
        for task_id, row in self._goal_root_rows.items():
            row.set_row_selected(
                task_id == self._selected_task_id and not self._selected_subtask_id
            )
        for key, row in self._tree_row_widgets.items():
            task_id, sub_id = key.split(":", 1)
            row.set_row_selected(
                task_id == self._selected_task_id
                and sub_id == self._selected_subtask_id
            )
            task = self.manager.get(task_id)
            active_path: frozenset[str] = frozenset()
            if task is not None and task.status == TaskStatus.ACTIVE:
                active_path = task.active_focus_path_ids()
            row.set_row_focused(sub_id in active_path)

        for key, sub_block in self._subtask_blocks.items():
            task_id, sub_id = key.split(":", 1)
            task = self.manager.get(task_id)
            if task is None:
                continue
            active_path = task.active_focus_path_ids()
            is_sub_selected = (
                task_id == self._selected_task_id
                and sub_id == self._selected_subtask_id
                and bool(self._selected_subtask_id)
            )
            apply_subtask_block_ui(
                sub_block,
                selected=is_sub_selected,
                focused=sub_id in active_path,
            )

        for task in self._widget_goals():
            block = self._goal_blocks.get(task.id)
            if block is not None:
                goal_selected = (
                    task.id == self._selected_task_id
                    and not self._selected_subtask_id
                )
                apply_goal_block_ui(
                    block,
                    is_running=task.status == TaskStatus.ACTIVE,
                    selected=goal_selected,
                    focused=bool(task.active_focus_path_ids()),
                )
                apply_goal_block_hover(
                    block,
                    hovered=task.id == self._hovered_goal_id,
                )

    def _refresh_tree_labels(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
        stats_only: bool = False,
    ) -> None:
        for task in self._widget_goals():
            editable = task.status == TaskStatus.ACTIVE
            active_path = task.active_focus_path_ids() if editable else frozenset()

            if not stats_only:
                line = self._goal_root_lines.get(task.id)
                if line is not None:
                    self._set_html(
                        line,
                        format_goal_root_line_html(
                            task,
                            selected=(
                                task.id == self._selected_task_id
                                and not self._selected_subtask_id
                            ),
                            is_running=task.status == TaskStatus.ACTIVE,
                            muted=task.status == TaskStatus.PAUSED,
                        ),
                    )
                    self._pin_tree_label_width(line)

            for sub_key, sub_line in self._subgoal_line_labels.items():
                if not sub_key.startswith(f"{task.id}:"):
                    continue
                sid = sub_key.split(":", 1)[1]
                sub = task.find_subtask(sid)
                if sub is None:
                    continue
                is_selected = (
                    task.id == self._selected_task_id
                    and sid == self._selected_subtask_id
                )
                is_current = sid in active_path
                if stats_only and not (is_selected or is_current):
                    continue
                show_stats = is_selected or is_current
                self._set_html(
                    sub_line,
                    format_tree_node_html(
                        sub,
                        selected=is_selected,
                        is_current=is_current,
                        expanded=self.manager.is_subtask_expanded(task.id, sub.id),
                        show_stats=show_stats,
                    ),
                )
                self._pin_tree_label_width(sub_line)

        self._sync_subgoals_container_geometry(remeasure=True)

    def _subtask_completion_bonus(self) -> float:
        return float(self.state.settings.get("subtask_completion_bonus_gold", 0.5))

    def _refresh_goal_detail_stats_only(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
    ) -> None:
        if not self._selected_task_id or not self.goal_detail_panel.isVisible():
            return
        task = self.manager.get(self._selected_task_id)
        if task is None:
            return
        sub: Subtask | None = None
        if self._selected_subtask_id:
            sub = task.find_subtask(self._selected_subtask_id)
        self._set_html(
            self.goal_detail_stats,
            format_tree_detail_html(
                task,
                sub,
                since_roll_gold=since_gold,
                since_roll_diamond=since_diamond,
                completion_bonus=self._subtask_completion_bonus(),
            ),
        )

    def _refresh_task_ops_ui(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
    ) -> None:
        """按键/计时后仅刷新统计文本，不重建树或按钮。"""
        self._refresh_tree_labels(
            since_gold=since_gold,
            since_diamond=since_diamond,
            stats_only=True,
        )
        if not self._selected_task_id or not self.goal_detail_panel.isVisible():
            return
        task = self.manager.get(self._selected_task_id)
        if task is None:
            return
        sub: Subtask | None = None
        if self._selected_subtask_id:
            sub = task.find_subtask(self._selected_subtask_id)
        if self._goal_detail_actions_signature(task, sub) != self._goal_detail_actions_sig:
            self._refresh_goal_detail_panel(
                since_gold=since_gold,
                since_diamond=since_diamond,
            )
        else:
            self._refresh_goal_detail_stats_only(
                since_gold=since_gold,
                since_diamond=since_diamond,
            )

    def _on_goal_toggle_fold(self, task_id: str) -> None:
        if task_id in self._expanded_goal_ids:
            self._expanded_goal_ids.discard(task_id)
        else:
            self._expanded_goal_ids.add(task_id)
        self._request_local_refresh()

    def _clear_tree_layout(self) -> None:
        self._goal_root_rows.clear()
        self._goal_root_lines.clear()
        self._subtask_blocks.clear()
        self._goal_blocks.clear()
        self._hovered_goal_id = ""
        self._subgoals_content_size = (0, 0)
        self._goal_detail_actions_sig = None
        while self.subgoals_layout.count():
            item = self.subgoals_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # 必须先 hide：勿 setParent(None)，否则会变成顶层窗口挡住点击
                widget.hide()
                widget.deleteLater()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
            elif item.layout() is not None:
                FloatingWidget._clear_layout(item.layout())

    def _refresh_goal_detail_panel(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
    ) -> None:
        task_id = self._selected_task_id
        if not task_id:
            self.goal_detail_panel.hide()
            self._goal_detail_actions_sig = None
            return
        task = self.manager.get(task_id)
        if task is None:
            self.goal_detail_panel.hide()
            self._goal_detail_actions_sig = None
            return

        self.goal_detail_panel.show()
        sub: Subtask | None = None
        if self._selected_subtask_id:
            sub = task.find_subtask(self._selected_subtask_id)

        title_text = sub.title if sub is not None else task.title
        self._set_text(self.goal_detail_title, title_text)
        self._set_html(
            self.goal_detail_stats,
            format_tree_detail_html(
                task,
                sub,
                since_roll_gold=since_gold,
                since_roll_diamond=since_diamond,
                completion_bonus=self._subtask_completion_bonus(),
            ),
        )

        actions_sig = self._goal_detail_actions_signature(task, sub)
        if actions_sig == self._goal_detail_actions_sig:
            return
        self._goal_detail_actions_sig = actions_sig
        self._clear_layout(self.goal_detail_btn_lay)
        if sub is None and task.status != TaskStatus.COMPLETED:
            if task.status == TaskStatus.PAUSED:
                btn = QPushButton("开始运行")
                btn.setObjectName("GoalResumeBtn")
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(
                    lambda _c=False, tid=task.id: self._on_goal_resume(tid)
                )
                self.goal_detail_btn_lay.addWidget(btn)
            elif task.status == TaskStatus.ACTIVE:
                btn = QPushButton("暂停")
                btn.setObjectName("GoalPauseBtn")
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(
                    lambda _c=False, tid=task.id: self._on_goal_pause(tid)
                )
                self.goal_detail_btn_lay.addWidget(btn)
                if task.subtasks and task.current_subtask() is None:
                    first_leaf = next(
                        (leaf for leaf in task.iter_leaves() if not leaf.done),
                        None,
                    )
                    if first_leaf is not None:
                        btn_start = QPushButton("开始运行")
                        btn_start.setObjectName("GoalResumeBtn")
                        btn_start.setCursor(Qt.PointingHandCursor)
                        btn_start.setToolTip("聚焦第一个未完成的子目标")
                        leaf_tid = task.id
                        leaf_sid = first_leaf.id
                        btn_start.clicked.connect(
                            lambda _c=False, tid=leaf_tid, sid=leaf_sid: (
                                self._on_sub_focus(tid, sid)
                            )
                        )
                        self.goal_detail_btn_lay.addWidget(btn_start)

            complete_style = (
                "Primary" if task.status == TaskStatus.ACTIVE else "Ghost"
            )
            btn_complete = QPushButton("完成目标")
            btn_complete.setObjectName(complete_style)
            btn_complete.setCursor(Qt.PointingHandCursor)
            btn_complete.clicked.connect(
                lambda _c=False, tid=task.id: self._on_goal_complete(tid)
            )
            self.goal_detail_btn_lay.addWidget(btn_complete)

            btn_del = QPushButton("删除")
            btn_del.setObjectName("Danger")
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.clicked.connect(
                lambda _c=False, tid=task.id: self._on_goal_delete(tid)
            )
            self.goal_detail_btn_lay.addWidget(btn_del)

        elif (
            sub is not None
            and task.status != TaskStatus.COMPLETED
        ):
            sid = sub.id
            callbacks = SubtaskActionCallbacks(
                on_claim=lambda tid=task.id, s=sid: self._on_sub_claim(tid, s),
                on_focus=lambda tid=task.id, s=sid: self._on_sub_focus(tid, s),
                on_pause=lambda tid=task.id: self._on_sub_pause(tid),
                on_complete=lambda tid=task.id, s=sid: self._on_sub_complete(tid, s),
                on_decompose=lambda tid=task.id, s=sid: self._on_decompose(tid, s),
                on_delete=lambda tid=task.id, s=sid: self._on_sub_delete(tid, s),
                on_add_child=lambda s=sid: self._on_sub_add_child(s),
            )
            append_subtask_detail_actions(
                self.goal_detail_btn_lay,
                sub,
                task_status=task.status,
                current_id=task.current_subtask_id,
                callbacks=callbacks,
            )

        self.goal_detail_btn_lay.addStretch(1)

        # 统一按钮高度：不同选中状态按钮组高度不同时，行高变化会改变
        # 详情面板的最小高度，进而把悬浮窗顶高
        row_h = self._detail_btn_row_height()
        for i in range(self.goal_detail_btn_lay.count()):
            item = self.goal_detail_btn_lay.itemAt(i)
            if item is not None and isinstance(item.widget(), QPushButton):
                item.widget().setFixedHeight(row_h)

    def _detail_btn_row_height(self) -> int:
        """详情面板按钮固定高度（含 QSS padding 与边框）。"""
        return 30

    def _apply_tree_selection_ui(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
    ) -> None:
        self._apply_tree_selection_chrome()
        self._refresh_tree_labels(
            since_gold=since_gold,
            since_diamond=since_diamond,
            stats_only=False,
        )
        self._refresh_goal_detail_panel(
            since_gold=since_gold,
            since_diamond=since_diamond,
        )

    def _on_tree_select(
        self,
        task_id: str,
        subtask_id: str = "",
        *,
        sub: Subtask | None = None,
        editable: bool = False,
    ) -> None:
        self._selected_task_id = task_id
        self._selected_subtask_id = subtask_id
        since = self.state.since_roll
        self._apply_tree_selection_ui(
            since_gold=since.gold,
            since_diamond=since.diamond,
        )

    def _make_goal_root_row(
        self,
        task: Task,
        *,
        selected: bool = False,
    ) -> tuple[TreeRow, QLabel]:
        is_running = task.status == TaskStatus.ACTIVE
        goal_expanded = self._is_goal_expanded(task.id)
        row = TreeRow()
        row.setObjectName("GoalRootRow")
        row.setCursor(Qt.PointingHandCursor)
        row.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        apply_goal_root_row_state(row, is_running=is_running)
        row.set_row_selected(selected)

        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(4, 3, 4, 3)
        row_lay.setSpacing(4)

        has_children = bool(task.subtasks) or is_running
        if has_children:
            btn_fold = QPushButton("v" if goal_expanded else ">")
            btn_fold.setObjectName("TreeFoldBtn")
            btn_fold.setCursor(Qt.PointingHandCursor)
            btn_fold.setFixedSize(18, 18)
            btn_fold.clicked.connect(
                lambda _c=False, tid=task.id: self._on_goal_toggle_fold(tid)
            )
            row_lay.addWidget(btn_fold, 0, Qt.AlignVCenter)

        line = QLabel(
            format_goal_root_line_html(
                task,
                selected=selected,
                is_running=is_running,
                muted=task.status == TaskStatus.PAUSED,
            )
        )
        line.setObjectName("TaskTitle")
        line.setWordWrap(False)
        line.setTextFormat(Qt.RichText)
        line.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        row_lay.addWidget(line, 0)
        self._pin_tree_label_width(line)

        row.selected.connect(
            lambda tid=task.id: self._on_tree_select(tid, editable=False)
        )
        row.style().unpolish(row)
        row.style().polish(row)
        return row, line

    def _make_tree_node_row(
        self,
        task: Task,
        sub: Subtask,
        *,
        depth: int,
        selected: bool,
        is_current: bool,
        editable: bool,
    ) -> tuple[TreeRow, QLabel]:
        row = TreeRow()
        row.setObjectName("TreeNodeRow")
        row.setCursor(Qt.PointingHandCursor)
        row.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        if depth > 0:
            row.setProperty("nested", True)
        row.set_row_selected(selected)

        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(4, 3, 4, 3)
        row_lay.setSpacing(4)

        if sub.is_container():
            expanded = self.manager.is_subtask_expanded(task.id, sub.id)
            btn_fold = QPushButton("v" if expanded else ">")
            btn_fold.setObjectName("TreeFoldBtn")
            btn_fold.setCursor(Qt.PointingHandCursor)
            btn_fold.setFixedSize(18, 18)
            btn_fold.clicked.connect(
                lambda _c=False, tid=task.id, sid=sub.id: self._on_sub_toggle_fold(
                    tid, sid
                )
            )
            row_lay.addWidget(btn_fold, 0, Qt.AlignVCenter)

        show_stats = selected or is_current
        line = QLabel(
            format_tree_node_html(
                sub,
                selected=selected,
                is_current=is_current,
                expanded=self.manager.is_subtask_expanded(task.id, sub.id),
                show_stats=show_stats,
            )
        )
        line.setObjectName("SubGoalList")
        line.setWordWrap(False)
        line.setTextFormat(Qt.RichText)
        line.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        row_lay.addWidget(line, 0)
        self._pin_tree_label_width(line)

        callbacks = SubtaskActionCallbacks(
            on_claim=lambda tid=task.id, sid=sub.id: self._on_sub_claim(tid, sid),
            on_focus=lambda tid=task.id, sid=sub.id: self._on_sub_focus(tid, sid),
            on_pause=lambda tid=task.id: self._on_sub_pause(tid),
            on_complete=lambda tid=task.id, sid=sub.id: self._on_sub_complete(tid, sid),
            on_decompose=lambda tid=task.id, sid=sub.id: self._on_decompose(tid, sid),
            on_delete=lambda tid=task.id, sid=sub.id: self._on_sub_delete(tid, sid),
            on_add_child=lambda sid=sub.id: self._on_sub_add_child(sid),
        )
        actions = build_subtask_action_buttons(
            sub,
            task_status=task.status,
            current_id=task.current_subtask_id,
            callbacks=callbacks,
            parent=row,
        )
        row.set_actions_widget(actions)
        row_lay.addWidget(actions, 0, Qt.AlignVCenter)
        row.set_row_focused(is_current)

        row.selected.connect(
            lambda s=sub, tid=task.id, e=editable: self._on_tree_select(
                tid, s.id, sub=s, editable=e
            )
        )
        row.style().unpolish(row)
        row.style().polish(row)
        return row, line

    def _task_tree_structure_signature(self) -> tuple:
        """仅布局/结构相关字段；选中、聚焦、统计变化不触发整树重建。"""
        parts: list[tuple] = []
        for task in self._widget_goals():
            expanded = frozenset(self.manager.expanded_subtask_ids(task.id))
            if self._is_goal_expanded(task.id):
                sub_part = tuple(
                    (
                        s.id,
                        s.title,
                        s.done,
                        s.rewards_claimed,
                        s.is_container(),
                    )
                    for _, s in self.manager.iter_visible_subtasks(task)
                )
            else:
                sub_part = ()
            parts.append((
                task.id,
                task.title,
                task.status,
                expanded,
                sub_part,
            ))
        return (frozenset(self._expanded_goal_ids), tuple(parts))

    def _refresh_task_tree_section(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
    ) -> None:
        sig = self._task_tree_structure_signature()
        if sig != self._subgoal_structure_sig:
            self._rebuild_task_tree(
                since_gold=since_gold,
                since_diamond=since_diamond,
            )
        else:
            self._update_task_tree_lines(
                since_gold=since_gold,
                since_diamond=since_diamond,
            )

    def _update_task_tree_lines(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
    ) -> None:
        active = self.state.active_task()
        focus_hint = ""
        if active is not None and active.status == TaskStatus.ACTIVE:
            focus_hint = format_subgoals_focus_hint_html(active)
        if focus_hint:
            self.subgoals_hint.setTextFormat(Qt.RichText)
            self._set_html(self.subgoals_hint, focus_hint)
            self.subgoals_hint.show()
        else:
            self.subgoals_hint.hide()

        self._apply_tree_selection_chrome()
        self._refresh_task_ops_ui(
            since_gold=since_gold,
            since_diamond=since_diamond,
        )
        self._sync_subgoals_container_geometry(remeasure=True)

    def _rebuild_task_tree(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
    ) -> None:
        self._clear_tree_layout()
        self._subgoal_line_labels.clear()
        self._tree_row_widgets.clear()
        self._subgoal_structure_sig = None

        goals = self._widget_goals()
        if not goals:
            self.subgoals_scroll.hide()
            self.subgoals_hbar.hide()
            self.subgoals_hint.hide()
            self.subgoals_empty.setText("还没有目标")
            self.subgoals_empty.show()
            return

        self.subgoals_empty.hide()
        self.subgoals_scroll.show()

        if self._selected_task_id:
            if not any(t.id == self._selected_task_id for t in goals):
                self._selected_task_id = ""
                self._selected_subtask_id = ""
            elif self._selected_subtask_id:
                task = self.manager.get(self._selected_task_id)
                if task is None or task.find_subtask(self._selected_subtask_id) is None:
                    self._selected_subtask_id = ""

        active = self.state.active_task()
        focus_hint = ""
        if active is not None and active.status == TaskStatus.ACTIVE:
            focus_hint = format_subgoals_focus_hint_html(active)
        if focus_hint:
            self.subgoals_hint.setTextFormat(Qt.RichText)
            self._set_html(self.subgoals_hint, focus_hint)
            self.subgoals_hint.show()
        else:
            self.subgoals_hint.hide()

        for task in goals:
            is_running = task.status == TaskStatus.ACTIVE
            editable = is_running
            goal_expanded = self._is_goal_expanded(task.id)
            root_selected = (
                task.id == self._selected_task_id and not self._selected_subtask_id
            )

            block = QWidget()
            block.setObjectName("GoalBlock")
            block.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(0, 0, 0, 0)
            block_layout.setSpacing(0)

            root_row, root_line = self._make_goal_root_row(
                task,
                selected=root_selected,
            )
            self._goal_root_rows[task.id] = root_row
            self._goal_root_lines[task.id] = root_line
            block_layout.addWidget(root_row)

            if goal_expanded:
                active_path = task.active_focus_path_ids() if editable else frozenset()

                if not task.subtasks and is_running:
                    hint = QLabel("添加目标后开始累计奖励")
                    hint.setObjectName("SubGoalList")
                    hint.setWordWrap(True)
                    hint.setContentsMargins(22, 0, 4, 0)
                    block_layout.addWidget(hint)
                else:
                    for depth, sub in self.manager.iter_visible_subtasks(task):
                        key = self._sub_line_key(task.id, sub.id)
                        row, line = self._make_tree_node_row(
                            task,
                            sub,
                            depth=depth + 1,
                            selected=(
                                task.id == self._selected_task_id
                                and sub.id == self._selected_subtask_id
                            ),
                            is_current=sub.id in active_path,
                            editable=editable,
                        )
                        self._subgoal_line_labels[key] = line
                        self._tree_row_widgets[key] = row

                        sub_block = QWidget()
                        sub_block.setObjectName("SubtaskBlock")
                        sub_block.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
                        apply_subtask_block_ui(
                            sub_block,
                            selected=(
                                task.id == self._selected_task_id
                                and sub.id == self._selected_subtask_id
                            ),
                            focused=sub.id in active_path,
                        )
                        sub_block_layout = QVBoxLayout(sub_block)
                        sub_block_layout.setContentsMargins(0, 0, 0, 0)
                        sub_block_layout.setSpacing(0)
                        sub_block_layout.addWidget(row)
                        self._subtask_blocks[key] = sub_block

                        indent_wrap = QWidget()
                        indent_wrap.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
                        indent_lay = QHBoxLayout(indent_wrap)
                        indent_lay.setContentsMargins(
                            (depth + 1) * SUBGOAL_INDENT_PX,
                            0,
                            0,
                            0,
                        )
                        indent_lay.setSpacing(0)
                        indent_lay.addWidget(sub_block)
                        block_layout.addWidget(indent_wrap)

            self._goal_blocks[task.id] = block
            self.subgoals_layout.addWidget(block, 0, Qt.AlignLeft)

        for task in goals:
            block = self._goal_blocks.get(task.id)
            if block is not None:
                goal_selected = (
                    task.id == self._selected_task_id
                    and not self._selected_subtask_id
                )
                apply_goal_block_ui(
                    block,
                    is_running=task.status == TaskStatus.ACTIVE,
                    selected=goal_selected,
                    focused=bool(task.active_focus_path_ids()),
                )

        for task_id, block in self._goal_blocks.items():
            self._install_goal_hover_filters(block)

        self.subgoals_layout.addStretch(1)
        self._subgoal_structure_sig = self._task_tree_structure_signature()
        self._apply_tree_selection_ui(
            since_gold=since_gold,
            since_diamond=since_diamond,
        )
        self._sync_subgoals_container_geometry(remeasure=True)

    def _on_decompose(self, task_id: str, subtask_id: str) -> None:
        text, ok = QInputDialog.getText(
            self,
            "分解目标",
            "子项名称（多个用逗号分隔）：",
            text="子项1, 子项2",
        )
        if not ok:
            return
        titles = [p.strip() for p in text.replace("，", ",").split(",") if p.strip()]
        if not titles:
            return
        if self.manager.decompose_subtask(task_id, subtask_id, titles):
            self._selected_task_id = task_id
            self._selected_subtask_id = subtask_id
            self._reveal_subtask_path(task_id, subtask_id)
            self._request_state_sync()

    def _confirm_subgoal_delete(self, sub: Subtask, *, has_rewards: bool) -> bool:
        if has_rewards:
            text = f"「{sub.title}」有未领取奖励，确定删除吗？"
        else:
            text = f"确定删除「{sub.title}」吗？"
        return ask_yes_no(self, "删除目标", text)

    def _update_action_visibility(self, active: Task | None) -> None:
        if not self._selected_task_id:
            if active is not None:
                self._selected_task_id = active.id
            else:
                for task in self._widget_goals():
                    if task.status != TaskStatus.COMPLETED:
                        self._selected_task_id = task.id
                        break

        show_add = False
        if active is not None and active.status != TaskStatus.COMPLETED:
            show_add = True
        elif self._selected_task_id:
            task = self.manager.get(self._selected_task_id)
            show_add = task is not None and task.status != TaskStatus.COMPLETED
        self.subgoal_actions.setVisible(show_add)

        if not self._selected_task_id:
            self.goal_detail_panel.hide()
            return
        task = self.manager.get(self._selected_task_id)
        if task is None:
            self.goal_detail_panel.hide()
            return
        since = self.state.since_roll
        self._refresh_goal_detail_panel(
            since_gold=since.gold,
            since_diamond=since.diamond,
        )

    def _paused_tasks(self) -> list[Task]:
        return self.manager.by_status(TaskStatus.PAUSED)

    def _on_goal_pause(self, task_id: str) -> None:
        task = self.manager.get(task_id)
        if task is None or task.status != TaskStatus.ACTIVE:
            return
        self.manager.pause(task_id)
        self._request_state_sync()

    def _on_goal_resume(self, task_id: str) -> None:
        t = self.manager.resume(task_id)
        if t is None or t.status != TaskStatus.ACTIVE:
            return
        sub = t.current_subtask()
        if sub is not None:
            self._selected_task_id = task_id
            self._selected_subtask_id = sub.id
            self._reveal_subtask_path(task_id, sub.id)
        self._request_state_sync()

    def _on_goal_complete(self, task_id: str) -> None:
        if try_complete_goal(self, self.manager, task_id):
            self._request_state_sync()

    def _on_goal_delete(self, task_id: str) -> None:
        if try_delete_goal(self, self.manager, task_id):
            if self._selected_task_id == task_id:
                self._selected_task_id = ""
                self._selected_subtask_id = ""
            self._request_state_sync()

    def _on_sub_toggle_fold(self, task_id: str, subtask_id: str) -> None:
        if self.manager.toggle_subtask_expand(task_id, subtask_id):
            self._request_local_refresh()

    def _on_sub_focus(self, task_id: str, subtask_id: str) -> None:
        if self.manager.start_subtask(task_id, subtask_id):
            self._reveal_subtask_path(task_id, subtask_id)
            self._request_state_sync()

    def _on_sub_pause(self, task_id: str) -> None:
        task = self.manager.get(task_id)
        if task is None or task.status != TaskStatus.ACTIVE:
            return
        self.manager.pause(task_id)
        self._request_state_sync()

    def _on_sub_complete(self, task_id: str, subtask_id: str) -> None:
        task = self.manager.get(task_id)
        if task is None or task.status == TaskStatus.COMPLETED:
            return
        sub = task.find_subtask(subtask_id)
        if sub is None:
            return
        reward = self.manager.complete_and_claim_subtask(task_id, subtask_id)
        if reward is not None:
            self.subtask_claimed.emit(sub.title, reward)
        self._request_state_sync()

    def _on_sub_claim(self, task_id: str, subtask_id: str) -> None:
        task = self.manager.get(task_id)
        if task is None or task.status == TaskStatus.COMPLETED:
            return
        sub = task.find_subtask(subtask_id)
        if sub is None:
            return
        reward = self.manager.complete_and_claim_subtask(task_id, subtask_id)
        if reward is not None:
            self.subtask_claimed.emit(sub.title, reward)
        self._request_state_sync()

    def _subtree_has_unclaimed(self, sub: Subtask) -> bool:
        for node in sub.iter_subtree():
            if node.rewards_claimed:
                continue
            if node.is_claimable() or node.pending_rewards:
                return True
        return False

    def _on_sub_delete(self, task_id: str, subtask_id: str) -> None:
        task = self.manager.get(task_id)
        if task is None or task.status == TaskStatus.COMPLETED:
            return
        sub = task.find_subtask(subtask_id)
        if sub is None:
            return
        if self._subtree_has_unclaimed(sub):
            if not self._confirm_subgoal_delete(sub, has_rewards=True):
                return
        elif not sub.done and (
            sub.pending_rewards
            or sub.rollup_operations() > 0
            or sub.children
        ):
            if not self._confirm_subgoal_delete(sub, has_rewards=False):
                return
        if not self.manager.delete_subtask(task_id, subtask_id):
            return
        if self._selected_subtask_id == subtask_id:
            self._selected_subtask_id = ""
        if self._sub_add_parent_id == subtask_id:
            self._sub_add_parent_id = None
            self._update_subgoal_add_hint()
        self._request_state_sync()

    def _update_subgoal_add_hint(self) -> None:
        if self._sub_add_parent_id:
            active = self.state.active_task()
            parent = active.find_subtask(self._sub_add_parent_id) if active else None
            if parent is not None:
                self.subgoal_input.setPlaceholderText(f"添加到「{parent.title}」下…")
                self.subgoal_add_context.setText(
                    f"正在向「{parent.title}」添加子目标"
                )
                self.subgoal_add_context.show()
                self.sub_add_btn.setText("添加子项")
                return
            self._sub_add_parent_id = None
        self.subgoal_input.setPlaceholderText("子目标标题…（根级）")
        self.subgoal_add_context.hide()
        self.sub_add_btn.setText("添加")

    def _on_sub_add_child(self, parent_subtask_id: str) -> None:
        task = self._subgoal_target_task()
        if task is None:
            return
        if task.find_subtask(parent_subtask_id) is None:
            return
        self._sub_add_parent_id = parent_subtask_id
        self._update_subgoal_add_hint()
        self.subgoal_input.setFocus()
        self.subgoal_input.selectAll()

    def _on_subtask_min_changed(self, value: int) -> None:
        self.state.settings["subtask_default_target_minutes"] = max(1, int(value))
        save_state(self.state)

    def _subgoal_target_task(self) -> Task | None:
        """添加子目标所作用的目标：优先当前选中，否则进行中目标。"""
        if self._selected_task_id:
            task = self.manager.get(self._selected_task_id)
            if task is not None and task.status != TaskStatus.COMPLETED:
                return task
        return self.state.active_task()

    def _on_add_subgoal(self) -> None:
        task = self._subgoal_target_task()
        if task is None:
            return
        title = self.subgoal_input.text().strip()
        if not title:
            return
        target_minutes = self.subgoal_min_spin.value()
        self.state.settings["subtask_default_target_minutes"] = target_minutes
        sub = self.manager.add_subtask(
            task.id,
            title,
            target_minutes=target_minutes,
            parent_subtask_id=self._sub_add_parent_id,
        )
        if sub is None:
            return
        self._selected_task_id = task.id
        self._selected_subtask_id = sub.id
        self._reveal_subtask_path(task.id, sub.id)
        self.subgoal_input.clear()
        self._sub_add_parent_id = None
        self._update_subgoal_add_hint()
        self._request_state_sync()

    def _on_add_goal(self) -> None:
        title, ok = QInputDialog.getText(self, "新建目标", "目标标题：")
        if not ok:
            return
        title = title.strip()
        if not title:
            return
        self.manager.create(title)
        self._request_state_sync()

    def _refresh_task_actions(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
    ) -> None:
        self._refresh_task_tree_section(
            since_gold=since_gold,
            since_diamond=since_diamond,
        )

    def _apply_task_section(
        self,
        active: Task | None,
        *,
        since_gold: float,
        since_diamond: float,
    ) -> None:
        self._sync_expanded_goals(active)
        self._refresh_task_tree_section(
            since_gold=since_gold,
            since_diamond=since_diamond,
        )
        self._update_action_visibility(active)

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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(
            0,
            lambda: self._sync_subgoals_container_geometry(remeasure=True),
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

        since = self.state.since_roll
        self._apply_tree_selection_chrome()
        self._refresh_task_ops_ui(
            since_gold=since.gold,
            since_diamond=since.diamond,
        )

    def nativeEvent(self, eventType, message):
        self.manager.power_monitor.handle_native_event(eventType, message)
        return super().nativeEvent(eventType, message)

    # ---------- 显示时初始化窗口属性 ----------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.manager.power_monitor.install_on(self)
        if self.state.settings.get("pin_all_desktops", True):
            pin_window_to_all_desktops(int(self.winId()))
