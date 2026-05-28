"""全局键鼠操作监听 - 后台线程，通过回调上抛操作事件。

依赖 pynput。回调会在 pynput 监听线程中触发，Qt 部分需自行做线程切换
(我们通过 Qt 信号 + QueuedConnection 把事件投递回主线程)。

键盘：同一颗键按住不放时，系统会重复触发 on_press；我们只计「首次按下」。
鼠标：同一按键按住只计一次，松开后再次按下才再计。
"""
from __future__ import annotations

import threading
from typing import Callable, Optional, Set

try:
    from pynput import keyboard, mouse  # type: ignore
except Exception:  # pragma: no cover - 缺依赖时降级为不可用
    keyboard = None
    mouse = None


class InputMonitor:
    """全局键鼠监听器。每次独立的按键按下 / 鼠标按下视为一次「操作」。"""

    def __init__(self, on_op: Callable[[], None]):
        self._on_op = on_op
        self._kb_listener: Optional["keyboard.Listener"] = None  # type: ignore
        self._mouse_listener: Optional["mouse.Listener"] = None  # type: ignore
        self._lock = threading.Lock()
        self._running = False
        self._keys_down: Set[object] = set()
        self._buttons_down: Set[object] = set()
        self._input_lock = threading.Lock()

    def available(self) -> bool:
        return keyboard is not None and mouse is not None

    def start(self) -> None:
        if not self.available():
            return
        with self._lock:
            if self._running:
                return
            self._running = True
            self._kb_listener = keyboard.Listener(
                on_press=self._on_key_press,
                on_release=self._on_key_release,
            )
            self._mouse_listener = mouse.Listener(on_click=self._on_click)
            self._kb_listener.daemon = True
            self._mouse_listener.daemon = True
            self._kb_listener.start()
            self._mouse_listener.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False
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
        with self._input_lock:
            self._keys_down.clear()
            self._buttons_down.clear()

    def _count_op(self) -> None:
        try:
            self._on_op()
        except Exception:
            pass

    def _on_key_press(self, key) -> None:
        with self._input_lock:
            if key in self._keys_down:
                return
            self._keys_down.add(key)
        self._count_op()

    def _on_key_release(self, key) -> None:
        with self._input_lock:
            self._keys_down.discard(key)

    def _on_click(self, _x, _y, button, pressed: bool) -> None:
        with self._input_lock:
            if pressed:
                if button in self._buttons_down:
                    return
                self._buttons_down.add(button)
            else:
                self._buttons_down.discard(button)
                return
        self._count_op()
