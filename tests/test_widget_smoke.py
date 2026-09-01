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

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from src.models import AppState, Reward
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

    def test_refresh_stats_does_not_rebuild_tree(self):
        """按键轻量刷新不得销毁树行，否则点击会落到已删除控件上。"""
        widget = self.widget
        tree = widget.goal_tree
        before = {key: id(row) for key, row in tree._tree_row_widgets.items()}
        self.assertTrue(before, "测试前提：应有子目标行")
        widget.note_operation()
        widget.refresh_stats()
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
        widget.refresh_stats()
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
        self.assertFalse(widget.is_user_moving())
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


class RollBarInitRegressionTest(unittest.TestCase):
    """回归：启动时进度条必须用存档进度，不能停在默认 0/10。"""

    def test_create_uses_saved_roll_progress(self):
        from src.models import AppState
        from src.power_monitor import PowerMonitor
        from src.reward_system import roll_progress
        from src.task_manager import TaskManager

        state = AppState()
        state.total_operations = 4
        state.last_roll_at = 0
        state.roll_runtime.next_roll_at = 10
        state.roll_runtime.roll_span = 10
        widget = FloatingWidget(state, TaskManager(state, PowerMonitor()))
        progress, span = roll_progress(state)
        self.assertEqual(progress, 4)
        self.assertEqual(widget.roll_bar._progress, progress)
        self.assertEqual(widget.roll_bar._span, span)
        self.assertTrue(widget.roll_bar._chance_label)
        widget.close()
        widget.deleteLater()


class FillFlashIntervalTests(unittest.TestCase):
    def test_start_does_not_flash(self):
        from src.ui_roll_bar import fill_flash_interval_ms

        self.assertIsNone(fill_flash_interval_ms(0.0))
        self.assertIsNone(fill_flash_interval_ms(0.19))

    def test_closer_to_end_is_faster(self):
        from src.ui_roll_bar import fill_flash_interval_ms

        mid = fill_flash_interval_ms(0.5)
        late = fill_flash_interval_ms(0.95)
        self.assertIsNotNone(mid)
        self.assertIsNotNone(late)
        self.assertGreater(mid, late)

    def test_full_is_near_180ms(self):
        from src.ui_roll_bar import fill_flash_interval_ms

        full = fill_flash_interval_ms(1.0)
        self.assertIsNotNone(full)
        self.assertGreaterEqual(full, 160)
        self.assertLessEqual(full, 180)


class FillFlashColorTests(unittest.TestCase):
    def test_legend_hot_is_lighter_than_rest(self):
        from src.ui_roll_bar import _RARITY_LEGEND, fill_flash_hex

        rest = QColor(fill_flash_hex(_RARITY_LEGEND, flash_on=False))
        hot = QColor(fill_flash_hex(_RARITY_LEGEND, flash_on=True))
        self.assertNotEqual(rest.name(), hot.name())
        self.assertGreater(hot.lightness(), rest.lightness())

    def test_rare_hot_is_not_old_blue(self):
        from src.ui_roll_bar import _RARITY_RARE, fill_flash_hex

        hot = fill_flash_hex(_RARITY_RARE, flash_on=True)
        self.assertNotEqual(hot.lower(), "#b8d0ff")
        self.assertEqual(hot.lower(), "#dce8ff")


class EaseChestClickTests(unittest.TestCase):
    """缓动条左键应能点到宝箱，不能被全局拖动滤镜吃掉。"""

    def test_click_reached_chest_emits_claimed(self):
        from src.ui_roll_bar import EasedProgressBar, _ease_span_for_cycle

        bar = EasedProgressBar()
        bar.resize(280, 18)
        bar.show()
        _app.processEvents()
        bar.set_progress(_ease_span_for_cycle(0), freeze_at_end=True)
        _app.processEvents()
        got: list[int] = []
        bar.chest_claimed.connect(lambda i, _r: got.append(i))
        QTest.mouseClick(bar, Qt.LeftButton, pos=bar.chest_center_local(0))
        _app.processEvents()
        self.assertEqual(got, [0])
        bar.close()
        bar.deleteLater()

    def test_move_filter_does_not_eat_eased_bar_clicks(self):
        from src.ui_roll_bar import EasedProgressBar
        from src.ui_window_drag import SystemMoveFilter

        class Host:
            def __init__(self) -> None:
                self.moves = 0

            def begin_user_move(self) -> None:
                self.moves += 1

        root = QWidget()
        bar = EasedProgressBar(root)
        bar.setGeometry(0, 0, 200, 18)
        host = Host()
        SystemMoveFilter(host).attach(root)
        root.show()
        bar.show()
        _app.processEvents()
        QTest.mouseClick(bar, Qt.LeftButton, pos=QPoint(10, 9))
        _app.processEvents()
        self.assertEqual(host.moves, 0)
        root.close()
        root.deleteLater()


class CurrencyCountUpWidgetTests(unittest.TestCase):
    def test_kick_starts_timer_and_moves_display(self):
        state = AppState()
        manager = TaskManager(state, PowerMonitor())
        widget = FloatingWidget(state, manager)
        widget.show()
        _app.processEvents()
        start = widget._currency.gold
        state.inventory.gold += 2.0
        widget.kick_currency_display()
        self.assertTrue(widget._currency_timer.isActive())
        QTest.qWait(400)
        self.assertGreater(widget._currency.gold, start)
        self.assertLess(widget._currency.gold, state.inventory.gold)
        widget.close()
        widget.deleteLater()

    def test_pending_roll_moves_global_display(self):
        state = AppState()
        manager = TaskManager(state, PowerMonitor())
        widget = FloatingWidget(state, manager)
        widget.show()
        _app.processEvents()
        task = manager.create("父")
        leaf = manager.add_subtask(task.id, "叶子")
        self.assertIsNotNone(leaf)
        start_g, _ = state.visible_gold_diamond()
        widget._currency.snap_to(start_g, state.inventory.diamond)
        leaf.pending_rewards.append(Reward(gold=2.0))
        widget.kick_currency_display()
        self.assertTrue(widget._currency_timer.isActive())
        QTest.qWait(400)
        self.assertGreater(widget._currency.gold, start_g)
        self.assertLess(widget._currency.gold, start_g + 2.0)
        self.assertGreater(widget.gold_reel.amount(), start_g)
        self.assertLess(widget.gold_reel.amount(), start_g + 2.0)
        widget.close()
        widget.deleteLater()

    def test_detail_reel_snaps_and_chases_earned(self):
        state = AppState()
        manager = TaskManager(state, PowerMonitor())
        widget = FloatingWidget(state, manager)
        widget.show()
        _app.processEvents()
        task = manager.create("父")
        leaf = manager.add_subtask(task.id, "叶子")
        self.assertIsNotNone(leaf)
        leaf.earned_gold = 1.0
        tree = widget.goal_tree
        tree._expanded_goal_ids.add(task.id)
        widget.refresh()
        _app.processEvents()
        tree._on_tree_select(task.id, leaf.id)
        _app.processEvents()
        self.assertTrue(tree.goal_detail_panel.isVisible())
        self.assertAlmostEqual(tree.detail_gold_reel.amount(), 1.0)
        leaf.earned_gold += 2.0
        widget.kick_currency_display()
        self.assertTrue(widget._currency_timer.isActive())
        QTest.qWait(400)
        shown = tree.detail_gold_reel.amount()
        self.assertGreater(shown, 1.0)
        self.assertLess(shown, 3.0)
        widget.close()
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
