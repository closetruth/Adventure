"""点到虚拟机窗口也要计入操作。"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.input_monitor import InputMonitor
from src.vm_detect import grabbed_input_should_count, is_vm_executable


class VmExecutableTests(unittest.TestCase):
    def test_vmware_and_vbox_are_vm(self):
        self.assertTrue(is_vm_executable("vmware.exe"))
        self.assertTrue(is_vm_executable("VMware-vmx.EXE"))
        self.assertTrue(is_vm_executable("vmware-remotemks.exe"))
        self.assertTrue(is_vm_executable("VirtualBoxVM.exe"))
        self.assertTrue(is_vm_executable("vmconnect.exe"))
        self.assertTrue(is_vm_executable("WindowsSandboxClient.exe"))
        self.assertTrue(is_vm_executable("qemu-system-x86_64.exe"))

    def test_normal_apps_are_not_vm(self):
        self.assertFalse(is_vm_executable("chrome.exe"))
        self.assertFalse(is_vm_executable("Code.exe"))
        self.assertFalse(is_vm_executable("python.exe"))
        self.assertFalse(is_vm_executable("mstsc.exe"))
        self.assertFalse(is_vm_executable("CefRendererProcess.exe"))
        self.assertFalse(is_vm_executable(""))

    def test_yingyongbao_androws_is_vm(self):
        self.assertTrue(is_vm_executable("AndrowsFG.exe"))
        self.assertTrue(is_vm_executable("Androws.exe"))
        self.assertTrue(is_vm_executable("AndrowsStore.exe"))
        self.assertTrue(is_vm_executable("AndrowsVm.exe"))
        self.assertTrue(is_vm_executable("ABoxHeadless.exe"))
        self.assertTrue(
            is_vm_executable(
                r"C:\Program Files\Tencent\Androws\Application\5.10.7100.6351\renderer\AndrowsFG.exe"
            )
        )
        self.assertTrue(
            is_vm_executable(
                r"C:\Program Files\Tencent\Androws\Application\5.10.7100.6351\CefRendererProcess.exe"
            )
        )


class GrabbedInputFallbackTests(unittest.TestCase):
    def test_counts_when_vm_click_not_seen_by_async_key(self):
        self.assertTrue(
            grabbed_input_should_count(
                vm_active=True,
                last_tick=100,
                prev_tick=90,
                cursor=(10, 10),
                prev_cursor=(10, 11),
                already_counted=False,
                now_mono=1.0,
                last_op_mono=0.0,
                cooldown_sec=0.25,
            )
        )

    def test_skips_mouse_move_inside_vm(self):
        self.assertFalse(
            grabbed_input_should_count(
                vm_active=True,
                last_tick=100,
                prev_tick=90,
                cursor=(40, 10),
                prev_cursor=(10, 10),
                already_counted=False,
                now_mono=1.0,
                last_op_mono=0.0,
                cooldown_sec=0.25,
            )
        )

    def test_skips_when_not_in_vm(self):
        self.assertFalse(
            grabbed_input_should_count(
                vm_active=False,
                last_tick=100,
                prev_tick=90,
                cursor=(10, 10),
                prev_cursor=(10, 10),
                already_counted=False,
                now_mono=1.0,
                last_op_mono=0.0,
                cooldown_sec=0.25,
            )
        )

    def test_skips_when_async_key_already_counted(self):
        self.assertFalse(
            grabbed_input_should_count(
                vm_active=True,
                last_tick=100,
                prev_tick=90,
                cursor=(10, 10),
                prev_cursor=(10, 10),
                already_counted=True,
                now_mono=1.0,
                last_op_mono=0.0,
                cooldown_sec=0.25,
            )
        )

    def test_skips_first_sample_without_baseline(self):
        self.assertFalse(
            grabbed_input_should_count(
                vm_active=True,
                last_tick=100,
                prev_tick=None,
                cursor=(10, 10),
                prev_cursor=None,
                already_counted=False,
                now_mono=1.0,
                last_op_mono=-1.0,
                cooldown_sec=0.25,
            )
        )

    def test_cooldown_prevents_hold_repeat_flood(self):
        self.assertFalse(
            grabbed_input_should_count(
                vm_active=True,
                last_tick=100,
                prev_tick=90,
                cursor=(10, 10),
                prev_cursor=(10, 10),
                already_counted=False,
                now_mono=1.05,
                last_op_mono=1.0,
                cooldown_sec=0.25,
            )
        )

    def test_skips_lastinput_up_after_recent_count(self):
        """一次点击：按下已计数，松开也会刷新 LastInput，不得再记。"""
        self.assertFalse(
            grabbed_input_should_count(
                vm_active=True,
                last_tick=200,
                prev_tick=100,
                cursor=(10, 10),
                prev_cursor=(10, 10),
                already_counted=False,
                now_mono=1.08,
                last_op_mono=1.0,
                cooldown_sec=0.25,
            )
        )

    def test_skips_when_moved_this_tick(self):
        """本轮已有位移时 LastInput 不得再当点击，否则虚拟机里移动会双计。"""
        self.assertFalse(
            grabbed_input_should_count(
                vm_active=True,
                last_tick=100,
                prev_tick=90,
                cursor=(10, 10),
                prev_cursor=(10, 10),
                already_counted=False,
                now_mono=1.0,
                last_op_mono=0.0,
                cooldown_sec=0.25,
                moved=True,
            )
        )


class MouseAndKeyCountTests(unittest.TestCase):
    def test_mouse_press_counts_even_over_vm(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        with mock.patch.object(mon, "_cursor_over_vm", return_value=True):
            mon._on_mouse_pressed()
        self.assertEqual(ops, [1])

    def test_key_press_counts_even_in_vm(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        with mock.patch.object(mon, "_foreground_is_vm", return_value=True):
            mon._on_key_pressed()
        self.assertEqual(ops, [1])

    def test_vm_fallback_counts_once(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        with mock.patch(
            "src.input_monitor.grabbed_input_should_count",
            return_value=True,
        ), mock.patch("src.input_monitor.last_input_tick", return_value=1), mock.patch(
            "src.input_monitor.cursor_screen_pos",
            return_value=(1, 1),
        ), mock.patch.object(mon, "_cursor_over_vm", return_value=True):
            mon._maybe_count_grabbed_vm(already_counted=False)
        self.assertEqual(ops, [1])

    def test_vm_duplicate_sources_count_once(self):
        """Raw / 轮询 / LastInput 对同一次点击不得各记一次。"""
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        with mock.patch.object(mon, "_cursor_over_vm", return_value=True):
            mon._count_op()
            mon._count_op()
            mon._on_mouse_pressed()
        self.assertEqual(ops, [1])

    def test_slide_out_of_vm_does_not_count(self):
        """光标从虚拟机滑到外面：松开抢鼠标不得记一次操作。"""
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        over = True

        def cursor_over() -> bool:
            return over

        with mock.patch.object(mon, "_cursor_over_vm", side_effect=cursor_over):
            mon._note_cursor_vm_state()
            over = False
            mon._count_op()
        self.assertEqual(ops, [])

    def test_host_click_after_leave_window_counts(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        with mock.patch.object(mon, "_cursor_over_vm", return_value=False):
            mon._was_over_vm = True
            mon._count_op()
            self.assertEqual(ops, [])
            mon._ignore_until = 0.0
            mon._count_op()
        self.assertEqual(ops, [1])


class MouseMotionCountTests(unittest.TestCase):
    def test_eighty_pixels_counts_once(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        mon._prev_cursor = (0, 0)
        mon._settle_mouse_motion((80, 0))
        self.assertEqual(len(ops), 1)

    def test_remainder_carries_to_next_tick(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        mon._prev_cursor = (0, 0)
        mon._settle_mouse_motion((40, 0))
        self.assertEqual(ops, [])
        mon._settle_mouse_motion((80, 0))
        self.assertEqual(len(ops), 1)

    def test_forty_pixels_does_not_count(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        mon._prev_cursor = (0, 0)
        mon._settle_mouse_motion((40, 0))
        self.assertEqual(len(ops), 0)

    def test_second_move_within_50ms_does_not_count(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        clock = {"t": 1000.0}

        def now() -> float:
            return clock["t"]

        with mock.patch("src.input_monitor.time.perf_counter", side_effect=now):
            mon._prev_cursor = (0, 0)
            mon._settle_mouse_motion((80, 0))
            self.assertEqual(len(ops), 1)
            clock["t"] += 0.05
            mon._settle_mouse_motion((160, 0))
        self.assertEqual(len(ops), 1)

    def test_second_move_after_100ms_counts(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        clock = {"t": 1000.0}

        def now() -> float:
            return clock["t"]

        with mock.patch("src.input_monitor.time.perf_counter", side_effect=now):
            mon._prev_cursor = (0, 0)
            mon._settle_mouse_motion((80, 0))
            self.assertEqual(len(ops), 1)
            clock["t"] += 0.1
            mon._settle_mouse_motion((160, 0))
        self.assertEqual(len(ops), 2)

    def test_first_sample_does_not_count(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        mon._settle_mouse_motion((100, 100))
        self.assertEqual(ops, [])

    def test_frozen_cursor_uses_raw_delta(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        mon._prev_cursor = (50, 50)
        mon._on_raw_mouse_move(80, 0)
        mon._settle_mouse_motion((50, 50))
        self.assertEqual(len(ops), 1)

    def test_screen_move_does_not_double_count_raw(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        mon._prev_cursor = (0, 0)
        mon._on_raw_mouse_move(80, 0)
        mon._settle_mouse_motion((80, 0))
        self.assertEqual(len(ops), 1)

    def test_move_counts_inside_vm(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        with mock.patch.object(mon, "_cursor_over_vm", return_value=True):
            mon._prev_cursor = (0, 0)
            mon._settle_mouse_motion((80, 0))
        self.assertEqual(len(ops), 1)

    def test_move_not_blocked_by_vm_press_dedupe(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        with mock.patch.object(mon, "_cursor_over_vm", return_value=True):
            mon._count_op()
            mon._prev_cursor = (0, 0)
            mon._settle_mouse_motion((80, 0))
        self.assertEqual(len(ops), 2)

    def test_slide_out_ignores_press_but_counts_move(self):
        ops: list[int] = []
        mon = InputMonitor(on_op=lambda: ops.append(1), method="poll")
        over = True

        def cursor_over() -> bool:
            return over

        with mock.patch.object(mon, "_cursor_over_vm", side_effect=cursor_over):
            mon._note_cursor_vm_state()
            over = False
            mon._count_op()
            mon._prev_cursor = (0, 0)
            mon._settle_mouse_motion((80, 0))
        self.assertEqual(len(ops), 1)
