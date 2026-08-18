"""Windows 10 专属工具：把窗口固定到「所有虚拟桌面」。

依赖可选：``pyvda`` (Python Virtual Desktop Accessor)。若运行平台不是 Windows
或未安装 pyvda，函数会安全地无操作返回 False。
"""
from __future__ import annotations

import sys
from typing import Optional

# winuser.h
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
RDW_INVALIDATE = 0x0001
RDW_ERASE = 0x0004
RDW_FRAME = 0x0400
RDW_ALLCHILDREN = 0x0080
RDW_UPDATENOW = 0x0100
WM_NCHITTEST = 0x0084
WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232
HTCLIENT = 1


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


def _user32():
    import ctypes

    return ctypes.windll.user32


def _hwnd_ptr(hwnd: int):
    import ctypes

    return ctypes.c_void_p(int(hwnd))


def _get_set_long(user32):
    import ctypes

    if ctypes.sizeof(ctypes.c_void_p) == 8:
        get_long = user32.GetWindowLongPtrW
        set_long = user32.SetWindowLongPtrW
        get_long.restype = ctypes.c_int64
        get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
        set_long.restype = ctypes.c_int64
        set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int64]
        return get_long, set_long
    return user32.GetWindowLongW, user32.SetWindowLongW


def prepare_overlay_hwnd(hwnd: int) -> None:
    """去掉 WS_EX_TRANSPARENT，避免半透明置顶窗点穿或不重绘。

    64 位必须用 Get/SetWindowLongPtr，否则句柄被截断后可能把窗口设成点穿。
    """
    resync_overlay_hwnd(hwnd)


def resync_overlay_hwnd(hwnd: int) -> None:
    """拖动/显示后强制同步分层窗的命中区域。

    半透明置顶窗用 WS_EX_LAYERED；若只 QWidget.move()，画面可能已挪走，
    点击仍打在旧位置或整窗变成点穿。
    """
    if not is_windows() or not hwnd:
        return
    try:
        import ctypes

        user32 = _user32()
        hwnd_p = _hwnd_ptr(hwnd)
        get_long, set_long = _get_set_long(user32)
        style = int(get_long(hwnd_p, GWL_EXSTYLE) or 0)
        if style & WS_EX_TRANSPARENT:
            set_long(hwnd_p, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT)
        swp_flags = (
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
        )
        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = ctypes.c_int
        user32.SetWindowPos(hwnd_p, None, 0, 0, 0, 0, swp_flags)
        user32.RedrawWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        user32.RedrawWindow.restype = ctypes.c_int
        user32.RedrawWindow(
            hwnd_p,
            None,
            None,
            RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN | RDW_UPDATENOW,
        )
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
    """通过注册表 Run 键设置/取消开机启动。

    Args:
        enabled: True 启用开机启动，False 取消。
        exe_path: 可执行程序完整路径；为 None 时使用当前进程的 sys.argv[0]。
    """
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
