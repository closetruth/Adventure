"""任务卡片/悬浮窗上的「操作数 + 待领金币/钻石」醒目展示。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

TASK_STATS_QSS = """
QLabel#TaskOpNum { color: #86efac; font-size: 28px; font-weight: 800; }
QLabel#TaskGoldNum { color: #ffd54f; font-size: 28px; font-weight: 800; }
QLabel#TaskDiamNum { color: #7dd3fc; font-size: 28px; font-weight: 800; }
QLabel#TaskStatCap { color: #d8dce8; font-size: 13px; font-weight: 700; }
QLabel#TaskHint { color: #b8bcc8; font-size: 12px; font-weight: 500; }
QLabel#TaskDuration { color: #9aa0b4; font-size: 11px; }
"""


def _make_chip(caption: str, num_object: str) -> dict:
    box = QWidget()
    box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(10, 8, 10, 8)
    lay.setSpacing(2)
    num = QLabel("0")
    num.setObjectName(num_object)
    num.setAlignment(Qt.AlignCenter)
    cap = QLabel(caption)
    cap.setObjectName("TaskStatCap")
    cap.setAlignment(Qt.AlignCenter)
    lay.addWidget(num)
    lay.addWidget(cap)
    box.setStyleSheet(
        "background-color: rgba(255,255,255,16); border-radius: 10px;"
    )
    return {"box": box, "num": num}


class TaskRewardStrip(QWidget):
    """三格大数字：本任务操作 / 待领金币 / 待领钻石。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(TASK_STATS_QSS)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.op_chip = _make_chip("本任务操作", "TaskOpNum")
        self.gold_chip = _make_chip("待领金币", "TaskGoldNum")
        self.diam_chip = _make_chip("待领钻石", "TaskDiamNum")
        row.addWidget(self.op_chip["box"])
        row.addWidget(self.gold_chip["box"])
        row.addWidget(self.diam_chip["box"])
        root.addLayout(row)

        self.duration_lbl = QLabel("")
        self.duration_lbl.setObjectName("TaskDuration")
        self.duration_lbl.setAlignment(Qt.AlignRight)
        root.addWidget(self.duration_lbl)

        self.hint_lbl = QLabel("")
        self.hint_lbl.setObjectName("TaskHint")
        self.hint_lbl.setWordWrap(True)
        self.hint_lbl.hide()
        root.addWidget(self.hint_lbl)

    def show_active(self, operations: int, gold: int, diamond: int, duration: str = "") -> None:
        self.hint_lbl.hide()
        self.op_chip["box"].show()
        self.gold_chip["box"].show()
        self.diam_chip["box"].show()
        self.op_chip["num"].setText(str(operations))
        self.gold_chip["num"].setText(str(gold))
        self.diam_chip["num"].setText(str(diamond))
        if duration:
            self.duration_lbl.setText(f"已进行 {duration}")
            self.duration_lbl.show()
        else:
            self.duration_lbl.hide()

    def show_hint(self, text: str) -> None:
        self.op_chip["box"].hide()
        self.gold_chip["box"].hide()
        self.diam_chip["box"].hide()
        self.duration_lbl.hide()
        self.hint_lbl.setText(text)
        self.hint_lbl.show()
