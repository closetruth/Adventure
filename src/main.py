"""Adventure 应用入口。

启动流程:
1. 加载本地数据 (AppState);
2. 启动全局键鼠监听 (pynput, 后台线程);
3. 创建主悬浮 Widget；
4. 主线程通过 Qt 信号接收监听线程上抛的「操作」事件，统一更新数据 & UI。
"""
from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .game_launcher import launch_pet_arena
from .input_monitor import InputMonitor
from .inventory_dialog import InventoryDialog
from .models import AppState
from .reward_system import maybe_roll
from .storage import load_state, save_state
from .task_dialog import TaskDialog
from .task_manager import TaskManager
from .widget import FloatingWidget


class OpBridge(QObject):
    """把后台线程的操作事件搬运到 Qt 主线程。"""
    op_happened = Signal()


class Application(QObject):
    def __init__(self, qt_app: QApplication):
        # 高 DPI 处理 (PySide6 默认即开启)
        self.qt_app = qt_app
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.qt_app.setApplicationName("Adventure")
        super().__init__()

        self.state: AppState = load_state()
        self.manager = TaskManager(self.state)

        self.widget = FloatingWidget(self.state, self.manager)
        self.widget.request_task_dialog.connect(self.show_task_dialog)
        self.widget.request_inventory_dialog.connect(self.show_inventory)
        self.widget.request_quit.connect(self.quit)

        # 桥接全局输入事件
        self.bridge = OpBridge()
        self.bridge.op_happened.connect(self._on_operation, Qt.QueuedConnection)
        self.monitor = InputMonitor(on_op=self.bridge.op_happened.emit)
        if not self.monitor.available():
            QMessageBox.warning(
                None, "Adventure",
                "未检测到 pynput，全局键鼠监听已禁用。\n请先运行 `pip install pynput` 后再启动。",
            )
        else:
            self.monitor.start()

        # 周期性自动存档
        self.save_timer = QTimer(self)
        self.save_timer.setInterval(15_000)
        self.save_timer.timeout.connect(lambda: save_state(self.state))
        self.save_timer.start()

        # 系统托盘
        self.tray = self._build_tray()

        # 引用子窗口避免被 GC
        self._task_dialog = None
        self._inv_dialog = None

        # 让 Ctrl+C 在终端启动时也能干净退出
        try:
            signal.signal(signal.SIGINT, lambda *_: self.quit())
        except Exception:
            pass

        self._place_widget_initial()
        self.widget.show()

    # ---------- 系统托盘 ----------
    def _build_tray(self) -> QSystemTrayIcon:
        icon = self._make_icon()
        tray = QSystemTrayIcon(icon, parent=self)
        tray.setToolTip("Adventure - 任务与奖励小部件")
        menu = QMenu()

        act_show = QAction("显示悬浮窗", menu)
        act_show.triggered.connect(self._show_widget)
        menu.addAction(act_show)

        act_tasks = QAction("任务管理", menu)
        act_tasks.triggered.connect(self.show_task_dialog)
        menu.addAction(act_tasks)

        act_inv = QAction("奖励背包", menu)
        act_inv.triggered.connect(self.show_inventory)
        menu.addAction(act_inv)

        menu.addSeparator()
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_quit)

        self._tray_menu = menu  # 保留引用以防 GC
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _make_icon(self) -> QIcon:
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#3a5cff"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(2, 2, 60, 60, 14, 14)
        p.setPen(QColor("#ffffff"))
        f = QFont("Segoe UI", 28, QFont.Bold)
        p.setFont(f)
        p.drawText(pix.rect(), Qt.AlignCenter, "A")
        p.end()
        return QIcon(pix)

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._show_widget()

    def _show_widget(self) -> None:
        self.widget.showNormal()
        self.widget.raise_()
        self.widget.activateWindow()

    # ---------- 初始位置 ----------
    def _place_widget_initial(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        # 默认放置到屏幕右上角，留出 24px 边距
        self.widget.adjustSize()
        size = self.widget.sizeHint()
        x = geo.right() - size.width() - 24
        y = geo.top() + 80
        self.widget.move(x, y)

    # ---------- 事件处理 ----------
    def _on_operation(self) -> None:
        self.state.total_operations += 1
        reward = maybe_roll(self.state)
        self.manager.record_operation(reward)
        # 即时刷新（保持成本低）
        self.widget.refresh()
        if self._task_dialog is not None and self._task_dialog.isVisible():
            # 任务列表里只是计数变了不必每次都重排，但小数据量下也无所谓
            self._task_dialog.refresh()
        if self._inv_dialog is not None and self._inv_dialog.isVisible():
            self._inv_dialog.refresh()

    # ---------- 子窗口 ----------
    def show_task_dialog(self) -> None:
        if self._task_dialog is None:
            self._task_dialog = TaskDialog(self.state, self.manager, parent=self.widget)
            self._task_dialog.state_changed.connect(self.widget.refresh)
        self._task_dialog.refresh()
        self._task_dialog.show()
        self._task_dialog.raise_()
        self._task_dialog.activateWindow()

    def show_inventory(self) -> None:
        if self._inv_dialog is None:
            self._inv_dialog = InventoryDialog(self.state, parent=self.widget)
            self._inv_dialog.request_play_game.connect(self.play_pet_arena)
        self._inv_dialog.refresh()
        self._inv_dialog.show()
        self._inv_dialog.raise_()
        self._inv_dialog.activateWindow()

    def play_pet_arena(self) -> None:
        """暂停主窗交互感，启动 pygame 子进程并结算。"""
        ok, msg, _result = launch_pet_arena(self.state)
        save_state(self.state)
        self.widget.refresh()
        if self._inv_dialog is not None and self._inv_dialog.isVisible():
            self._inv_dialog.refresh()
        if ok:
            QMessageBox.information(self.widget, "竞技场结算", msg)
        else:
            QMessageBox.warning(self.widget, "无法开始", msg)

    # ---------- 退出 ----------
    def quit(self) -> None:
        try:
            self.monitor.stop()
        except Exception:
            pass
        try:
            save_state(self.state)
        except Exception:
            pass
        self.qt_app.quit()

    def run(self) -> int:
        return self.qt_app.exec()


def main() -> int:
    qt_app = QApplication(sys.argv)
    app = Application(qt_app)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
