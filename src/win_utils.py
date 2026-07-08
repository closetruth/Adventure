"""Windows 10 专属工具：把窗口固定到「所有虚拟桌面」。

依赖可选：``pyvda`` (Python Virtual Desktop Accessor)。若运行平台不是 Windows
或未安装 pyvda，函数会安全地无操作返回 False。
"""
from __future__ import annotations

import sys
from typing import Optional


def is_windows() -> bool:
    return sys.platform.startswith("win")


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
