"""目标管理对话框：创建 / 暂停 / 恢复 / 完成 / 删除目标。"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .models import AppState, Subtask, Task, TaskStatus
from .task_manager import TaskManager
from .ui_styles import DARK_BASE_QSS
from .ui_task_tree import (
    TREE_DETAIL_QSS,
    TREE_INDENT_PX,
    SubtaskActionCallbacks,
    TreeRow,
    apply_goal_root_row_state,
    build_subtask_action_buttons,
    make_goal_status_badge,
)
from .ui_text import (
    format_duration,
    format_goal_root_line_html,
    format_reward_gain,
    format_tree_node_html,
)


SUBTASK_INDENT_PX = TREE_INDENT_PX

DIALOG_STYLESHEET = DARK_BASE_QSS + """
QTabWidget::pane {
    background: #1a1b24;
    border: 1px solid #2a2d38;
    border-radius: 10px;
    top: -1px;
    padding: 8px;
}
QTabBar::tab {
    background: transparent;
    color: #8b93a8;
    padding: 8px 16px;
    border-radius: 8px;
    margin-right: 6px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background: #252833;
    color: #e8eaf0;
    border: 1px solid #3a3f52;
}
QTabBar::tab:hover:!selected { color: #c8ceda; background: #1e1f28; }
QLineEdit#SubtaskInput { padding: 6px 8px; font-size: 12px; }
QSpinBox#SubtaskOps { padding: 4px 6px; font-size: 12px; }
QPushButton#SubtaskClaim {
    background-color: #3a5cff;
    border-color: #3a5cff;
    padding: 4px 12px;
    font-size: 12px;
}
QPushButton#SubtaskClaim:hover { background-color: #4d6dff; }
QPushButton#SubtaskDel {
    background: #252833;
    border: 1px solid #503838;
    color: #a87070;
    padding: 2px 8px;
    min-width: 24px;
    font-size: 14px;
    border-radius: 6px;
}
QPushButton#SubtaskDel:hover { color: #ffb0b0; background: #302525; }
QPushButton#SubtaskFold {
    background: #252833;
    border: 1px solid #404558;
    color: #c8ceda;
    padding: 2px 6px;
    min-width: 24px;
    font-size: 12px;
    font-weight: 700;
    border-radius: 6px;
}
QPushButton#SubtaskFold:hover { background: #303448; }
QCheckBox#SubtaskCheck { spacing: 0; }
QCheckBox#SubtaskCheck::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid #4a5068; background: #12141a;
}
QCheckBox#SubtaskCheck::indicator:checked {
    background: #3a5cff; border-color: #3a5cff;
}
QCheckBox#SubtaskCheck:disabled::indicator { border-color: #333848; background: #1a1b24; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QFrame#Card {
    background-color: #1e1f28;
    border: 1px solid #2a2d38;
    border-radius: 12px;
}
QFrame#Card[active="true"] {
    border: 1px solid #3a5080;
    background-color: #1a2030;
}
QFrame#CreateCard {
    background-color: #1a1b24;
    border: 1px solid #2a2d38;
    border-radius: 12px;
}
QFrame#SubtaskRow {
    background-color: #16161e;
    border: 1px solid #2a2d38;
    border-radius: 8px;
}
QFrame#SubtaskRow[nested="true"] {
    border-left: 3px solid #3a4a68;
    background-color: #14161e;
}
QFrame#SubtaskRow[current="true"] {
    background-color: #141c30;
    border-color: #3a5080;
}
QFrame#SubtaskRow[claimable="true"] {
    background-color: #1c1810;
    border-color: #6a5020;
}
QFrame#SubtaskRow[done="true"] { background-color: #16161e; border-color: #252833; }
QFrame#Divider { background-color: #2a2d38; max-height: 1px; min-height: 1px; border: none; }
QLabel#TaskTitle { font-size: 16px; font-weight: 700; color: #f0f2f8; }
QLabel#SectionTitle {
    font-size: 12px; font-weight: 700; color: #8b93a8;
    padding-bottom: 2px;
}
QLabel#SubtaskTitle { font-size: 13px; font-weight: 600; color: #c8ceda; }
QLabel#SubtaskTitle[current="true"] { color: #7eb4ff; }
QLabel#SubtaskTitle[claimable="true"] { color: #f0c040; }
QLabel#SubtaskTitle[done="true"] { color: #6e7588; text-decoration: line-through; }
QLabel#SubtaskMeta { font-size: 11px; color: #6e7588; line-height: 1.35; }
QLabel#SubtaskMark { font-size: 13px; font-weight: 700; min-width: 14px; }
QLabel#Note { color: #9aa0b4; font-size: 12px; line-height: 1.4; }
QLabel#Meta { color: #8b93a8; font-size: 12px; }
QLabel#CreatedMeta { color: #6e7588; font-size: 11px; }
QLabel#EmptyHint { color: #6e7588; font-size: 13px; padding: 40px 20px; }
""" + TREE_DETAIL_QSS


def _make_divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


def _make_section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("SectionTitle")
    return lbl


class TaskCard(QFrame):
    """单个目标卡片。"""

    action = Signal(str, str, str)  # (task_id, action_name, extra)

    def __init__(
        self,
        task: Task,
        *,
        manager: TaskManager,
        default_target_minutes: int = 10,
    ):
        super().__init__()
        self.task = task
        self.manager = manager
        self._default_target_minutes = max(1, default_target_minutes)
        self.setObjectName("Card")
        self.setProperty("active", task.status == TaskStatus.ACTIVE)
        self._subtask_input: Optional[QLineEdit] = None
        self._subtask_minutes_spin: Optional[QSpinBox] = None
        self._sub_add_parent_id: Optional[str] = None
        self._selected_subtask_id: str = ""
        self._build()

    def _editable(self) -> bool:
        return self.task.status != TaskStatus.COMPLETED

    def _on_tree_select(
        self,
        subtask_id: str,
        *,
        sub: Subtask | None = None,
        editable: bool = False,
    ) -> None:
        self._selected_subtask_id = subtask_id
        if (
            editable
            and sub is not None
            and sub.is_leaf()
            and not sub.done
            and not sub.rewards_claimed
        ):
            self.action.emit(self.task.id, "subtask_focus", sub.id)

    def _show_subtask_context_menu(self, sub: Subtask, global_pos) -> None:
        if not self._editable():
            return
        menu = QMenu(self)
        current_id = self.task.current_subtask_id

        if sub.is_leaf() and not sub.done and not sub.rewards_claimed:
            if sub.id == current_id:
                menu.addAction("暂停聚焦", lambda: self.action.emit(
                    self.task.id, "subtask_pause", sub.id,
                ))
            else:
                menu.addAction("开始聚焦", lambda: self.action.emit(
                    self.task.id, "subtask_focus", sub.id,
                ))
            if sub.time_target_met():
                menu.addAction("完成", lambda: self.action.emit(
                    self.task.id, "subtask_confirm_done", sub.id,
                ))
            menu.addAction("分解…", lambda: self._prompt_decompose(sub.id))
            menu.addSeparator()

        if sub.can_claim_pending() or sub.is_claimable():
            menu.addAction("领取", lambda: self.action.emit(
                self.task.id, "subtask_claim", sub.id,
            ))
            menu.addSeparator()

        if not sub.is_claimable() and not (sub.done and sub.rewards_claimed):
            menu.addAction("添加子项", lambda: self._set_sub_add_parent(sub.id))

        if not (sub.done and sub.rewards_claimed):
            menu.addAction("删除", lambda: self.action.emit(
                self.task.id, "subtask_delete", sub.id,
            ))

        if not menu.isEmpty():
            menu.exec(global_pos)

    def _prompt_decompose(self, subtask_id: str) -> None:
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
        self.action.emit(
            self.task.id,
            "subtask_decompose",
            f"{subtask_id}|{','.join(titles)}",
        )

    def _append_tree_node_row(
        self,
        parent_layout: QVBoxLayout,
        sub: Subtask,
        *,
        depth: int,
        editable: bool,
        current_id: Optional[str],
    ) -> None:
        is_current = (
            sub.id == current_id
            and self.task.status == TaskStatus.ACTIVE
            and not sub.done
        )
        selected = sub.id == self._selected_subtask_id
        row = TreeRow()
        row.setObjectName("TreeNodeRow")
        row.setCursor(Qt.PointingHandCursor)
        if depth > 0:
            row.setProperty("nested", True)
        if selected:
            row.setProperty("selected", True)
        if is_current:
            row.setProperty("current", True)

        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(8 + depth * SUBTASK_INDENT_PX, 4, 8, 4)
        row_lay.setSpacing(4)

        expanded = (
            self.manager.is_subtask_expanded(self.task.id, sub.id)
            if sub.is_container()
            else True
        )

        if sub.is_container() and editable:
            btn_fold = QPushButton("v" if expanded else ">")
            btn_fold.setObjectName("TreeFoldBtn")
            btn_fold.setFixedWidth(18)
            btn_fold.clicked.connect(
                lambda _c=False, sid=sub.id: self.action.emit(
                    self.task.id, "subtask_toggle_fold", sid,
                )
            )
            row_lay.addWidget(btn_fold, 0, Qt.AlignVCenter)
        elif sub.is_container():
            mark = QLabel("v" if expanded else ">")
            mark.setFixedWidth(18)
            row_lay.addWidget(mark, 0, Qt.AlignVCenter)

        line = QLabel(
            format_tree_node_html(
                sub,
                selected=selected,
                is_current=is_current,
                expanded=expanded,
                show_stats=selected or is_current,
            )
        )
        line.setObjectName("SubtaskTitle")
        line.setTextFormat(Qt.RichText)
        row_lay.addWidget(line, 1)

        callbacks = SubtaskActionCallbacks(
            on_claim=lambda: self.action.emit(self.task.id, "subtask_claim", sub.id),
            on_pause=lambda: self.action.emit(self.task.id, "subtask_pause", sub.id),
            on_complete=lambda: self.action.emit(
                self.task.id, "subtask_confirm_done", sub.id,
            ),
            on_add_child=lambda: self._set_sub_add_parent(sub.id),
            on_more=lambda pos, s=sub: self._show_subtask_context_menu(s, pos),
        )
        actions = build_subtask_action_buttons(
            sub,
            editable=editable,
            current_id=current_id,
            callbacks=callbacks,
            parent=row,
        )
        row.set_actions_widget(actions)
        row_lay.addWidget(actions, 0, Qt.AlignVCenter)

        row.set_row_selected(selected)
        row.selected.connect(
            lambda s=sub, e=editable: self._on_tree_select(s.id, sub=s, editable=e)
        )
        row._show_context_menu = lambda pos, s=sub: self._show_subtask_context_menu(s, pos)
        row.style().unpolish(row)
        row.style().polish(row)
        parent_layout.addWidget(row)

    def _append_goal_root_row(self, parent_layout: QVBoxLayout) -> None:
        is_running = self.task.status == TaskStatus.ACTIVE
        row = TreeRow()
        row.setObjectName("GoalRootRow")
        row.setCursor(Qt.PointingHandCursor)
        apply_goal_root_row_state(row, is_running=is_running)
        if self._selected_subtask_id == "":
            row.setProperty("selected", True)
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(12, 8, 10, 8)
        row_lay.setSpacing(8)

        title = QLabel(
            format_goal_root_line_html(
                self.task,
                selected=self._selected_subtask_id == "",
                is_running=is_running,
                muted=self.task.status == TaskStatus.PAUSED,
            )
        )
        title.setObjectName("TaskTitle")
        title.setWordWrap(True)
        title.setTextFormat(Qt.RichText)
        row_lay.addWidget(title, 1)
        row_lay.addWidget(make_goal_status_badge(self.task.status), 0, Qt.AlignTop)
        row.selected.connect(lambda: self._on_tree_select("", editable=False))
        row.set_row_selected(self._selected_subtask_id == "")
        row.style().unpolish(row)
        row.style().polish(row)
        parent_layout.addWidget(row)

    def _build_task_tree(self, parent: QVBoxLayout) -> None:
        editable = self._editable()
        current_id = self.task.current_subtask_id

        tree_layout = QVBoxLayout()
        tree_layout.setSpacing(4)
        tree_layout.setContentsMargins(0, 0, 0, 0)

        self._append_goal_root_row(tree_layout)

        if not self.task.subtasks:
            hint = QLabel("添加目标后开始累计奖励")
            hint.setObjectName("Note")
            hint.setWordWrap(True)
            tree_layout.addWidget(hint)
        else:
            for depth, sub in self.manager.iter_visible_subtasks(self.task):
                self._append_tree_node_row(
                    tree_layout,
                    sub,
                    depth=depth + 1,
                    editable=editable,
                    current_id=current_id,
                )

        if tree_layout.count():
            parent.addLayout(tree_layout)

        if editable:
            add_row = QHBoxLayout()
            add_row.setSpacing(6)
            inp = QLineEdit()
            inp.setObjectName("SubtaskInput")
            inp.setPlaceholderText("新目标标题…")
            inp.returnPressed.connect(self._emit_subtask_add)
            self._subtask_input = inp
            add_row.addWidget(inp, 1)
            min_spin = QSpinBox()
            min_spin.setObjectName("SubtaskOps")
            min_spin.setRange(1, 999)
            min_spin.setValue(self._default_target_minutes)
            min_spin.setPrefix("目标 ")
            min_spin.setSuffix(" 分钟")
            min_spin.setToolTip("完成所需时长")
            self._subtask_minutes_spin = min_spin
            add_row.addWidget(min_spin)
            btn_add = QPushButton("添加")
            btn_add.setObjectName("Primary")
            btn_add.clicked.connect(self._emit_subtask_add)
            add_row.addWidget(btn_add)
            parent.addLayout(add_row)

    def _set_sub_add_parent(self, parent_subtask_id: str) -> None:
        self._sub_add_parent_id = parent_subtask_id
        self._selected_subtask_id = parent_subtask_id
        if self._subtask_input is None:
            return
        parent = self.task.find_subtask(parent_subtask_id)
        if parent is not None:
            self._subtask_input.setPlaceholderText(f"添加到「{parent.title}」下…")
        self._subtask_input.setFocus()

    def _emit_subtask_add(self) -> None:
        if self._subtask_input is None:
            return
        title = self._subtask_input.text().strip()
        if not title:
            return
        target_minutes = self._default_target_minutes
        if self._subtask_minutes_spin is not None:
            target_minutes = self._subtask_minutes_spin.value()
        self.action.emit(
            self.task.id,
            "subtask_add",
            f"{title}|{target_minutes}|{self._sub_add_parent_id or ''}",
        )
        self._subtask_input.clear()
        self._sub_add_parent_id = None
        self._subtask_input.setPlaceholderText("新目标标题…")

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)

        if self.task.note:
            note = QLabel(self.task.note)
            note.setObjectName("Note")
            note.setWordWrap(True)
            v.addWidget(note)

        self._build_task_tree(v)

        meta_parts: list[str] = []
        created = time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(self.task.created_at),
        )
        meta_parts.append(f"创建 {created}")
        if self.task.completed_at:
            done = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(self.task.completed_at),
            )
            meta_parts.append(f"完成 {done}")
        duration = format_duration(
            self.task.active_duration_seconds()
            if self.task.status == TaskStatus.ACTIVE
            else self.task.active_seconds
        )
        meta_parts.append(f"累计 {duration}")
        meta = QLabel(" · ".join(meta_parts))
        meta.setObjectName("CreatedMeta")
        meta.setWordWrap(True)

        v.addWidget(_make_divider())
        v.addWidget(meta)

        v.addWidget(_make_divider())
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        if self.task.status == TaskStatus.ACTIVE:
            b_pause = QPushButton("暂停")
            b_pause.setObjectName("Ghost")
            b_pause.clicked.connect(lambda: self.action.emit(self.task.id, "pause", ""))
            btn_row.addWidget(b_pause)
            b_complete = QPushButton("完成目标")
            b_complete.setObjectName("Primary")
            b_complete.clicked.connect(
                lambda: self.action.emit(self.task.id, "complete", "")
            )
            btn_row.addWidget(b_complete)
        elif self.task.status == TaskStatus.PAUSED:
            b_resume = QPushButton("恢复")
            b_resume.setObjectName("Primary")
            b_resume.clicked.connect(
                lambda: self.action.emit(self.task.id, "resume", "")
            )
            btn_row.addWidget(b_resume)
            b_complete = QPushButton("完成目标")
            b_complete.setObjectName("Ghost")
            b_complete.clicked.connect(
                lambda: self.action.emit(self.task.id, "complete", "")
            )
            btn_row.addWidget(b_complete)
        else:
            btn_row.addStretch(1)

        btn_row.addStretch(1)
        b_del = QPushButton("删除")
        b_del.setObjectName("Danger")
        b_del.clicked.connect(lambda: self.action.emit(self.task.id, "delete", ""))
        btn_row.addWidget(b_del)
        v.addLayout(btn_row)

    def update_stats(self) -> None:
        """卡片重建前占位；统计由行内展示。"""
        return

class TaskDialog(QDialog):
    """目标管理主对话框。"""

    state_changed = Signal()
    subtask_claimed = Signal(str, object)  # (title, Reward)

    def __init__(self, state: AppState, manager: TaskManager, parent=None):
        super().__init__(parent)
        self.state = state
        self.manager = manager

        self.setWindowTitle("目标管理 - Adventure")
        self.resize(540, 640)
        self.setStyleSheet(DIALOG_STYLESHEET)
        self._build()
        self.refresh()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)

        create_box = QFrame()
        create_box.setObjectName("CreateCard")
        cl = QVBoxLayout(create_box)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(8)
        cl.addWidget(_make_section_title("新建目标"))
        self.input_title = QLineEdit()
        self.input_title.setPlaceholderText("目标标题，例如：写完文档第 3 章")
        self.input_note = QTextEdit()
        self.input_note.setPlaceholderText("备注（可选）")
        self.input_note.setFixedHeight(56)
        cl.addWidget(self.input_title)
        cl.addWidget(self.input_note)
        bt = QHBoxLayout()
        bt.addStretch(1)
        self.btn_create = QPushButton("创建目标")
        self.btn_create.setObjectName("Primary")
        self.btn_create.clicked.connect(self._on_create)
        bt.addWidget(self.btn_create)
        cl.addLayout(bt)
        v.addWidget(create_box)

        # 目标列表
        self.tabs = QTabWidget()
        self.tab_active = self._make_scroll_tab()
        self.tab_paused = self._make_scroll_tab()
        self.tab_done = self._make_scroll_tab()
        self.tabs.addTab(self.tab_active["widget"], "进行中")
        self.tabs.addTab(self.tab_paused["widget"], "已暂停")
        self.tabs.addTab(self.tab_done["widget"], "已完成")
        v.addWidget(self.tabs, 1)

    def _make_scroll_tab(self) -> dict:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        inner = QWidget()
        inner.setObjectName("TabInner")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(2, 2, 2, 8)
        layout.setSpacing(10)
        layout.addStretch(1)
        scroll.setWidget(inner)
        return {"widget": scroll, "inner": inner, "layout": layout}

    # ---------- 行为 ----------
    def _on_create(self) -> None:
        title = self.input_title.text().strip()
        note = self.input_note.toPlainText().strip()
        if not title:
            QMessageBox.information(self, "提示", "请输入目标标题")
            return
        self.manager.create(title, note)
        self.input_title.clear()
        self.input_note.clear()
        self.state_changed.emit()
        self.refresh()

    def _on_card_action(self, task_id: str, action: str, extra: str = "") -> None:
        if action == "pause":
            self.manager.pause(task_id)
        elif action == "resume":
            self.manager.resume(task_id)
        elif action == "subtask_toggle_fold":
            if self.manager.toggle_subtask_expand(task_id, extra):
                self.state_changed.emit()
                self.refresh()
            return
        elif action == "subtask_focus":
            if self.manager.focus_subtask(task_id, extra):
                self.state_changed.emit()
                self.refresh()
            return
        elif action == "subtask_pause":
            if self.manager.pause_subtask_focus(task_id):
                self.state_changed.emit()
                self.refresh()
            return
        elif action == "subtask_decompose":
            parts = extra.split("|", 1)
            if len(parts) < 2:
                return
            subtask_id, titles_raw = parts[0], parts[1]
            titles = [t.strip() for t in titles_raw.split(",") if t.strip()]
            if not titles:
                return
            if self.manager.decompose_subtask(task_id, subtask_id, titles):
                self.state_changed.emit()
                self.refresh()
            return
        elif action == "subtask_add":
            parts = extra.split("|")
            title = parts[0] if parts else ""
            target_minutes = None
            parent_subtask_id = None
            if len(parts) >= 2 and parts[1]:
                target_minutes = max(1, int(parts[1]))
            if len(parts) >= 3 and parts[2]:
                parent_subtask_id = parts[2]
            self.manager.add_subtask(
                task_id,
                title,
                target_minutes=target_minutes,
                parent_subtask_id=parent_subtask_id,
            )
        elif action == "subtask_confirm_done":
            task = self.manager.get(task_id)
            if task is None:
                return
            sub = task.find_subtask(extra)
            if sub is None or sub.done:
                self.refresh()
                return
            if not self.manager.subtask_time_met(task_id, extra):
                QMessageBox.information(
                    self,
                    "提示",
                    f"目标「{sub.title}」时长未达标（"
                    f"{format_duration(sub.active_seconds)}/"
                    f"{format_duration(sub.target_seconds)}），暂不能完成。",
                )
                self.refresh()
                return
            ret = QMessageBox.question(
                self,
                "完成目标",
                f"完成目标「{sub.title}」？\n完成后请点击「领取」获得奖励。",
            )
            if ret != QMessageBox.Yes:
                self.refresh()
                return
            if not self.manager.confirm_manual_complete_subtask(task_id, extra):
                self.refresh()
                return
            self.state_changed.emit()
            self.refresh()
            return
        elif action == "subtask_claim":
            task = self.manager.get(task_id)
            if task is None:
                return
            sub = task.find_subtask(extra)
            if sub is None:
                return
            reward = self.manager.claim_subtask_reward(task_id, extra)
            if reward is not None:
                self.subtask_claimed.emit(sub.title, reward)
            self.state_changed.emit()
            self.refresh()
            return
        elif action == "subtask_delete":
            task = self.manager.get(task_id)
            if task is None:
                return
            sub = task.find_subtask(extra)
            if sub is None:
                return
            if not sub.rewards_claimed:
                p = sub.pending_summary()
                if sub.done or p.gold or p.diamond:
                    ret = QMessageBox.question(
                        self,
                    "删除目标",
                    f"「{sub.title}」有未领取奖励，确定删除吗？",
                    )
                    if ret != QMessageBox.Yes:
                        return
            self.manager.delete_subtask(task_id, extra)
        elif action == "delete":
            task = self.manager.get(task_id)
            if task is None:
                return
            ret = QMessageBox.question(
                self, "删除目标",
                f"确定要删除「{task.title}」吗？\n未领取的奖励将一并丢失。",
            )
            if ret != QMessageBox.Yes:
                return
            self.manager.delete(task_id)
        elif action == "complete":
            task = self.manager.get(task_id)
            if task is None:
                return
            if not self.manager.can_complete_task(task_id):
                QMessageBox.information(
                    self,
                    "提示",
                    "请先完成并领取所有目标的奖励，再完成目标。",
                )
                return
            reward = self.manager.complete(task_id)
            if reward is not None and not reward.is_empty():
                QMessageBox.information(
                    self, "恭喜",
                    f"目标「{task.title}」已完成！\n获得 {format_reward_gain(reward.gold, reward.diamond)}",
                )
            else:
                QMessageBox.information(
                    self, "完成",
                    f"目标「{task.title}」已完成。本次没有累计到奖励。",
                )
        self.state_changed.emit()
        self.refresh()

    # ---------- 刷新 ----------
    def refresh_stats(self) -> None:
        """轻量刷新：只更新各卡片上的操作数/奖励，不重建列表。"""
        for tab in (self.tab_active, self.tab_paused, self.tab_done):
            for card in tab["inner"].findChildren(TaskCard):
                card.update_stats()

    def refresh(self) -> None:
        self._fill_tab(self.tab_active, self.manager.by_status(TaskStatus.ACTIVE))
        self._fill_tab(self.tab_paused, self.manager.by_status(TaskStatus.PAUSED))
        # 已完成：倒序
        done = sorted(
            self.manager.by_status(TaskStatus.COMPLETED),
            key=lambda t: t.completed_at or 0,
            reverse=True,
        )
        self._fill_tab(self.tab_done, done)

        self.tabs.setTabText(0, f"进行中 ({len(self.manager.by_status(TaskStatus.ACTIVE))})")
        self.tabs.setTabText(1, f"已暂停 ({len(self.manager.by_status(TaskStatus.PAUSED))})")
        self.tabs.setTabText(2, f"已完成 ({len(self.manager.by_status(TaskStatus.COMPLETED))})")

    def _clear_tab_layout(self, layout: QVBoxLayout) -> None:
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _fill_tab(self, tab: dict, tasks) -> None:
        layout: QVBoxLayout = tab["layout"]
        self._clear_tab_layout(layout)
        if not tasks:
            empty = QLabel("暂无目标")
            empty.setObjectName("EmptyHint")
            empty.setAlignment(Qt.AlignCenter)
            layout.addWidget(empty)
        else:
            for t in tasks:
                default_min = int(self.state.settings.get("subtask_default_target_minutes", 10))
                card = TaskCard(t, manager=self.manager, default_target_minutes=default_min)
                card.action.connect(self._on_card_action)
                layout.addWidget(card)
        layout.addStretch(1)
