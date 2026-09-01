"""全局键鼠操作监听。

主模式（Windows 默认）：QTimer + GetAsyncKeyState 轮询，不安装系统级钩子，
避免与笔记本触摸板驱动、OEM 键盘软件、杀毒软件冲突导致死机。

备选模式（非 Windows / 显式指定）：pynput 全局钩子。

每次独立的按键按下 / 鼠标按下视为一次「操作」。
鼠标移动按路程累计，每满 80 像素记一次，最快约 10 次/秒。
点到本应用窗口、点到虚拟机里面都计入。
虚拟机抢走键鼠时：Raw Input + LastInput 回退补按下；同一次点击只记一次。
光标滑出虚拟机时不计假点击（移动本身仍计）。
UI 刷新在鼠标按下期间推迟，避免吃掉点击。
"""
from __future__ import annotations

import ctypes
import logging
import math
import threading
import time
from typing import Callable, Optional

from PySide6.QtCore import QTimer

from .vm_detect import (
    cursor_over_vm,
    cursor_screen_pos,
    foreground_is_vm,
    grabbed_input_should_count,
    last_input_tick,
)
from .win_utils import is_windows

logger = logging.getLogger(__name__)

# --- pynput 可选依赖 ---
try:
    from pynput import keyboard, mouse  # type: ignore

    _PYNPUT_AVAILABLE = True
except Exception:
    keyboard = None
    mouse = None
    _PYNPUT_AVAILABLE = False

# --- GetAsyncKeyState 常量 ---
_VK_RANGE = range(0x01, 0xFF)  # 所有标准虚拟键码

# 鼠标按钮 VK 码
_MOUSE_VK = frozenset({
    0x01,  # VK_LBUTTON
    0x02,  # VK_RBUTTON
    0x04,  # VK_MBUTTON
    0x05,  # VK_XBUTTON1
    0x06,  # VK_XBUTTON2
})

# 轮询间隔（毫秒）
_POLL_INTERVAL_MS = 50

# 休眠唤醒检测阈值（秒）：间隔超此值视为刚唤醒，清脏状态
_SLEEP_GAP_SEC = 1.5

_VM_OP_DEDUP_SEC = 0.25
_MOVE_OP_PIXELS = 80.0
_MOVE_OP_MIN_SEC = 0.1


class InputMonitor:
    """全局键鼠监听器。

    通过 ``method`` 选择工作模式：

    * ``"auto"`` (默认)：Windows 上使用 GetAsyncKeyState 轮询；
      其它平台回退到 pynput 钩子。
    * ``"poll"``：强制 GetAsyncKeyState 轮询（仅 Windows）。
    * ``"hook"``：强制 pynput 钩子（需安装 pynput）。
    """

    def __init__(self, on_op: Callable[[], None], method: str = "auto"):
        if method not in ("auto", "poll", "hook"):
            raise ValueError(f"未知 method: {method!r}，可选 auto / poll / hook")
        self._on_op = on_op
        self._method = method
        self._lock = threading.Lock()
        self._running = False

        # --- 轮询模式状态（主线程） ---
        self._poll_timer: Optional[QTimer] = None
        self._keys_down: set[int] = set()
        self._buttons_down: set[int] = set()
        self._last_poll_time: float = 0.0
        self._op_seq = 0
        self._prev_last_input: Optional[int] = None
        self._prev_cursor: Optional[tuple[int, int]] = None
        self._last_op_mono: float = -1.0
        self._last_move_mono: float = -1.0
        self._was_over_vm = False
        self._ignore_until = 0.0
        self._move_accum = 0.0
        self._raw_move_dx = 0.0
        self._raw_move_dy = 0.0
        self._raw_filter = None
        self._raw_widget = None

        # --- 钩子模式状态（后台线程） ---
        self._kb_listener = None
        self._mouse_listener = None
        self._hook_keys_down: set[object] = set()
        self._hook_buttons_down: set[object] = set()
        self._hook_lock = threading.Lock()

    # ---------- 公开 API ----------
    def available(self) -> bool:
        """当前模式是否可用。"""
        if self._method == "poll":
            return is_windows()
        if self._method == "hook":
            return _PYNPUT_AVAILABLE
        # auto
        if is_windows():
            return True
        return _PYNPUT_AVAILABLE

    def start(self) -> None:
        if not self.available():
            logger.warning("输入监听不可用 (method=%s)", self._method)
            return
        with self._lock:
            if self._running:
                return
            self._running = True

        use_poll = (self._method == "poll") or (
            self._method == "auto" and is_windows()
        )

        if use_poll:
            self._start_poll()
            self._start_raw_input()
        else:
            self._start_hook()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            # 停止轮询
            if self._poll_timer is not None:
                try:
                    self._poll_timer.stop()
                except Exception:
                    pass
                self._poll_timer = None
            self._stop_raw_input()
            # 停止钩子
            if self._kb_listener is not None:
                try:
                    self._kb_listener.stop()
                except Exception:
                    pass
                self._kb_listener = None
            if self._mouse_listener is not None:
                try:
                    self._mouse_listener.stop()
                except Exception:
                    pass
                self._mouse_listener = None
        # 清状态（不持锁）
        self._keys_down.clear()
        self._buttons_down.clear()
        with self._hook_lock:
            self._hook_keys_down.clear()
            self._hook_buttons_down.clear()
        logger.info("输入监听器已停止")

    # ---------- 轮询模式 ----------
    def _start_poll(self) -> None:
        logger.info("输入监听器已启动 (poll @ %dms)", _POLL_INTERVAL_MS)
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def _start_raw_input(self) -> None:
        try:
            from .win_raw_input import install_raw_input

            self._raw_filter, self._raw_widget = install_raw_input(
                on_mouse_down=self._on_raw_mouse_down,
                on_mouse_up=self._on_raw_mouse_up,
                on_key_down=self._on_raw_key_down,
                on_key_up=self._on_raw_key_up,
                on_mouse_move=self._on_raw_mouse_move,
            )
        except Exception:
            logger.debug("Raw Input 启动失败", exc_info=True)
            self._raw_filter = None
            self._raw_widget = None

    def _stop_raw_input(self) -> None:
        try:
            from .win_raw_input import uninstall_raw_input

            uninstall_raw_input(self._raw_filter, self._raw_widget)
        except Exception:
            logger.debug("Raw Input 停止失败", exc_info=True)
        self._raw_filter = None
        self._raw_widget = None

    def _poll(self) -> None:
        """QTimer 回调：扫描所有 VK 码，检测首次按下。"""
        try:
            now = time.perf_counter()

            # 休眠唤醒检测：间隔过大 → 清脏状态，跳过本轮
            if self._last_poll_time > 0 and (now - self._last_poll_time) > _SLEEP_GAP_SEC:
                self._keys_down.clear()
                self._buttons_down.clear()
                self._prev_last_input = None
                self._prev_cursor = None
                self._move_accum = 0.0
                self._raw_move_dx = 0.0
                self._raw_move_dy = 0.0
                self._last_move_mono = -1.0
                self._last_poll_time = now
                return
            self._last_poll_time = now

            self._note_cursor_vm_state()
            seq_before = self._op_seq
            user32 = ctypes.windll.user32
            for vk in _VK_RANGE:
                state = user32.GetAsyncKeyState(vk)
                is_down = (state & 0x8000) != 0

                if vk in _MOUSE_VK:
                    if is_down:
                        if vk not in self._buttons_down:
                            self._buttons_down.add(vk)
                            self._on_mouse_pressed()
                    else:
                        self._buttons_down.discard(vk)
                else:
                    if is_down:
                        if vk not in self._keys_down:
                            self._keys_down.add(vk)
                            self._on_key_pressed()
                    else:
                        self._keys_down.discard(vk)
            moved = self._settle_mouse_motion(cursor_screen_pos())
            self._maybe_count_grabbed_vm(
                already_counted=self._op_seq != seq_before,
                moved=moved,
            )
        except Exception:
            logger.debug("输入轮询异常", exc_info=True)

    # ---------- 钩子模式 ----------
    def _start_hook(self) -> None:
        logger.info("输入监听器已启动 (hook, pynput)")
        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press_hook,
            on_release=self._on_key_release_hook,
        )
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click_hook,
            on_move=self._on_move_hook,
        )
        self._kb_listener.daemon = True
        self._mouse_listener.daemon = True
        self._kb_listener.start()
        self._mouse_listener.start()

    def _on_key_press_hook(self, key) -> None:
        with self._hook_lock:
            if key in self._hook_keys_down:
                return
            self._hook_keys_down.add(key)
        self._on_key_pressed()

    def _on_key_release_hook(self, key) -> None:
        with self._hook_lock:
            self._hook_keys_down.discard(key)

    def _on_click_hook(self, _x, _y, button, pressed: bool) -> None:
        with self._hook_lock:
            if pressed:
                if button in self._hook_buttons_down:
                    return
                self._hook_buttons_down.add(button)
            else:
                self._hook_buttons_down.discard(button)
                return
        self._on_mouse_pressed()

    def _on_move_hook(self, x, y) -> None:
        self._settle_mouse_motion((int(x), int(y)))

    # ---------- 共用 ----------
    def _cursor_over_vm(self) -> bool:
        return cursor_over_vm()

    def _foreground_is_vm(self) -> bool:
        return foreground_is_vm()

    def _vm_active(self) -> bool:
        return self._cursor_over_vm() or self._foreground_is_vm()

    def _note_cursor_vm_state(self) -> None:
        """光标刚离开虚拟机时开启短忽略窗，吞掉松开/抢鼠标的假点击。"""
        over = self._cursor_over_vm()
        if self._was_over_vm and not over:
            self._ignore_until = time.perf_counter() + _VM_OP_DEDUP_SEC
        self._was_over_vm = over

    def _on_mouse_pressed(self) -> None:
        self._count_op()

    def _on_key_pressed(self) -> None:
        self._count_op()

    def _on_raw_mouse_down(self, vk: int) -> None:
        if vk not in self._buttons_down:
            self._buttons_down.add(vk)
            self._count_op()

    def _on_raw_mouse_up(self, vk: int) -> None:
        self._buttons_down.discard(vk)

    def _on_raw_key_down(self, vk: int) -> None:
        if vk not in self._keys_down:
            self._keys_down.add(vk)
            self._count_op()

    def _on_raw_key_up(self, vk: int) -> None:
        self._keys_down.discard(vk)

    def _on_raw_mouse_move(self, dx: int, dy: int) -> None:
        self._raw_move_dx += dx
        self._raw_move_dy += dy

    def _apply_mouse_motion(self, dist: float) -> None:
        if dist <= 0:
            return
        self._move_accum += dist
        if self._move_accum < _MOVE_OP_PIXELS:
            return
        now = time.perf_counter()
        if self._last_move_mono >= 0 and (now - self._last_move_mono) < _MOVE_OP_MIN_SEC:
            self._move_accum = _MOVE_OP_PIXELS
            return
        self._move_accum -= _MOVE_OP_PIXELS
        self._count_op(kind="move")

    def _settle_mouse_motion(self, pos: Optional[tuple[int, int]]) -> bool:
        screen_dist = 0.0
        if self._prev_cursor is not None and pos is not None:
            screen_dist = math.hypot(
                pos[0] - self._prev_cursor[0],
                pos[1] - self._prev_cursor[1],
            )
        raw_dist = math.hypot(self._raw_move_dx, self._raw_move_dy)
        self._raw_move_dx = 0.0
        self._raw_move_dy = 0.0
        moved = False
        if screen_dist >= 1.0:
            self._apply_mouse_motion(screen_dist)
            moved = True
        elif raw_dist > 0.0:
            self._apply_mouse_motion(raw_dist)
            moved = True
        self._prev_cursor = pos
        return moved

    def _maybe_count_grabbed_vm(
        self, already_counted: bool, moved: bool = False
    ) -> None:
        tick = last_input_tick()
        pos = cursor_screen_pos()
        if grabbed_input_should_count(
            vm_active=self._cursor_over_vm(),
            last_tick=tick,
            prev_tick=self._prev_last_input,
            cursor=pos,
            prev_cursor=self._prev_cursor,
            already_counted=already_counted,
            now_mono=time.perf_counter(),
            last_op_mono=self._last_op_mono,
            cooldown_sec=_VM_OP_DEDUP_SEC,
            moved=moved,
        ):
            self._count_op()
        self._prev_last_input = tick

    def _count_op(self, kind: str = "press") -> None:
        now = time.perf_counter()
        self._note_cursor_vm_state()
        if kind == "press":
            if self._ignore_until > 0 and now < self._ignore_until:
                return
            if (
                self._was_over_vm
                and self._last_op_mono >= 0
                and (now - self._last_op_mono) < _VM_OP_DEDUP_SEC
            ):
                return
        self._last_op_mono = now
        if kind == "move":
            self._last_move_mono = now
        self._op_seq += 1
        try:
            self._on_op()
        except Exception:
            pass
