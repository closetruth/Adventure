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
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from src.models import AppState
from src.power_monitor import PowerMonitor
from src.task_manager import TaskManager
from src.widget import FloatingWidget

_app = QApplication.instance() or QApplication([])


class WidgetGeometryRegressionTest(unittest.TestCase):
    """回归：窗口 minimumSizeHint 必须 ≤ 600，点击/显示后窗口高度不变。"""

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
            widget.goal_tree._expanded_goal_ids.add(t.id)
        widget.refresh()
        widget.show()
        _app.processEvents()
        _app.processEvents()
        cls.widget = widget

    def test_show_does_not_grow_window_after_layout(self):
        """回归：显示后不得把窗口撑大（曾从 631 撑回 677）。"""
        widget = self.widget
        _app.processEvents()
        h_after_show = widget.height()
        widget.hide()
        widget.show()
        _app.processEvents()
        _app.processEvents()
        self.assertEqual(widget.height(), h_after_show, "show 后窗口高度不得变化")

    def test_click_tree_rows_does_not_resize_window(self):
        widget = self.widget
        tree = widget.goal_tree
        before_h = widget.height()
        self.assertLessEqual(
            widget.minimumSizeHint().height(),
            600,
            "窗口最小高度超过 600：布局会把窗口顶高（点击目标树回归）",
        )
        self.assertGreater(len(tree._tree_row_widgets), 0, "测试前提：应有子目标行")

        # 点击行 + 根行往返多次（完整走选择/详情面板重建链路）
        rows = list(tree._tree_row_widgets.values())
        roots = list(tree._goal_root_rows.values())
        for _ in range(3):
            for row in rows:
                QTest.mouseClick(row, Qt.LeftButton)
                _app.processEvents()
            for root in roots:
                QTest.mouseClick(root, Qt.LeftButton)
                _app.processEvents()

        self.assertEqual(widget.height(), before_h, "点击后窗口高度不得变化")
        self.assertLessEqual(widget.minimumSizeHint().height(), 600)

    def test_window_is_opaque(self):
        """不透明顶层窗，避免分层窗点穿。"""
        self.assertFalse(
            self.widget.testAttribute(Qt.WA_TranslucentBackground),
            "悬浮窗不得使用半透明背景",
        )

    def test_expand_goal_does_not_hide_tree(self):
        """回归：折叠后再点展开，根目标不得被裁成看不见。"""
        widget = self.widget
        tree = widget.goal_tree
        tree._expanded_goal_ids.clear()
        widget.refresh()
        _app.processEvents()
        _app.processEvents()
        roots_before = len(tree._goal_root_rows)
        self.assertGreater(roots_before, 0, "折叠后仍应有顶层目标")
        self.assertTrue(
            any(row.isVisible() for row in tree._goal_root_rows.values()),
            "折叠后顶层目标应可见",
        )
        folds = [
            btn
            for btn in tree.findChildren(QPushButton)
            if btn.objectName() == "TreeFoldBtn"
        ]
        self.assertTrue(folds, "应有展开按钮")
        QTest.mouseClick(folds[0], Qt.LeftButton)
        _app.processEvents()
        _app.processEvents()
        self.assertEqual(len(tree._goal_root_rows), roots_before)
        self.assertGreater(
            tree.subgoals_container.height(),
            40,
            "展开后树容器高度不得塌成看不见",
        )
        self.assertTrue(
            any(row.isVisible() for row in tree._goal_root_rows.values()),
            "展开后顶层目标应仍可见",
        )

    def test_refresh_light_does_not_rebuild_tree(self):
        """按键轻量刷新不得销毁树行，否则点击会落到已删除控件上。"""
        widget = self.widget
        tree = widget.goal_tree
        before = {key: id(row) for key, row in tree._tree_row_widgets.items()}
        self.assertTrue(before, "测试前提：应有子目标行")
        widget.note_operation()
        widget.refresh_light()
        _app.processEvents()
        after = {key: id(row) for key, row in tree._tree_row_widgets.items()}
        self.assertEqual(before, after)
        btn_ids = []
        lay = tree.goal_detail_btn_lay
        for i in range(lay.count()):
            item = lay.itemAt(i)
            w = item.widget() if item is not None else None
            if w is not None:
                btn_ids.append(id(w))
        widget.refresh_light()
        _app.processEvents()
        after_btns = []
        for i in range(lay.count()):
            item = lay.itemAt(i)
            w = item.widget() if item is not None else None
            if w is not None:
                after_btns.append(id(w))
        self.assertEqual(btn_ids, after_btns, "轻量刷新不得拆掉详情按钮")

    def test_drag_then_tree_still_clickable(self):
        """回归：系统拖动结束后目标树仍应能点。"""
        from PySide6.QtCore import QPoint

        widget = self.widget
        handle = widget.findChild(QWidget, "DragHandle")
        self.assertIsNotNone(handle, "测试前提：应有顶栏拖动手柄")
        QTest.mousePress(handle, Qt.LeftButton, pos=QPoint(8, 8))
        _app.processEvents()
        QTest.mouseRelease(handle, Qt.LeftButton, pos=QPoint(8, 8))
        widget.end_user_move()
        _app.processEvents()
        self.assertFalse(widget._window_dragging)
        self.assertIsNone(QWidget.mouseGrabber())

        row = next(iter(widget.goal_tree._tree_row_widgets.values()))
        QTest.mouseClick(row, Qt.LeftButton)
        _app.processEvents()
        self.assertTrue(
            bool(widget.goal_tree._selected_task_id),
            "拖窗后点击目标树应能选中",
        )


class RollBarPaintRegressionTest(unittest.TestCase):
    """回归：paintEvent 不得再排队 update，否则半透明置顶窗会卡死。"""

    def test_paint_does_not_requeue_update(self):
        from src.ui_roll_bar import SegmentedRollBar

        bar = SegmentedRollBar()
        bar.set_cycle(2, 8, ["#6c8cff"] * 8)
        bar.resize(200, 18)
        bar.show()
        _app.processEvents()

        calls = {"n": 0}
        real_update = bar.update

        def wrapped(*args, **kwargs):
            calls["n"] += 1
            return real_update(*args, **kwargs)

        bar.update = wrapped
        bar.pulse_operation()
        after_pulse = calls["n"]
        self.assertGreaterEqual(after_pulse, 1)
        bar.repaint()
        self.assertEqual(
            calls["n"],
            after_pulse,
            "paintEvent 不得再调用 update()（会造成半透明窗重绘风暴）",
        )
        bar.hide()
        bar.deleteLater()


if __name__ == "__main__":
    unittest.main()
