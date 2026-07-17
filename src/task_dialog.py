"""目标管理对话框：创建 / 暂停 / 恢复 / 完成 / 删除目标。"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from .ui_task_stats import TASK_STATS_QSS, TaskRewardStrip
from .ui_text import (
    format_amount,
    format_duration,
    format_pending,
    format_reward_gain,
    format_timestamp_short,
)


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
QLabel#StatusBadge {
    font-size: 11px; font-weight: 700;
    padding: 4px 10px; border-radius: 10px;
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
""" + TASK_STATS_QSS


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


def _make_status_badge(status: TaskStatus) -> QLabel:
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


class TaskCard(QFrame):
    """单个目标卡片。"""

    action = Signal(str, str, str)  # (task_id, action_name, extra)

    def __init__(self, task: Task, *, default_target_minutes: int = 10):
        super().__init__()
        self.task = task
        self._default_target_minutes = max(1, default_target_minutes)
        self.setObjectName("Card")
        self.setProperty("active", task.status == TaskStatus.ACTIVE)
        self._subtask_input: Optional[QLineEdit] = None
        self._subtask_minutes_spin: Optional[QSpinBox] = None
        self._build()

    def _subtask_dates_label(self, sub: Subtask) -> str:
        parts: list[str] = []
        created = format_timestamp_short(sub.created_at)
        if created:
            parts.append(f"创{created}")
        completed = format_timestamp_short(sub.completed_at)
        if completed:
            parts.append(f"完{completed}")
        return " · ".join(parts)

    def _subtask_meta_line(self, sub: Subtask, *, is_current: bool) -> str:
        parts = [
            f"时长 {format_duration(sub.active_seconds)}/{format_duration(sub.target_seconds)}",
            f"操作 {sub.operations}",
        ]
        if sub.earned_gold:
            parts.append(f"累计金 {format_amount(sub.earned_gold)}")
        if sub.earned_diamond:
            parts.append(f"累计钻 {format_amount(sub.earned_diamond)}")
        dates = self._subtask_dates_label(sub)
        if dates:
            parts.append(dates)
        if sub.done and not sub.rewards_claimed:
            pending = sub.pending_summary()
            # 领取实际给的是 pending + 完成奖励；与累计 earned 可能不同
            parts.append(f"可领 {format_pending(pending.gold, pending.diamond)}")
        if is_current:
            parts.append("当前聚焦")
        elif sub.rewards_claimed:
            parts.append("已领取")
        return " · ".join(parts)

    def _subtask_marker(self, sub: Subtask, *, is_current: bool) -> tuple[str, str]:
        if sub.is_claimable():
            return "●", "#f0c040"
        if sub.rewards_claimed:
            return "✓", "#6e7588"
        if sub.done:
            return "●", "#f0c040"
        if is_current:
            return "●", "#7eb4ff"
        return "○", "#5a6175"

    def _polish_row(self, row: QFrame) -> None:
        row.style().unpolish(row)
        row.style().polish(row)

    def _on_subtask_checked(self, state: int, subtask_id: str) -> None:
        if state != Qt.CheckState.Checked.value:
            return
        sub = next((s for s in self.task.subtasks if s.id == subtask_id), None)
        if sub is None or sub.done:
            return
        self.action.emit(self.task.id, "subtask_confirm_done", subtask_id)

    def _build_subtasks(self, parent: QVBoxLayout) -> None:
        done, total = self.task.subtask_progress()
        editable = self.task.status != TaskStatus.COMPLETED
        current_id = self.task.current_subtask_id

        if total > 0 or editable:
            cap = _make_section_title(
                f"子目标 · {done}/{total}" if total else "子目标"
            )
            parent.addWidget(cap)

        sub_layout = QVBoxLayout()
        sub_layout.setSpacing(6)
        sub_layout.setContentsMargins(0, 0, 0, 0)

        for sub in self.task.subtasks:
            is_current = (
                sub.id == current_id
                and self.task.status == TaskStatus.ACTIVE
                and not sub.done
            )
            row = QFrame()
            row.setObjectName("SubtaskRow")
            if sub.is_claimable():
                row.setProperty("claimable", True)
            elif is_current:
                row.setProperty("current", True)
            elif sub.rewards_claimed:
                row.setProperty("done", True)

            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(10, 8, 10, 8)
            row_lay.setSpacing(8)

            if (
                editable
                and not sub.done
                and not sub.rewards_claimed
                and not sub.is_claimable()
            ):
                cb = QCheckBox()
                cb.setObjectName("SubtaskCheck")
                cb.setToolTip("时长达标后可勾选完成")
                with QSignalBlocker(cb):
                    cb.setChecked(False)
                can_check = sub.time_target_met()
                cb.setEnabled(can_check)
                cb.stateChanged.connect(
                    lambda state, sid=sub.id: self._on_subtask_checked(state, sid)
                )
                row_lay.addWidget(cb, 0, Qt.AlignTop)
            else:
                mark_char, mark_color = self._subtask_marker(sub, is_current=is_current)
                mark = QLabel(mark_char)
                mark.setObjectName("SubtaskMark")
                mark.setStyleSheet(f"color: {mark_color};")
                mark.setAlignment(Qt.AlignTop)
                row_lay.addWidget(mark)

            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            text_col.setContentsMargins(0, 0, 0, 0)
            title = QLabel(sub.title)
            title.setObjectName("SubtaskTitle")
            if sub.is_claimable():
                title.setProperty("claimable", True)
            elif is_current:
                title.setProperty("current", True)
            elif sub.rewards_claimed:
                title.setProperty("done", True)
            title.setWordWrap(True)
            meta = QLabel(self._subtask_meta_line(sub, is_current=is_current))
            meta.setObjectName("SubtaskMeta")
            meta.setWordWrap(True)
            text_col.addWidget(title)
            text_col.addWidget(meta)
            row_lay.addLayout(text_col, 1)

            if sub.is_claimable():
                btn_claim = QPushButton("领取")
                btn_claim.setObjectName("SubtaskClaim")
                btn_claim.clicked.connect(
                    lambda _checked=False, sid=sub.id: self.action.emit(
                        self.task.id, "subtask_claim", sid
                    )
                )
                row_lay.addWidget(btn_claim, 0, Qt.AlignTop)
            elif editable and not sub.done and not sub.rewards_claimed:
                btn_del = QPushButton("×")
                btn_del.setObjectName("SubtaskDel")
                btn_del.setFixedWidth(28)
                btn_del.setToolTip("删除子目标")
                btn_del.clicked.connect(
                    lambda _checked=False, sid=sub.id: self.action.emit(
                        self.task.id, "subtask_delete", sid
                    )
                )
                row_lay.addWidget(btn_del, 0, Qt.AlignTop)

            self._polish_row(row)
            title.style().unpolish(title)
            title.style().polish(title)
            sub_layout.addWidget(row)

        if sub_layout.count():
            parent.addLayout(sub_layout)

        if editable:
            add_row = QHBoxLayout()
            add_row.setSpacing(6)
            inp = QLineEdit()
            inp.setObjectName("SubtaskInput")
            inp.setPlaceholderText("新子目标标题…")
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

    def _emit_subtask_add(self) -> None:
        if self._subtask_input is None:
            return
        title = self._subtask_input.text().strip()
        if not title:
            return
        target_minutes = self._default_target_minutes
        if self._subtask_minutes_spin is not None:
            target_minutes = self._subtask_minutes_spin.value()
        self.action.emit(self.task.id, "subtask_add", f"{title}|{target_minutes}")
        self._subtask_input.clear()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel(self.task.title)
        title.setObjectName("TaskTitle")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        head.addWidget(_make_status_badge(self.task.status), 0, Qt.AlignTop)
        v.addLayout(head)

        if self.task.note:
            note = QLabel(self.task.note)
            note.setObjectName("Note")
            note.setWordWrap(True)
            v.addWidget(note)

        v.addWidget(_make_divider())
        self._build_subtasks(v)

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
        v.addWidget(_make_section_title("累计数据"))
        self.task_stats = TaskRewardStrip()
        if self.task.status == TaskStatus.COMPLETED:
            self.task_stats.show_completed(
                self.task.operations,
                *self.task.earned_totals(),
            )
        else:
            self.task_stats.show_active_compact(
                self.task.operations,
                *self.task.earned_totals(),
            )
        v.addWidget(self.task_stats)
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
        """仅刷新操作数/奖励数字，不重建卡片（避免打断子目标输入）。"""
        if self.task.status == TaskStatus.COMPLETED:
            self.task_stats.show_completed(
                self.task.operations,
                *self.task.earned_totals(),
            )
        else:
            self.task_stats.show_active_compact(
                self.task.operations,
                *self.task.earned_totals(),
            )

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
        elif action == "subtask_add":
            if "|" in extra:
                title, min_str = extra.split("|", 1)
                target_minutes = max(1, int(min_str))
            else:
                title, target_minutes = extra, None
            self.manager.add_subtask(task_id, title, target_minutes=target_minutes)
        elif action == "subtask_confirm_done":
            task = self.manager.get(task_id)
            if task is None:
                return
            sub = next((s for s in task.subtasks if s.id == extra), None)
            if sub is None or sub.done:
                self.refresh()
                return
            if not self.manager.subtask_time_met(task_id, extra):
                QMessageBox.information(
                    self,
                    "提示",
                    f"子目标「{sub.title}」时长未达标（"
                    f"{format_duration(sub.active_seconds)}/"
                    f"{format_duration(sub.target_seconds)}），暂不能完成。",
                )
                self.refresh()
                return
            ret = QMessageBox.question(
                self,
                "完成子目标",
                f"完成子目标「{sub.title}」？\n完成后请点击「领取」获得奖励。",
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
            sub = next((s for s in task.subtasks if s.id == extra), None)
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
            sub = next((s for s in task.subtasks if s.id == extra), None)
            if sub is None:
                return
            if not sub.rewards_claimed:
                p = sub.pending_summary()
                if sub.done or p.gold or p.diamond:
                    ret = QMessageBox.question(
                        self,
                    "删除子目标",
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
                    "请先完成并领取所有子目标的奖励，再完成目标。",
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
                card = TaskCard(t, default_target_minutes=default_min)
                card.action.connect(self._on_card_action)
                layout.addWidget(card)
        layout.addStretch(1)
