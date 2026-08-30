"""奖励背包布局回归：窗口不得被内容撑出屏幕，底部小游戏必须能看见。"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QScrollArea

from src.inventory_dialog import InventoryDialog
from src.models import AppState

_app = QApplication.instance() or QApplication([])


class InventoryDialogLayoutTest(unittest.TestCase):
    def setUp(self):
        self.dlg = InventoryDialog(AppState())
        self.dlg.show()
        _app.processEvents()
        _app.processEvents()

    def tearDown(self):
        self.dlg.close()
        self.dlg.deleteLater()
        _app.processEvents()

    def test_dialog_fits_available_screen(self):
        """字母网格 + 三块游戏卡曾把窗口撑到 1022x1047，底部游戏被裁掉。"""
        avail = self.dlg.screen().availableGeometry()
        self.assertLessEqual(
            self.dlg.width(),
            avail.width(),
            f"背包宽 {self.dlg.width()} 超出可用屏宽 {avail.width()}",
        )
        self.assertLessEqual(
            self.dlg.height(),
            avail.height(),
            f"背包高 {self.dlg.height()} 超出可用屏高 {avail.height()}",
        )
        self.assertLessEqual(self.dlg.width(), 640)
        self.assertLessEqual(self.dlg.height(), 720)

    def test_game_buttons_visible_in_window(self):
        """小游戏入口固定在窗口底部，打开背包即可看见，不必先滚过字母网格。"""
        dlg = self.dlg
        for btn in (dlg.btn_play, dlg.btn_play_grid, dlg.btn_play_word):
            self.assertTrue(btn.isVisible(), f"{btn.text()} 应存在")
            mapped = btn.mapTo(dlg, btn.rect().center())
            self.assertTrue(
                dlg.rect().contains(mapped),
                f"{btn.text()} 中心 {mapped} 不在窗口 {dlg.rect()} 内",
            )

        scroll = dlg.findChild(QScrollArea, "InvBodyScroll")
        self.assertIsNotNone(scroll, "上方内容需要滚动区，否则窗口会被撑出屏幕")

