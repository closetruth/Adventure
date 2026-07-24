"""全局键鼠操作监听。

主模式（Windows 默认）：QTimer + GetAsyncKeyState 轮询，不安装系统级钩子，
避免与笔记本触摸板驱动、OEM 键盘软件、杀毒软件冲突导致死机。

备选模式（非 Windows / 显式指定）：pynput 全局钩子。

每次独立的按键按下 / 鼠标按下视为一次「操作」。
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from typing import Callable, Optional

from PySide6.QtCore import QTimer

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


def _is_win() -> bool:
    return sys.platform.startswith("win")


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
            return _is_win()
        if self._method == "hook":
            return _PYNPUT_AVAILABLE
        # auto
        if _is_win():
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
            self._method == "auto" and _is_win()
        )

        if use_poll:
            self._start_poll()
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

    def _poll(self) -> None:
        """QTimer 回调：扫描所有 VK 码，检测首次按下。"""
        try:
            now = time.perf_counter()

            # 休眠唤醒检测：间隔过大 → 清脏状态，跳过本轮
            if self._last_poll_time > 0 and (now - self._last_poll_time) > _SLEEP_GAP_SEC:
                self._keys_down.clear()
                self._buttons_down.clear()
                self._last_poll_time = now
                return
            self._last_poll_time = now

            user32 = ctypes.windll.user32
            for vk in _VK_RANGE:
                state = user32.GetAsyncKeyState(vk)
                is_down = (state & 0x8000) != 0

                if vk in _MOUSE_VK:
                    if is_down:
                        if vk not in self._buttons_down:
                            self._buttons_down.add(vk)
                            self._count_op()
                    else:
                        self._buttons_down.discard(vk)
                else:
                    if is_down:
                        if vk not in self._keys_down:
                            self._keys_down.add(vk)
                            self._count_op()
                    else:
                        self._keys_down.discard(vk)
        except Exception:
            logger.debug("输入轮询异常", exc_info=True)

    # ---------- 钩子模式 ----------
    def _start_hook(self) -> None:
        logger.info("输入监听器已启动 (hook, pynput)")
        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press_hook,
            on_release=self._on_key_release_hook,
        )
        self._mouse_listener = mouse.Listener(on_click=self._on_click_hook)
        self._kb_listener.daemon = True
        self._mouse_listener.daemon = True
        self._kb_listener.start()
        self._mouse_listener.start()

    def _on_key_press_hook(self, key) -> None:
        with self._hook_lock:
            if key in self._hook_keys_down:
                return
            self._hook_keys_down.add(key)
        self._count_op()

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
        self._count_op()

    # ---------- 共用 ----------
    def _count_op(self) -> None:
        try:
            self._on_op()
        except Exception:
            pass
