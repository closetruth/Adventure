"""奖励背包对话框：展示玩家拥有的金币 / 钻石以及历史奖励统计。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .models import AppState, TaskStatus
from .ui_text import format_amount, format_roll_history_line


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
QLabel#HistLine { color: #b8bcc8; font-size: 12px; font-weight: 500; }
QLabel#HistHit { color: #ffd54f; font-size: 12px; font-weight: 600; }
QLabel#HistMiss { color: #8a909e; font-size: 12px; font-weight: 500; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QPushButton {
    background-color: #2b3050; color: #f0f0f6;
    border: 1px solid #3a4070; border-radius: 6px;
    padding: 6px 12px;
    font-size: 13px;
}
QPushButton:hover { background-color: #3a4070; }
QPushButton#Primary { background-color: #3a5cff; border-color: #3a5cff; font-weight: 700; }
QPushButton#Primary:hover { background-color: #4d6dff; }
"""


class InventoryDialog(QDialog):
    request_play_game = Signal()
    request_play_grid_game = Signal()

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("奖励背包 - Adventure")
        self.resize(420, 560)
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

        v.addWidget(self._section_label("开奖历史"))
        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setMaximumHeight(180)
        self.history_inner = QWidget()
        self.history_layout = QVBoxLayout(self.history_inner)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(4)
        self.history_scroll.setWidget(self.history_inner)
        v.addWidget(self.history_scroll)

        v.addWidget(self._section_label("小游戏"))
        games = QFrame()
        games.setObjectName("Card")
        gl = QVBoxLayout(games)
        gl.setContentsMargins(14, 12, 14, 12)
        gl.setSpacing(6)
        gl.addWidget(QLabel("小动物竞技场（AutoPet）"))
        sub = QLabel(
            "AutoPet 风格：Q/W/E 购买，A/S/D 冻结，1~5 选槽位，左右换位，X 卖出，R 刷新。"
            "空格开战，入场费 10 金币。"
        )
        sub.setObjectName("StatLine")
        sub.setWordWrap(True)
        gl.addWidget(sub)
        self.btn_play = QPushButton("开始游戏")
        self.btn_play.setObjectName("Primary")
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self.btn_play.clicked.connect(self.request_play_game.emit)
        gl.addWidget(self.btn_play, alignment=Qt.AlignRight)
        v.addWidget(games)

        grid_games = QFrame()
        grid_games.setObjectName("Card")
        gl2 = QVBoxLayout(grid_games)
        gl2.setContentsMargins(14, 12, 14, 12)
        gl2.setSpacing(6)
        gl2.addWidget(QLabel("像素格子战场（类金铲铲）"))
        sub2 = QLabel(
            "像素 6x4 棋盘，先布阵后自动战斗。方向键移动光标，Z 放置，R 刷新，空格开战。"
            "入场费 12 金币。"
        )
        sub2.setObjectName("StatLine")
        sub2.setWordWrap(True)
        gl2.addWidget(sub2)
        self.btn_play_grid = QPushButton("开始像素格子模式")
        self.btn_play_grid.setObjectName("Primary")
        self.btn_play_grid.setCursor(Qt.PointingHandCursor)
        self.btn_play_grid.clicked.connect(self.request_play_grid_game.emit)
        gl2.addWidget(self.btn_play_grid, alignment=Qt.AlignRight)
        v.addWidget(grid_games)

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
        self.gold_card["num"].setText(format_amount(s.inventory.gold))
        self.diam_card["num"].setText(format_amount(s.inventory.diamond))
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
        self.lbl_pending.setText(
            f"待领取：金币 {format_amount(pending_g)}，钻石 {format_amount(pending_d)}"
        )
        best_round = int(s.settings.get("pet_best_round", 0))
        self.lbl_ops.setText(f"全局操作数：{s.total_operations}  ｜  小动物最高回合：{best_round}")
        self._refresh_roll_history()

    def _refresh_roll_history(self) -> None:
        while self.history_layout.count():
            item = self.history_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self.state.roll_history:
            empty = QLabel("暂无开奖记录")
            empty.setObjectName("HistLine")
            self.history_layout.addWidget(empty)
            self.history_layout.addStretch(1)
            return

        for entry in self.state.roll_history:
            line = format_roll_history_line(entry, include_time=True)
            if entry.task_title:
                line = f"{line}  （{entry.task_title}）"
            lbl = QLabel(line)
            lbl.setObjectName("HistHit" if entry.hit else "HistMiss")
            lbl.setWordWrap(True)
            self.history_layout.addWidget(lbl)
        self.history_layout.addStretch(1)
