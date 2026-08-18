"""Windows 工具：虚拟桌面固定、开机自启、去掉点穿样式。"""
from __future__ import annotations

import sys
from typing import Optional

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232


def is_windows() -> bool:
    return sys.platform.startswith("win")


def win32_message_id(eventType, message) -> int:
    """解析 nativeEvent 的 Windows 消息号；非 Windows / 失败时返回 0。"""
    if not is_windows() or message is None:
        return 0
    try:
        if bytes(eventType) != b"windows_generic_MSG":
            return 0
        import ctypes
        from ctypes import wintypes

        msg = wintypes.MSG.from_address(int(message))
        return int(msg.message)
    except Exception:
        return 0


def prepare_overlay_hwnd(hwnd: int) -> None:
    """去掉 WS_EX_TRANSPARENT，避免置顶窗被设成点穿。"""
    if not is_windows() or not hwnd:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd_p = ctypes.c_void_p(int(hwnd))
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            get_long = user32.GetWindowLongPtrW
            set_long = user32.SetWindowLongPtrW
            get_long.restype = ctypes.c_int64
            get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
            set_long.restype = ctypes.c_int64
            set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int64]
        else:
            get_long = user32.GetWindowLongW
            set_long = user32.SetWindowLongW
        style = int(get_long(hwnd_p, GWL_EXSTYLE) or 0)
        if style & WS_EX_TRANSPARENT:
            set_long(hwnd_p, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT)
    except Exception:
        return


def _toggle_pin(hwnd: int, pin: bool) -> bool:
    """把指定 HWND 固定/取消固定到所有虚拟桌面。"""
    if not is_windows() or not hwnd:
        return False
    try:
        from pyvda import AppView  # type: ignore
    except Exception:
        return False
    try:
        view = AppView(hwnd=hwnd)
        for method in ("pin" if pin else "unpin", "pin_app" if pin else "unpin_app"):
            try:
                getattr(view, method)()
            except Exception:
                pass
        return True
    except Exception:
        return False


def pin_window_to_all_desktops(hwnd: int) -> bool:
    """把指定 HWND 固定到所有虚拟桌面 (Windows 10 / 11)。"""
    return _toggle_pin(hwnd, pin=True)


def unpin_window_from_all_desktops(hwnd: int) -> bool:
    """取消固定。"""
    return _toggle_pin(hwnd, pin=False)


def set_startup(enabled: bool, exe_path: Optional[str] = None) -> bool:
    """通过注册表 Run 键设置/取消开机启动。"""
    if not is_windows():
        return False
    try:
        import winreg  # type: ignore
    except Exception:
        return False

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    name = "Adventure"
    if exe_path is None:
        exe_path = sys.argv[0]

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        ) as k:
            if enabled:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, f'"{exe_path}"')
            else:
                try:
                    winreg.DeleteValue(k, name)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
