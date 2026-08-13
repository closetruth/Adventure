"""离屏 UI 回归测试：点击目标树行不得改变悬浮窗尺寸。

历史 bug：点击目标树查看区域会把整个悬浮窗顶高（详情面板换行文本 +
按钮组切换改变布局最小高度）。此测试在 offscreen 平台跑真实点击链路，
不需要真实窗口。
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.models import AppState
from src.power_monitor import PowerMonitor
from src.task_manager import TaskManager
from src.widget import FloatingWidget

_app = QApplication.instance() or QApplication([])


class WidgetGeometryRegressionTest(unittest.TestCase):
    """回归：窗口 minimumSizeHint 必须 ≤ 600，点击后窗口高度不变。"""

    @classmethod
    def setUpClass(cls):
        state = AppState()
        manager = TaskManager(state, PowerMonitor())
        widget = FloatingWidget(state, manager)
        task = manager.create("学习 Qt 小部件布局与渲染管线性能优化")
        manager.add_subtask(task.id, "阅读 PySide6 官方文档布局章节并做笔记", target_minutes=30)
        manager.add_subtask(task.id, "重构目标树区域并修复窗口变高的问题", target_minutes=45)
        manager.create("健身")
        manager.create("读书笔记整理与知识体系构建复盘总结")
        for t in state.tasks:
            widget._expanded_goal_ids.add(t.id)
        widget.refresh()
        widget.show()
        _app.processEvents()
        _app.processEvents()
        cls.widget = widget

    def test_click_tree_rows_does_not_resize_window(self):
        widget = self.widget
        before_h = widget.height()
        self.assertLessEqual(
            widget.minimumSizeHint().height(),
            600,
            "窗口最小高度超过 600：布局会把窗口顶高（点击目标树回归）",
        )
        self.assertGreater(len(widget._tree_row_widgets), 0, "测试前提：应有子目标行")

        # 点击行 + 根行往返多次（完整走选择/详情面板重建链路）
        rows = list(widget._tree_row_widgets.values())
        roots = list(widget._goal_root_rows.values())
        for _ in range(3):
            for row in rows:
                QTest.mouseClick(row, Qt.LeftButton)
                _app.processEvents()
            for root in roots:
                QTest.mouseClick(root, Qt.LeftButton)
                _app.processEvents()

        self.assertEqual(widget.height(), before_h, "点击后窗口高度不得变化")
        self.assertLessEqual(widget.minimumSizeHint().height(), 600)


if __name__ == "__main__":
    unittest.main()
