"""任务管理对话框：创建 / 暂停 / 恢复 / 完成 / 删除任务。"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .models import AppState, Task, TaskStatus
from .task_manager import TaskManager
from .ui_text import format_pending, format_reward_gain


DIALOG_STYLESHEET = """
QDialog { background-color: #1c1c26; color: #f0f0f6; }
QLabel { color: #f0f0f6; font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; }
QTabWidget::pane { border: 1px solid #2e3040; border-radius: 8px; padding: 6px; }
QTabBar::tab {
    background: transparent; color: #b3b6c4;
    padding: 6px 14px; border-radius: 6px; margin-right: 4px;
}
QTabBar::tab:selected { background: #2b3050; color: #ffffff; }
QPushButton {
    background-color: #2b3050; color: #f0f0f6;
    border: 1px solid #3a4070; border-radius: 6px;
    padding: 5px 10px;
}
QPushButton:hover { background-color: #3a4070; }
QPushButton#Primary { background-color: #3a5cff; border-color: #3a5cff; }
QPushButton#Primary:hover { background-color: #4d6dff; }
QPushButton#Danger:hover { background-color: #b3403d; border-color: #b3403d; }
QLineEdit, QTextEdit {
    background-color: #14141c; color: #f0f0f6;
    border: 1px solid #2e3040; border-radius: 6px; padding: 6px;
}
QScrollArea { border: none; }
QFrame#Card {
    background-color: #23242f;
    border: 1px solid #2e3040;
    border-radius: 10px;
}
QFrame#Card[active="true"] { border: 1px solid #3a5cff; }
QLabel#TaskTitle { font-size: 15px; font-weight: 700; }
QLabel#Meta { color: #b8bcc8; font-size: 12px; font-weight: 500; }
QLabel#Status { font-size: 12px; font-weight: 700; }
"""


class TaskCard(QFrame):
    """单个任务卡片。"""

    action = Signal(str, str)  # (task_id, action_name)

    def __init__(self, task: Task):
        super().__init__()
        self.task = task
        self.setObjectName("Card")
        self.setProperty("active", task.status == TaskStatus.ACTIVE)
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        head = QHBoxLayout()
        title = QLabel(self.task.title)
        title.setObjectName("TaskTitle")
        title.setWordWrap(True)
        head.addWidget(title, 1)

        status_text = {
            TaskStatus.ACTIVE: "进行中",
            TaskStatus.PAUSED: "已暂停",
            TaskStatus.COMPLETED: "已完成",
        }.get(self.task.status, str(self.task.status))
        color = {
            TaskStatus.ACTIVE: "#7fe787",
            TaskStatus.PAUSED: "#ffc857",
            TaskStatus.COMPLETED: "#7fb1ff",
        }.get(self.task.status, "#cccccc")
        status = QLabel(status_text)
        status.setObjectName("Status")
        status.setStyleSheet(f"color: {color};")
        head.addWidget(status)
        v.addLayout(head)

        if self.task.note:
            note = QLabel(self.task.note)
            note.setWordWrap(True)
            note.setStyleSheet("color: #c4c7d6; font-size: 12px;")
            v.addWidget(note)

        meta = QLabel(self._meta_text())
        meta.setObjectName("Meta")
        v.addWidget(meta)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        if self.task.status == TaskStatus.ACTIVE:
            b_pause = QPushButton("暂停")
            b_pause.clicked.connect(lambda: self.action.emit(self.task.id, "pause"))
            btn_row.addWidget(b_pause)
            b_complete = QPushButton("完成并领奖")
            b_complete.setObjectName("Primary")
            b_complete.clicked.connect(lambda: self.action.emit(self.task.id, "complete"))
            btn_row.addWidget(b_complete)
        elif self.task.status == TaskStatus.PAUSED:
            b_resume = QPushButton("恢复")
            b_resume.setObjectName("Primary")
            b_resume.clicked.connect(lambda: self.action.emit(self.task.id, "resume"))
            btn_row.addWidget(b_resume)
            b_complete = QPushButton("完成")
            b_complete.clicked.connect(lambda: self.action.emit(self.task.id, "complete"))
            btn_row.addWidget(b_complete)
        else:
            btn_row.addStretch(1)

        btn_row.addStretch(1)
        b_del = QPushButton("删除")
        b_del.setObjectName("Danger")
        b_del.clicked.connect(lambda: self.action.emit(self.task.id, "delete"))
        btn_row.addWidget(b_del)
        v.addLayout(btn_row)

    def _meta_text(self) -> str:
        created = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.task.created_at))
        parts = [f"创建：{created}", f"操作 {self.task.operations}"]
        summary = self.task.pending_summary()
        if summary.gold or summary.diamond:
            parts.append(format_pending(summary.gold, summary.diamond))
        if self.task.completed_at:
            done = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.task.completed_at))
            parts.append(f"完成：{done}")
        return "  ·  ".join(parts)


class TaskDialog(QDialog):
    """任务管理主对话框。"""

    state_changed = Signal()

    def __init__(self, state: AppState, manager: TaskManager, parent=None):
        super().__init__(parent)
        self.state = state
        self.manager = manager

        self.setWindowTitle("任务管理 - Adventure")
        self.resize(520, 600)
        self.setStyleSheet(DIALOG_STYLESHEET)
        self._build()
        self.refresh()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        # 创建栏
        create_box = QFrame()
        create_box.setObjectName("Card")
        cl = QVBoxLayout(create_box)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(6)
        cl.addWidget(QLabel("新建任务"))
        self.input_title = QLineEdit()
        self.input_title.setPlaceholderText("任务标题，例如：写完文档第 3 章")
        self.input_note = QTextEdit()
        self.input_note.setPlaceholderText("备注（可选）")
        self.input_note.setFixedHeight(60)
        cl.addWidget(self.input_title)
        cl.addWidget(self.input_note)
        bt = QHBoxLayout()
        bt.addStretch(1)
        self.btn_create = QPushButton("创建任务")
        self.btn_create.setObjectName("Primary")
        self.btn_create.clicked.connect(self._on_create)
        bt.addWidget(self.btn_create)
        cl.addLayout(bt)
        v.addWidget(create_box)

        # 任务列表
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
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        layout.addStretch(1)
        scroll.setWidget(inner)
        return {"widget": scroll, "inner": inner, "layout": layout}

    # ---------- 行为 ----------
    def _on_create(self) -> None:
        title = self.input_title.text().strip()
        note = self.input_note.toPlainText().strip()
        if not title:
            QMessageBox.information(self, "提示", "请输入任务标题")
            return
        self.manager.create(title, note)
        self.input_title.clear()
        self.input_note.clear()
        self.state_changed.emit()
        self.refresh()

    def _on_card_action(self, task_id: str, action: str) -> None:
        if action == "pause":
            self.manager.pause(task_id)
        elif action == "resume":
            self.manager.resume(task_id)
        elif action == "delete":
            task = self.manager.get(task_id)
            if task is None:
                return
            ret = QMessageBox.question(
                self, "删除任务",
                f"确定要删除「{task.title}」吗？\n未领取的奖励将一并丢失。",
            )
            if ret != QMessageBox.Yes:
                return
            self.manager.delete(task_id)
        elif action == "complete":
            task = self.manager.get(task_id)
            if task is None:
                return
            reward = self.manager.complete(task_id)
            if reward is not None and not reward.is_empty():
                QMessageBox.information(
                    self, "恭喜",
                    f"任务「{task.title}」已完成！\n获得 {format_reward_gain(reward.gold, reward.diamond)}",
                )
            else:
                QMessageBox.information(
                    self, "完成",
                    f"任务「{task.title}」已完成。本次没有累计到奖励。",
                )
        self.state_changed.emit()
        self.refresh()

    # ---------- 刷新 ----------
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

    def _fill_tab(self, tab: dict, tasks) -> None:
        layout: QVBoxLayout = tab["layout"]
        while layout.count() > 0:
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not tasks:
            empty = QLabel("空空如也～")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #6e718a; padding: 30px;")
            layout.addWidget(empty)
        else:
            for t in tasks:
                card = TaskCard(t)
                card.action.connect(self._on_card_action)
                layout.addWidget(card)
        layout.addStretch(1)
