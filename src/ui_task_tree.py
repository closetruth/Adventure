"""目标树 UI 共享常量、行组件与行尾操作。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .models import Subtask, TaskStatus

TREE_INDENT_PX = 24

TREE_QSS = """
QWidget#TreeNodeRow,
QFrame#TreeNodeRow {
    background-color: transparent;
    border: none;
    border-radius: 3px;
}
QWidget#TreeNodeRow:hover,
QFrame#TreeNodeRow:hover {
    background-color: rgba(255, 255, 255, 0.08);
}
QWidget#TreeNodeRow[selected="true"],
QFrame#TreeNodeRow[selected="true"] {
    background-color: transparent;
}
QWidget#TreeNodeRow[current="true"],
QFrame#TreeNodeRow[current="true"] {
    background-color: transparent;
    border: none;
    border-radius: 3px;
}
QWidget#SubtaskBlock {
    background-color: transparent;
    border: none;
    border-radius: 4px;
    margin: 2px 0;
    padding: 3px 6px;
}
QWidget#SubtaskBlock[selected="true"] {
    border: 2px solid #7eb4ff;
    background-color: transparent;
}
QWidget#GoalBlock {
    background-color: transparent;
    border: none;
    border-radius: 6px;
    margin: 3px 0;
    padding: 4px 6px;
}
QWidget#GoalBlock[hovered="true"] {
    background-color: rgba(255, 255, 255, 0.06);
}
QWidget#GoalBlock[selected="true"] {
    border: 2px solid #7eb4ff;
    background-color: transparent;
}
QWidget#GoalRootRow,
QFrame#GoalRootRow {
    background-color: transparent;
    border: none;
    border-radius: 3px;
}
QWidget#GoalRootRow:hover,
QFrame#GoalRootRow:hover {
    background-color: rgba(255, 255, 255, 0.06);
}
QWidget#GoalRootRow[selected="true"],
QFrame#GoalRootRow[selected="true"] {
    background-color: transparent;
}
QWidget#GoalRootRow[current="true"],
QFrame#GoalRootRow[current="true"],
QWidget#GoalRootRow[paused="true"],
QFrame#GoalRootRow[paused="true"] {
    background-color: transparent;
    border: none;
}
QLabel#StatusBadge {
    font-size: 10px;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 4px;
}
QLabel#StatusBadge[status="active"] {
    background: rgba(110, 231, 160, 0.14);
    color: #6ee7a0;
    border: 1px solid rgba(110, 231, 160, 0.35);
}
QLabel#StatusBadge[status="paused"] {
    background: rgba(245, 200, 66, 0.12);
    color: #f5c842;
    border: 1px solid rgba(245, 200, 66, 0.35);
}
QLabel#StatusBadge[status="completed"] {
    background: rgba(94, 200, 242, 0.12);
    color: #5ec8f2;
    border: 1px solid rgba(94, 200, 242, 0.35);
}
QPushButton#TreeFoldBtn {
    background: transparent;
    border: none;
    color: #e8ecf4;
    font-size: 11px;
    font-weight: 700;
    min-width: 18px;
    max-width: 18px;
    min-height: 18px;
    padding: 0;
}
QWidget#TreeActions {
    background: transparent;
}
QPushButton#TreeActionBtn {
    background: transparent;
    border: none;
    color: #b8c0d4;
    font-size: 12px;
    font-weight: 700;
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
    padding: 0;
}
QPushButton#TreeActionBtn:hover {
    color: #e8eaf0;
    background-color: rgba(255, 255, 255, 0.08);
    border-radius: 4px;
}
QPushButton#TreeActionBtn[primary="true"] {
    color: #7eb4ff;
}
"""

# 兼容旧引用
TREE_DETAIL_QSS = TREE_QSS


def apply_subtask_block_ui(
    block: QWidget,
    *,
    selected: bool,
    focused: bool,
) -> None:
    """设置子目标块选中/聚焦 QSS 属性。"""
    block.setProperty("selected", selected)
    block.setProperty("focused", focused)
    block.style().unpolish(block)
    block.style().polish(block)


def apply_goal_block_hover(block: QWidget, *, hovered: bool) -> None:
    """设置目标块悬停 QSS 属性。"""
    block.setProperty("hovered", hovered)
    block.style().unpolish(block)
    block.style().polish(block)


def apply_goal_block_ui(
    block: QWidget,
    *,
    is_running: bool,
    selected: bool,
    focused: bool,
) -> None:
    """设置目标块运行/选中/子目标聚焦 QSS 属性。"""
    block.setProperty("current", is_running)
    block.setProperty("paused", not is_running)
    block.setProperty("selected", selected)
    block.setProperty("focused", focused)
    block.style().unpolish(block)
    block.style().polish(block)


def apply_goal_block_state(block: QWidget, *, is_running: bool) -> None:
    """设置目标块容器的运行/暂停 QSS 属性。"""
    apply_goal_block_ui(
        block,
        is_running=is_running,
        selected=block.property("selected") or False,
        focused=block.property("focused") or False,
    )


def apply_goal_block_selection(block: QWidget, *, selected: bool) -> None:
    """设置目标块选中描边（四边边框高亮）。"""
    apply_goal_block_ui(
        block,
        is_running=block.property("current") or False,
        selected=selected,
        focused=block.property("focused") or False,
    )


def apply_goal_root_row_state(row: QWidget, *, is_running: bool) -> None:
    """设置目标根行属性（块级高亮由 GoalBlock 承担，根行保持透明）。"""
    row.setProperty("current", is_running)
    row.setProperty("paused", not is_running)
    row.style().unpolish(row)
    row.style().polish(row)


def make_goal_status_badge(status: TaskStatus) -> QLabel:
    text = {
        TaskStatus.ACTIVE: "进行中",
        TaskStatus.PAUSED: "已暂停",
        TaskStatus.COMPLETED: "已完成",
    }.get(status, str(status))
    badge = QLabel(text)
    badge.setObjectName("StatusBadge")
    badge.setProperty("status", status.value)
    badge.style().unpolish(badge)
    badge.style().polish(badge)
    return badge


@dataclass
class SubtaskActionCallbacks:
    """子目标行尾操作回调。"""

    on_claim: Optional[Callable[[], None]] = None
    on_pause: Optional[Callable[[], None]] = None
    on_complete: Optional[Callable[[], None]] = None
    on_add_child: Optional[Callable[[], None]] = None
    on_more: Optional[Callable[[QPoint], None]] = None


def _make_action_btn(
    text: str,
    *,
    tooltip: str = "",
    primary: bool = False,
    parent: QWidget | None = None,
) -> QPushButton:
    btn = QPushButton(text, parent)
    btn.setObjectName("TreeActionBtn")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedSize(20, 20)
    if primary:
        btn.setProperty("primary", True)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def build_subtask_action_buttons(
    sub: Subtask,
    *,
    editable: bool,
    current_id: Optional[str],
    callbacks: SubtaskActionCallbacks,
    parent: QWidget | None = None,
) -> QWidget:
    """构建 VS Code 风行尾操作区（默认隐藏，由 TreeRow hover/selected 控制）。"""
    wrap = QWidget(parent)
    wrap.setObjectName("TreeActions")
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    if not editable:
        wrap.hide()
        return wrap

    is_current = sub.id == current_id and not sub.done

    if sub.can_claim_pending() or sub.is_claimable():
        if callbacks.on_claim is not None:
            btn = _make_action_btn("↓", tooltip="领取", primary=True, parent=wrap)
            btn.clicked.connect(callbacks.on_claim)
            lay.addWidget(btn)

    if sub.is_leaf() and not sub.done and not sub.rewards_claimed:
        if is_current:
            if callbacks.on_pause is not None:
                btn = _make_action_btn("||", tooltip="暂停聚焦", parent=wrap)
                btn.clicked.connect(callbacks.on_pause)
                lay.addWidget(btn)
            if sub.time_target_met() and callbacks.on_complete is not None:
                btn = _make_action_btn("v", tooltip="完成", parent=wrap)
                btn.clicked.connect(callbacks.on_complete)
                lay.addWidget(btn)

    if sub.is_container() and not sub.is_claimable():
        if not (sub.done and sub.rewards_claimed) and callbacks.on_add_child is not None:
            btn = _make_action_btn("+", tooltip="添加子项", parent=wrap)
            btn.clicked.connect(callbacks.on_add_child)
            lay.addWidget(btn)

    if callbacks.on_more is not None and not (sub.done and sub.rewards_claimed):
        btn = _make_action_btn("...", tooltip="更多", parent=wrap)
        btn.clicked.connect(
            lambda _c=False, b=btn: callbacks.on_more(b.mapToGlobal(QPoint(0, b.height())))
        )
        lay.addWidget(btn)

    wrap.setVisible(False)
    return wrap


class TreeRow(QWidget):
    """可单击选中的树行；悬停/选中时显示行尾操作。"""

    selected = Signal()
    activated = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._actions_widget: QWidget | None = None
        self._selected: bool = False
        self.setAttribute(Qt.WA_Hover, True)

    def set_actions_widget(self, widget: QWidget) -> None:
        self._actions_widget = widget
        self._sync_actions_visible()

    def set_row_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self._sync_actions_visible()

    def _sync_actions_visible(self) -> None:
        if self._actions_widget is None:
            return
        lay = self._actions_widget.layout()
        has_buttons = lay is not None and lay.count() > 0
        hovered = self.underMouse()
        self._actions_widget.setVisible(has_buttons and (self._selected or hovered))

    def enterEvent(self, event) -> None:
        self._sync_actions_visible()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._sync_actions_visible()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            child = self.childAt(event.position().toPoint())
            while child is not None and child is not self:
                if isinstance(child, QPushButton):
                    super().mousePressEvent(event)
                    return
                child = child.parentWidget()
            self.selected.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            child = self.childAt(event.position().toPoint())
            while child is not None and child is not self:
                if isinstance(child, QPushButton):
                    super().mouseDoubleClickEvent(event)
                    return
                child = child.parentWidget()
            self.selected.emit()
            self.activated.emit()
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        if hasattr(self, "_show_context_menu") and callable(self._show_context_menu):
            self._show_context_menu(event.globalPos())
        else:
            super().contextMenuEvent(event)
