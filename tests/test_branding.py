"""品牌常量冒烟测试。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.branding import APP_NAME, APP_NAME_ZH, TRAY_TOOLTIP, window_title


class BrandingTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(APP_NAME, "AimLoot")
        self.assertEqual(APP_NAME_ZH, "目标奖励管理工具")
        self.assertEqual(TRAY_TOOLTIP, "AimLoot - 目标奖励管理工具")

    def test_window_title(self):
        self.assertEqual(window_title(), "AimLoot")
        self.assertEqual(window_title("目标管理"), "目标管理 - AimLoot")


if __name__ == "__main__":
    unittest.main()
