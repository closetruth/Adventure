"""任务卡片/悬浮窗上的「操作数 + 待领金币/钻石」醒目展示。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .ui_text import format_amount, format_since_roll


TASK_STATS_QSS = """
QLabel#TaskOpNum { color: #86efac; font-size: 32px; font-weight: 800; }
QLabel#TaskGoldNum { color: #ffd54f; font-size: 32px; font-weight: 800; }
QLabel#TaskDiamNum { color: #7dd3fc; font-size: 32px; font-weight: 800; }
QLabel#TaskStatCap { color: #e8eaf0; font-size: 13px; font-weight: 700; }
QLabel#TaskRateNum { color: #a7f3d0; font-size: 22px; font-weight: 800; }
QLabel#TaskSinceRoll { color: #f5e6a8; font-size: 18px; font-weight: 800; }
QLabel#TaskSubCap { color: #b8bcc8; font-size: 11px; font-weight: 600; }
QLabel#TaskHint { color: #b8bcc8; font-size: 12px; font-weight: 500; }
QLabel#TaskDuration { color: #9aa0b4; font-size: 11px; }
"""


def _make_chip(
    caption: str,
    num_object: str,
    *,
    cap_object: str = "TaskStatCap",
    padding: str = "10, 10, 10, 10",
    bg: str = "rgba(255,255,255,16)",
    word_wrap: bool = False,
) -> dict:
    box = QWidget()
    box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    lay = QVBoxLayout(box)
    parts = [int(x.strip()) for x in padding.split(",")]
    lay.setContentsMargins(*parts)
    lay.setSpacing(2)
    num = QLabel("0")
    num.setObjectName(num_object)
    num.setAlignment(Qt.AlignCenter)
    num.setWordWrap(word_wrap)
    cap = QLabel(caption)
    cap.setObjectName(cap_object)
    cap.setAlignment(Qt.AlignCenter)
    cap.setWordWrap(True)
    lay.addWidget(num)
    lay.addWidget(cap)
    box.setStyleSheet(f"background-color: {bg}; border-radius: 10px;")
    return {"box": box, "num": num, "cap": cap}


class TaskRewardStrip(QWidget):
    """任务区：大数字待领奖励 + 近1分钟操作 + 上次开奖积累。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(TASK_STATS_QSS)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        main_row = QHBoxLayout()
        main_row.setSpacing(6)
        self.op_chip = _make_chip("本任务操作", "TaskOpNum", bg="rgba(134,239,172,22)")
        self.gold_chip = _make_chip("待领金币", "TaskGoldNum", bg="rgba(255,213,79,22)")
        self.diam_chip = _make_chip("待领钻石", "TaskDiamNum", bg="rgba(125,211,252,22)")
        main_row.addWidget(self.op_chip["box"])
        main_row.addWidget(self.gold_chip["box"])
        main_row.addWidget(self.diam_chip["box"])
        root.addLayout(main_row)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)
        self.rate_chip = _make_chip(
            "近1分钟操作",
            "TaskRateNum",
            cap_object="TaskSubCap",
            padding="8, 8, 8, 8",
            bg="rgba(255,255,255,10)",
        )
        self.since_roll_chip = _make_chip(
            "上次开奖获得",
            "TaskSinceRoll",
            cap_object="TaskSubCap",
            padding="8, 8, 8, 8",
            bg="rgba(255,213,79,16)",
            word_wrap=True,
        )
        sub_row.addWidget(self.rate_chip["box"], 2)
        sub_row.addWidget(self.since_roll_chip["box"], 3)
        root.addLayout(sub_row)

        self.duration_lbl = QLabel("")
        self.duration_lbl.setObjectName("TaskDuration")
        self.duration_lbl.setAlignment(Qt.AlignRight)
        root.addWidget(self.duration_lbl)

        self.hint_lbl = QLabel("")
        self.hint_lbl.setObjectName("TaskHint")
        self.hint_lbl.setWordWrap(True)
        self.hint_lbl.hide()
        root.addWidget(self.hint_lbl)

    def show_active(
        self,
        operations: int,
        gold: float,
        diamond: float,
        *,
        ops_1min: int = 0,
        since_roll_gold: float = 0.0,
        since_roll_diamond: float = 0.0,
        duration: str = "",
        show_runtime: bool = True,
    ) -> None:
        self.hint_lbl.hide()
        self.op_chip["box"].show()
        self.gold_chip["box"].show()
        self.diam_chip["box"].show()
        self.op_chip["cap"].setText("本任务操作")
        self.gold_chip["cap"].setText("待领金币")
        self.diam_chip["cap"].setText("待领钻石")
        self.op_chip["num"].setText(str(operations))
        self.gold_chip["num"].setText(format_amount(gold))
        self.diam_chip["num"].setText(format_amount(diamond))

        if show_runtime:
            self.rate_chip["box"].show()
            self.since_roll_chip["box"].show()
            self.rate_chip["num"].setText(str(ops_1min))
            self.since_roll_chip["num"].setText(
                format_since_roll(since_roll_gold, since_roll_diamond)
            )
        else:
            self.rate_chip["box"].hide()
            self.since_roll_chip["box"].hide()

        if duration:
            self.duration_lbl.setText(f"进行中 {duration}")
            self.duration_lbl.show()
        else:
            self.duration_lbl.hide()

    def show_completed(self, operations: int, gold: float, diamond: float) -> None:
        """已完成任务：显示操作数与完成时获得的奖励。"""
        self.hint_lbl.hide()
        self.rate_chip["box"].hide()
        self.since_roll_chip["box"].hide()
        self.duration_lbl.hide()
        self.op_chip["box"].show()
        self.gold_chip["box"].show()
        self.diam_chip["box"].show()
        self.op_chip["cap"].setText("本任务操作")
        self.gold_chip["cap"].setText("获得金币")
        self.diam_chip["cap"].setText("获得钻石")
        self.op_chip["num"].setText(str(operations))
        self.gold_chip["num"].setText(format_amount(gold))
        self.diam_chip["num"].setText(format_amount(diamond))

    def show_hint(self, text: str) -> None:
        self.op_chip["box"].hide()
        self.gold_chip["box"].hide()
        self.diam_chip["box"].hide()
        self.rate_chip["box"].hide()
        self.since_roll_chip["box"].hide()
        self.duration_lbl.hide()
        self.hint_lbl.setText(text)
        self.hint_lbl.show()
