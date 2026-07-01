"""目标卡片/悬浮窗上的「操作数 + 待领金币/钻石」醒目展示。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .ui_text import format_amount, format_goal_compact_html, format_since_roll, format_widget_runtime_html


def _set_if_changed(label: QLabel, text: str) -> None:
    if label.text() != text:
        label.setText(text)


TASK_STATS_QSS = """
QLabel#TaskOpNum { color: #8ff5b0; font-size: 32px; font-weight: 800; }
QLabel#TaskGoldNum { color: #ffe082; font-size: 32px; font-weight: 800; }
QLabel#TaskDiamNum { color: #8fd4ff; font-size: 32px; font-weight: 800; }
QLabel#TaskStatCap { color: #f0f2f8; font-size: 13px; font-weight: 700; }
QLabel#TaskRateNum { color: #a7f3d0; font-size: 22px; font-weight: 800; }
QLabel#TaskSinceRoll { color: #ffe599; font-size: 18px; font-weight: 800; }
QLabel#TaskSubCap { color: #c8ceda; font-size: 11px; font-weight: 600; }
QLabel#TaskHint { color: #c8ceda; font-size: 12px; font-weight: 500; }
QLabel#TaskDuration { color: #b8bfd0; font-size: 11px; }
QLabel#GoalCompact { color: #f2f4fa; font-size: 13px; }
QLabel#GoalCompactSub { color: #b8bfd0; font-size: 12px; }
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
    """目标区：大数字待领奖励 + 近1分钟操作 + 上次开奖积累。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(TASK_STATS_QSS)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        main_row = QHBoxLayout()
        main_row.setSpacing(6)
        self.op_chip = _make_chip("本目标操作", "TaskOpNum", bg="rgba(143,245,176,28)")
        self.gold_chip = _make_chip("目标累计金币", "TaskGoldNum", bg="rgba(255,224,130,28)")
        self.diam_chip = _make_chip("目标累计钻石", "TaskDiamNum", bg="rgba(143,212,255,28)")
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

        self.compact_lbl = QLabel("")
        self.compact_lbl.setObjectName("GoalCompact")
        self.compact_lbl.setWordWrap(True)
        self.compact_lbl.setTextFormat(Qt.RichText)
        self.compact_lbl.hide()
        root.addWidget(self.compact_lbl)

        self.compact_sub_lbl = QLabel("")
        self.compact_sub_lbl.setObjectName("GoalCompactSub")
        self.compact_sub_lbl.setWordWrap(True)
        self.compact_sub_lbl.setTextFormat(Qt.RichText)
        self.compact_sub_lbl.hide()
        root.addWidget(self.compact_sub_lbl)

        self._mode = "hint"

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
        if self._mode != "active":
            self.hint_lbl.hide()
            self.compact_lbl.hide()
            self.compact_sub_lbl.hide()
            self.op_chip["box"].show()
            self.gold_chip["box"].show()
            self.diam_chip["box"].show()
            self._mode = "active"
        self.op_chip["cap"].setText("本目标操作")
        self.gold_chip["cap"].setText("目标累计金币")
        self.diam_chip["cap"].setText("目标累计钻石")
        _set_if_changed(self.op_chip["num"], str(operations))
        _set_if_changed(self.gold_chip["num"], format_amount(gold))
        _set_if_changed(self.diam_chip["num"], format_amount(diamond))

        if show_runtime:
            if not self.rate_chip["box"].isVisible():
                self.rate_chip["box"].show()
                self.since_roll_chip["box"].show()
            _set_if_changed(self.rate_chip["num"], str(ops_1min))
            _set_if_changed(
                self.since_roll_chip["num"],
                format_since_roll(since_roll_gold, since_roll_diamond),
            )
        else:
            self.rate_chip["box"].hide()
            self.since_roll_chip["box"].hide()

        if duration:
            _set_if_changed(self.duration_lbl, f"进行中 {duration}")
            if not self.duration_lbl.isVisible():
                self.duration_lbl.show()
        elif self.duration_lbl.isVisible():
            self.duration_lbl.hide()

    def show_active_compact(
        self,
        operations: int,
        gold: float,
        diamond: float,
        *,
        ops_1min: int = 0,
        since_roll_gold: float = 0.0,
        since_roll_diamond: float = 0.0,
        duration: str = "",
    ) -> None:
        if self._mode != "compact":
            self.hint_lbl.hide()
            self.op_chip["box"].hide()
            self.gold_chip["box"].hide()
            self.diam_chip["box"].hide()
            self.rate_chip["box"].hide()
            self.since_roll_chip["box"].hide()
            self.duration_lbl.hide()
            self.compact_lbl.show()
            self.compact_sub_lbl.show()
            self._mode = "compact"
        _set_if_changed(
            self.compact_lbl,
            format_goal_compact_html(operations, gold, diamond),
        )
        _set_if_changed(
            self.compact_sub_lbl,
            format_widget_runtime_html(
                ops_1min, since_roll_gold, since_roll_diamond, duration,
            ),
        )

    def show_completed(self, operations: int, gold: float, diamond: float) -> None:
        """已完成目标：显示操作数与完成时获得的奖励。"""
        if self._mode != "completed":
            self.hint_lbl.hide()
            self.compact_lbl.hide()
            self.compact_sub_lbl.hide()
            self.rate_chip["box"].hide()
            self.since_roll_chip["box"].hide()
            self.duration_lbl.hide()
            self.op_chip["box"].show()
            self.gold_chip["box"].show()
            self.diam_chip["box"].show()
            self._mode = "completed"
        self.op_chip["cap"].setText("本目标操作")
        self.gold_chip["cap"].setText("获得金币")
        self.diam_chip["cap"].setText("获得钻石")
        _set_if_changed(self.op_chip["num"], str(operations))
        _set_if_changed(self.gold_chip["num"], format_amount(gold))
        _set_if_changed(self.diam_chip["num"], format_amount(diamond))

    def show_hint(self, text: str) -> None:
        if self._mode != "hint":
            self.op_chip["box"].hide()
            self.gold_chip["box"].hide()
            self.diam_chip["box"].hide()
            self.rate_chip["box"].hide()
            self.since_roll_chip["box"].hide()
            self.duration_lbl.hide()
            self.compact_lbl.hide()
            self.compact_sub_lbl.hide()
            self._mode = "hint"
        _set_if_changed(self.hint_lbl, text)
        if not self.hint_lbl.isVisible():
            self.hint_lbl.show()
