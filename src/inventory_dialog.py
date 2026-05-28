"""奖励背包对话框：展示玩家拥有的金币 / 钻石以及历史奖励统计。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .models import AppState, TaskStatus


DIALOG_STYLESHEET = """
QDialog { background-color: #1c1c26; color: #f0f0f6; }
QLabel { color: #f0f0f6; font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; }
QFrame#Card {
    background-color: #23242f;
    border: 1px solid #2e3040;
    border-radius: 12px;
}
QLabel#Big { font-size: 40px; font-weight: 800; }
QLabel#Cap { font-size: 15px; font-weight: 700; }
QLabel#Section { color: #e0e4f0; font-size: 14px; font-weight: 700; }
QLabel#StatLine { color: #c8ccd8; font-size: 13px; font-weight: 500; }
QPushButton {
    background-color: #2b3050; color: #f0f0f6;
    border: 1px solid #3a4070; border-radius: 6px;
    padding: 6px 12px;
    font-size: 13px;
}
QPushButton:hover { background-color: #3a4070; }
"""


class InventoryDialog(QDialog):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("奖励背包 - Adventure")
        self.resize(420, 460)
        self.setStyleSheet(DIALOG_STYLESHEET)
        self._build()
        self.refresh()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)

        v.addWidget(self._section_label("当前持有"))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.gold_card = self._make_card("金币", "#ffd54f", "GoldCap")
        self.diam_card = self._make_card("钻石", "#7dd3fc", "DiamCap")
        row.addWidget(self.gold_card["frame"])
        row.addWidget(self.diam_card["frame"])
        v.addLayout(row)

        v.addWidget(self._section_label("数据统计"))
        self.stat_card = self._make_stat_card()
        v.addWidget(self.stat_card["frame"])

        v.addWidget(self._section_label("小游戏"))
        games = QFrame()
        games.setObjectName("Card")
        gl = QVBoxLayout(games)
        gl.setContentsMargins(14, 12, 14, 12)
        gl.setSpacing(6)
        gl.addWidget(QLabel("小动物自走棋"))
        sub = QLabel("敬请期待。用金币 / 钻石抽宠物，自动战斗赢取更多奖励。")
        sub.setObjectName("StatLine")
        sub.setWordWrap(True)
        gl.addWidget(sub)
        btn = QPushButton("即将上线")
        btn.setEnabled(False)
        gl.addWidget(btn, alignment=Qt.AlignRight)
        v.addWidget(games)

        v.addStretch(1)

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("Section")
        return lbl

    def _make_card(self, caption: str, color: str, cap_name: str) -> dict:
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 16, 16, 16)
        big = QLabel("0")
        big.setObjectName("Big")
        big.setStyleSheet(f"color: {color};")
        big.setAlignment(Qt.AlignCenter)
        cap = QLabel(caption)
        cap.setObjectName(cap_name)
        cap.setStyleSheet(f"color: {color};")
        cap.setAlignment(Qt.AlignCenter)
        lay.addWidget(big)
        lay.addWidget(cap)
        return {"frame": frame, "num": big}

    def _make_stat_card(self) -> dict:
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        self.lbl_ops = QLabel()
        self.lbl_tasks_done = QLabel()
        self.lbl_tasks_active = QLabel()
        self.lbl_pending = QLabel()
        for w in (self.lbl_ops, self.lbl_tasks_done, self.lbl_tasks_active, self.lbl_pending):
            w.setObjectName("StatLine")
            lay.addWidget(w)
        return {"frame": frame}

    def refresh(self) -> None:
        s = self.state
        self.gold_card["num"].setText(str(s.inventory.gold))
        self.diam_card["num"].setText(str(s.inventory.diamond))
        self.lbl_ops.setText(f"全局操作数：{s.total_operations}")
        active = [t for t in s.tasks if t.status == TaskStatus.ACTIVE]
        done = [t for t in s.tasks if t.status == TaskStatus.COMPLETED]
        self.lbl_tasks_active.setText(f"进行中任务：{len(active)}")
        self.lbl_tasks_done.setText(f"已完成任务：{len(done)}")
        pending_g = pending_d = 0
        for t in s.tasks:
            if t.status != TaskStatus.COMPLETED:
                summary = t.pending_summary()
                pending_g += summary.gold
                pending_d += summary.diamond
        self.lbl_pending.setText(f"待领取：金币 {pending_g}，钻石 {pending_d}")
