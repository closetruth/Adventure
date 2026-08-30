"""奖励背包对话框：展示玩家拥有的金币 / 钻石、宝箱解锁与字母收集。"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import chest_opening
from .models import AppState, TaskStatus
from .ui_roll_bar import CHEST_RARITY_COLORS, CHEST_RARITY_NAMES
from .ui_styles import (
    ACCENT,
    ACCENT_HOVER,
    BG_CARD,
    BG_DIALOG,
    FONT_FAMILY,
    TEXT_PRIMARY,
)
from .ui_text import format_amount, format_roll_history_line


INVENTORY_DIALOG_QSS = f"""
QDialog {{ background-color: {BG_DIALOG}; color: {TEXT_PRIMARY}; }}
QLabel {{ color: {TEXT_PRIMARY}; font-family: {FONT_FAMILY}; }}
QFrame#Card {{
    background-color: {BG_CARD};
    border: 1px solid #2e3040;
    border-radius: 12px;
}}
QLabel#Big {{ font-size: 28px; font-weight: 800; }}
QLabel#Cap {{ font-size: 15px; font-weight: 700; }}
QLabel#Section {{ color: #e0e4f0; font-size: 14px; font-weight: 700; }}
QLabel#StatLine {{ color: #c8ccd8; font-size: 13px; font-weight: 500; }}
QLabel#HistLine {{ color: #b8bcc8; font-size: 12px; font-weight: 500; }}
QLabel#HistHit {{ color: #ffd54f; font-size: 12px; font-weight: 600; }}
QLabel#HistMiss {{ color: #8a909e; font-size: 12px; font-weight: 500; }}
QLabel#ChestLine {{ color: #d0d4e0; font-size: 13px; font-weight: 600; }}
QLabel#ChestEmpty {{ color: #8a909e; font-size: 12px; font-weight: 500; }}
QLabel#LetterCell {{ font-size: 12px; font-weight: 700; }}
QLabel#LetterEmpty {{ color: #6a7080; font-size: 10px; font-weight: 600; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QPushButton {{
    background-color: #2b3050; color: {TEXT_PRIMARY};
    border: 1px solid #3a4070; border-radius: 6px;
    padding: 6px 12px;
    font-size: 13px;
}}
QPushButton:hover {{ background-color: #3a4070; }}
QPushButton#Primary {{ background-color: {ACCENT}; border-color: {ACCENT}; font-weight: 700; }}
QPushButton#Primary:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#OpenReady {{ background-color: #3f7a4a; border-color: #4f9a5c; font-weight: 700; }}
QPushButton#OpenReady:hover {{ background-color: #4f9a5c; }}
"""


class _FitWidthScroll(QScrollArea):
    """sizeHint 不跟随内部内容宽度，避免把背包窗口撑出屏幕。"""

    def sizeHint(self) -> QSize:
        return QSize(200, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 80)


class InventoryDialog(QDialog):
    request_play_game = Signal()
    request_play_grid_game = Signal()
    request_play_word_game = Signal()
    request_start_unlock = Signal(int)  # 稀有度
    request_open_chest = Signal(int)    # 稀有度

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("奖励背包 - Adventure")
        self.setStyleSheet(INVENTORY_DIALOG_QSS)
        self._build()
        self._apply_dialog_size()
        self.refresh()

        # 1s 定时器刷新宝箱解锁倒计时
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh_chest_lines)
        self._timer.start()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)

    def _apply_dialog_size(self) -> None:
        """限制在可用屏内：QDialog 默认按内容 sizeHint 撑满，会裁掉底部游戏。"""
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail_w, avail_h = 800, 800
        if screen is not None:
            g = screen.availableGeometry()
            avail_w, avail_h = g.width(), g.height()
        w = min(560, max(420, avail_w - 48))
        h = min(640, max(360, avail_h - 80))
        self.setMinimumSize(min(420, w), min(360, h))
        self.setMaximumSize(max(w, avail_w - 24), max(h, avail_h - 40))
        self.resize(w, h)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # QDialog 默认 SetMinAndMaxSize，会按滚动区内内容把窗口撑出屏幕。
        outer.setSizeConstraint(QLayout.SetNoConstraint)

        scroll = _FitWidthScroll()
        scroll.setObjectName("InvBodyScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        v.addWidget(self._section_label("当前持有"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.gold_card = self._make_card("金币", "#ffd54f", "GoldCap")
        self.diam_card = self._make_card("钻石", "#7dd3fc", "DiamCap")
        row.addWidget(self.gold_card["frame"])
        row.addWidget(self.diam_card["frame"])
        v.addLayout(row)

        v.addWidget(self._section_label("未开宝箱"))
        self.chest_card = self._make_chest_card()
        v.addWidget(self.chest_card["frame"])

        v.addWidget(self._section_label("字母收集"))
        self.letters_card = self._make_letters_card()
        v.addWidget(self.letters_card["frame"])

        v.addWidget(self._section_label("数据统计"))
        self.stat_card = self._make_stat_card()
        v.addWidget(self.stat_card["frame"])

        v.addWidget(self._section_label("开奖历史"))
        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setMaximumHeight(96)
        self.history_inner = QWidget()
        self.history_layout = QVBoxLayout(self.history_inner)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(4)
        self.history_scroll.setWidget(self.history_inner)
        v.addWidget(self.history_scroll)
        v.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # 小游戏钉在窗口底部，不随字母/历史一起滚出可视区。
        footer = QWidget()
        fv = QVBoxLayout(footer)
        fv.setContentsMargins(14, 8, 14, 12)
        fv.setSpacing(6)
        fv.addWidget(self._section_label("小游戏"))
        games = QFrame()
        games.setObjectName("Card")
        gl = QVBoxLayout(games)
        gl.setContentsMargins(12, 8, 12, 8)
        gl.setSpacing(6)
        self.btn_play = self._add_game_row(
            gl, "小动物竞技场", "入场 10 金币", "开始",
            self.request_play_game,
        )
        self.btn_play_grid = self._add_game_row(
            gl, "像素格子战场", "入场 12 金币", "开始",
            self.request_play_grid_game,
        )
        self.btn_play_word = self._add_game_row(
            gl, "词汇自走棋", "入场 10 金币", "开始",
            self.request_play_word_game,
        )
        fv.addWidget(games)
        outer.addWidget(footer)

    def _add_game_row(
        self,
        parent: QVBoxLayout,
        title: str,
        cost: str,
        button_text: str,
        signal: Signal,
    ) -> QPushButton:
        row = QHBoxLayout()
        row.setSpacing(8)
        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel(title)
        fee = QLabel(cost)
        fee.setObjectName("StatLine")
        col.addWidget(name)
        col.addWidget(fee)
        row.addLayout(col, 1)
        btn = QPushButton(button_text)
        btn.setObjectName("Primary")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(signal.emit)
        row.addWidget(btn)
        parent.addLayout(row)
        return btn

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("Section")
        return lbl

    def _make_card(self, caption: str, color: str, cap_name: str) -> dict:
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
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

    def _make_chest_card(self) -> dict:
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        self.lbl_chests_empty = QLabel("暂无未开宝箱")
        self.lbl_chests_empty.setObjectName("ChestEmpty")
        lay.addWidget(self.lbl_chests_empty)

        self.chest_lines: list[QLabel] = []
        self.chest_hint: list[QLabel] = []
        self.chest_btns: list[QPushButton] = []
        for i, (name, color) in enumerate(zip(CHEST_RARITY_NAMES, CHEST_RARITY_COLORS)):
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel()
            lbl.setObjectName("ChestLine")
            lbl.setStyleSheet(f"color: {color};")
            lbl.hide()
            row.addWidget(lbl)
            hint = QLabel()
            hint.setObjectName("StatLine")
            hint.setStyleSheet("font-size: 12px;")
            hint.hide()
            row.addWidget(hint)
            row.addStretch(1)
            btn = QPushButton("解锁")
            btn.setCursor(Qt.PointingHandCursor)
            btn.hide()
            # 按钮只连一个分发 handler，按当前状态发对应信号
            btn.clicked.connect(lambda _=False, r=i: self._on_chest_row_clicked(r))
            row.addWidget(btn)
            lay.addLayout(row)
            self.chest_lines.append(lbl)
            self.chest_hint.append(hint)
            self.chest_btns.append(btn)
        return {"frame": frame}

    def _on_chest_row_clicked(self, rarity: int) -> None:
        """点击状态按钮：待解锁 → 开始解锁；就绪 → 开箱；解锁中 → 无动作。"""
        chest = next(
            (c for c in self.state.inventory.chests if c.rarity == rarity),
            None,
        )
        if chest is None:
            return
        if chest.unlock_started_at is None:
            self.request_start_unlock.emit(rarity)
        elif chest_opening.is_ready(chest):
            self.request_open_chest.emit(rarity)
        # 解锁中：点击无动作，等待倒计时结束

    def _refresh_chest_lines(self) -> None:
        """宝箱行：数量 + 状态按钮/倒计时。由 refresh() 与 1s 定时器调用。"""
        s = self.state
        counts = s.inventory.chest_counts_by_rarity()
        total_chests = sum(counts)
        self.lbl_chests_empty.setVisible(total_chests == 0)

        by_rarity: list[list] = [[] for _ in range(5)]
        for c in s.inventory.chests:
            by_rarity[c.rarity].append(c)

        can_unlock = chest_opening.slots_available(s)

        for i, name in enumerate(CHEST_RARITY_NAMES):
            n = counts[i]
            lbl = self.chest_lines[i]
            btn = self.chest_btns[i]
            hint = self.chest_hint[i]
            if n == 0:
                lbl.hide()
                btn.hide()
                hint.hide()
                continue

            chest = by_rarity[i][0]
            if chest.unlock_started_at is None:
                state_str = "待解锁"
                btn.setText("解锁")
                btn.setObjectName("")
                btn.setEnabled(can_unlock)
                btn.setToolTip("解锁槽已满" if not can_unlock else "开始解锁倒计时")
                btn.show()
                hint.hide()
            elif chest_opening.is_ready(chest):
                state_str = "点击开箱"
                btn.setText("开箱")
                btn.setObjectName("OpenReady")
                btn.setEnabled(True)
                btn.show()
                hint.hide()
            else:
                rem = chest_opening.remaining_seconds(chest)
                h, m_, sec = rem // 3600, (rem % 3600) // 60, rem % 60
                state_str = f"解锁中 {h:02d}:{m_:02d}:{sec:02d}"
                btn.hide()
                hint.setText(state_str)
                hint.show()

            lbl.setText(f"{name} × {n}  ·  {state_str}")
            lbl.show()
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _make_letters_card(self) -> dict:
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        self.lbl_letters_title = QLabel()
        self.lbl_letters_title.setObjectName("StatLine")
        lay.addWidget(self.lbl_letters_title)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(1)
        grid.setVerticalSpacing(2)
        self.letter_cells: list[QLabel] = []
        for rar in range(5):
            head = QLabel(CHEST_RARITY_NAMES[rar])
            head.setObjectName("LetterCell")
            head.setStyleSheet(f"color: {CHEST_RARITY_COLORS[rar]};")
            grid.addWidget(head, rar, 0)
            for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
                cell = QLabel(ch)
                cell.setObjectName("LetterCell")
                cell.setAlignment(Qt.AlignCenter)
                cell.setFixedSize(16, 20)
                cell.setStyleSheet("border-radius: 3px;")
                grid.addWidget(cell, rar, i + 1)
                self.letter_cells.append(cell)

        letters_scroll = _FitWidthScroll()
        letters_scroll.setWidgetResizable(True)
        letters_scroll.setFrameShape(QFrame.NoFrame)
        letters_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        letters_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        letters_scroll.setFixedHeight(5 * 20 + 2 * 4 + 18)
        letters_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        letters_scroll.setWidget(grid_host)
        lay.addWidget(letters_scroll)
        return {"frame": frame}

    def _refresh_letters(self) -> None:
        s = self.state
        collected = s.inventory.letters_collected_count()
        self.lbl_letters_title.setText(f"已收集 {collected}/130（字母 × 稀有度）")
        for rar in range(5):
            for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
                cell = self.letter_cells[rar * 26 + i]
                counts = s.inventory.letters.get(ch)
                n = counts[rar] if counts else 0
                if n > 0:
                    # 字母 + 数量分两行,稀有度色边框
                    cell.setText(f"{ch}\n×{n}")
                    cell.setStyleSheet(
                        f"background-color: #252838; color: {CHEST_RARITY_COLORS[rar]};"
                        f"border: 1px solid {CHEST_RARITY_COLORS[rar]}; border-radius: 3px;"
                        "font-size: 9px; font-weight: 700; line-height: 1.0;"
                    )
                    cell.setToolTip(f"{ch} · {CHEST_RARITY_NAMES[rar]} × {n}")
                else:
                    cell.setText("·")
                    cell.setStyleSheet(
                        "color: #6a7080; font-size: 10px; font-weight: 600;"
                    )
                    cell.setToolTip(f"未收集：{ch} · {CHEST_RARITY_NAMES[rar]}")

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
        self._refresh_chest_lines()
        self._refresh_letters()
        self.lbl_ops.setText(f"全局操作数：{s.total_operations}")
        active = [t for t in s.tasks if t.status == TaskStatus.ACTIVE]
        done = [t for t in s.tasks if t.status == TaskStatus.COMPLETED]
        self.lbl_tasks_active.setText(f"进行中目标：{len(active)}")
        self.lbl_tasks_done.setText(f"已完成目标：{len(done)}")
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
