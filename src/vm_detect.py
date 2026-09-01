"""识别虚拟机窗口：VMware / VirtualBox / Hyper-V / 腾讯应用宝 Androws 等。

宿主 GetAsyncKeyState 在虚拟机抢走键鼠后往往看不到按下；
用 GetLastInputInfo + 光标几乎没动 判断里面的点击/按键。
"""
from __future__ import annotations

import ctypes
import logging
import os
import time
from ctypes import wintypes
from typing import Optional

from .win_utils import is_windows

logger = logging.getLogger(__name__)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_CACHE_TTL_SEC = 2.0
_CURSOR_MOVE_PX = 4


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

_VM_PATH_MARKERS = (
    "\\tencent\\androws\\",
    "\\androwsbox\\",
    "\\txgameassistant\\",
    "\\gameloop\\",
)
_VM_NAME_PREFIXES = ("androws", "abox")
_VM_EXES = frozenset({
    "vmware.exe",
    "vmware-vmx.exe",
    "vmware-remotemks.exe",
    "vmplayer.exe",
    "vmrc.exe",
    "vmware-view.exe",
    "virtualbox.exe",
    "virtualboxvm.exe",
    "vboxsdl.exe",
    "vmconnect.exe",
    "windowssandbox.exe",
    "windowssandboxclient.exe",
    "androidemulator.exe",
    "androidemulatorex.exe",
    "aow_exe.exe",
    "appmarket.exe",
})

_user32 = None
_kernel32 = None
_pid_name_cache: dict[int, tuple[float, str]] = {}


def grabbed_input_should_count(
    *,
    vm_active: bool,
    last_tick: Optional[int],
    prev_tick: Optional[int],
    cursor: Optional[tuple[int, int]],
    prev_cursor: Optional[tuple[int, int]],
    already_counted: bool,
    now_mono: float,
    last_op_mono: float,
    cooldown_sec: float,
    moved: bool = False,
) -> bool:
    """虚拟机抢走键鼠时：LastInput 变了、光标几乎没动 → 视为一次点击/按键。

    按下和松开都会刷新 LastInput，且 Raw Input 可能已经记过，
    所以 ``last_op_mono`` 起 cooldown 内不再记。
    本轮已有位移时不当点击（移动按路程另计）。
    """
    if already_counted or not vm_active or moved:
        return False
    if last_tick is None or prev_tick is None:
        return False
    if last_tick == prev_tick:
        return False
    if cursor is None or prev_cursor is None:
        return False
    dx = cursor[0] - prev_cursor[0]
    dy = cursor[1] - prev_cursor[1]
    if dx * dx + dy * dy > _CURSOR_MOVE_PX * _CURSOR_MOVE_PX:
        return False
    if last_op_mono >= 0 and (now_mono - last_op_mono) < cooldown_sec:
        return False
    return True


def last_input_tick() -> Optional[int]:
    """GetLastInputInfo 的 dwTime（GetTickCount），失败返回 None。"""
    if not is_windows():
        return None
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not _user32_dll().GetLastInputInfo(ctypes.byref(info)):
        return None
    return int(info.dwTime)


def cursor_screen_pos() -> Optional[tuple[int, int]]:
    if not is_windows():
        return None
    pt = wintypes.POINT()
    if not _user32_dll().GetCursorPos(ctypes.byref(pt)):
        return None
    return (int(pt.x), int(pt.y))


def is_vm_executable(name: str) -> bool:
    """``name`` 可以是完整路径或文件名，大小写不敏感。含应用宝 Androws / ABox。"""
    path = name.replace("/", "\\").lower()
    base = os.path.basename(path)
    if not base:
        return False
    if any(marker in path for marker in _VM_PATH_MARKERS):
        return True
    if base in _VM_EXES:
        return True
    if base.endswith(".exe") and base.startswith(_VM_NAME_PREFIXES):
        return True
    return base.startswith("qemu-system-") and base.endswith(".exe")


def cursor_over_vm() -> bool:
    """光标下的 OS 窗口属于虚拟机进程。"""
    if not is_windows():
        return False
    try:
        pid = _pid_at_cursor()
        return bool(pid) and pid_is_vm(pid)
    except Exception:
        logger.debug("虚拟机光标检测失败", exc_info=True)
        return False


def foreground_is_vm() -> bool:
    """前台窗口属于虚拟机进程。"""
    if not is_windows():
        return False
    try:
        pid = _foreground_pid()
        return bool(pid) and pid_is_vm(pid)
    except Exception:
        logger.debug("虚拟机前台检测失败", exc_info=True)
        return False


def pid_is_vm(pid: int) -> bool:
    path = _image_path_for_pid(pid)
    return bool(path) and is_vm_executable(path)


def _user32_dll():
    global _user32
    if _user32 is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        u.GetCursorPos.restype = wintypes.BOOL
        u.WindowFromPoint.argtypes = [wintypes.POINT]
        u.WindowFromPoint.restype = wintypes.HWND
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
        u.GetLastInputInfo.restype = wintypes.BOOL
        _user32 = u
    return _user32


def _kernel32_dll():
    global _kernel32
    if _kernel32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        _kernel32 = k
    return _kernel32


def _pid_of_hwnd(hwnd) -> Optional[int]:
    if not hwnd:
        return None
    pid = wintypes.DWORD(0)
    _user32_dll().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == 0:
        return None
    return int(pid.value)


def _pid_at_cursor() -> Optional[int]:
    user32 = _user32_dll()
    pt = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return None
    return _pid_of_hwnd(user32.WindowFromPoint(pt))


def _foreground_pid() -> Optional[int]:
    return _pid_of_hwnd(_user32_dll().GetForegroundWindow())


def _image_path_for_pid(pid: int) -> Optional[str]:
    if pid <= 0:
        return None
    now = time.monotonic()
    cached = _pid_name_cache.get(pid)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SEC:
        return cached[1]
    path = _query_image_path(pid)
    if path:
        _pid_name_cache[pid] = (now, path)
    return path


def _query_image_path(pid: int) -> Optional[str]:
    k32 = _kernel32_dll()
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if not k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value.lower()
    finally:
        k32.CloseHandle(handle)
