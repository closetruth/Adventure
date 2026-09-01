"""Raw Input 后台接收：虚拟机抢走 GetAsyncKeyState 时仍可能收到 HID 按下。"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Callable, Optional

from PySide6.QtCore import QAbstractNativeEventFilter, Qt
from PySide6.QtWidgets import QApplication, QWidget

from .win_utils import is_windows

logger = logging.getLogger(__name__)

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x00000100
RIDEV_REMOVE = 0x00000001
RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1
RI_KEY_BREAK = 0x01

_RI_MOUSE_DOWN = (
    (0x0001, 0x01),
    (0x0004, 0x02),
    (0x0010, 0x04),
    (0x0040, 0x05),
    (0x0100, 0x06),
)
_RI_MOUSE_UP = (
    (0x0002, 0x01),
    (0x0008, 0x02),
    (0x0020, 0x04),
    (0x0080, 0x05),
    (0x0200, 0x06),
)


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("_pad", wintypes.USHORT),
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", wintypes.USHORT),
        ("Flags", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("VKey", wintypes.USHORT),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


_user32 = None


def _user32_dll():
    global _user32
    if _user32 is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.RegisterRawInputDevices.argtypes = [
            ctypes.POINTER(RAWINPUTDEVICE),
            wintypes.UINT,
            wintypes.UINT,
        ]
        u.RegisterRawInputDevices.restype = wintypes.BOOL
        u.GetRawInputData.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.UINT),
            wintypes.UINT,
        ]
        u.GetRawInputData.restype = wintypes.UINT
        _user32 = u
    return _user32


class RawInputFilter(QAbstractNativeEventFilter):
    def __init__(
        self,
        on_mouse_down: Callable[[int], None],
        on_mouse_up: Callable[[int], None],
        on_key_down: Callable[[int], None],
        on_key_up: Callable[[int], None],
    ):
        super().__init__()
        self._on_mouse_down = on_mouse_down
        self._on_mouse_up = on_mouse_up
        self._on_key_down = on_key_down
        self._on_key_up = on_key_up

    def nativeEventFilter(self, eventType, message) -> bool:
        try:
            if bytes(eventType) != b"windows_generic_MSG":
                return False
            msg = wintypes.MSG.from_address(int(message))
            if int(msg.message) != WM_INPUT:
                return False
            _dispatch_raw(
                int(msg.lParam),
                self._on_mouse_down,
                self._on_mouse_up,
                self._on_key_down,
                self._on_key_up,
            )
        except Exception:
            logger.debug("Raw Input 解析失败", exc_info=True)
        return False


def install_raw_input(
    on_mouse_down: Callable[[int], None],
    on_mouse_up: Callable[[int], None],
    on_key_down: Callable[[int], None],
    on_key_up: Callable[[int], None],
) -> tuple[Optional[RawInputFilter], Optional[QWidget]]:
    if not is_windows():
        return None, None
    app = QApplication.instance()
    if app is None:
        return None, None
    widget = QWidget()
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
    widget.createWinId()
    hwnd = int(widget.winId())
    if not _register(hwnd):
        logger.warning("RegisterRawInputDevices 失败")
        widget.deleteLater()
        return None, None
    filt = RawInputFilter(on_mouse_down, on_mouse_up, on_key_down, on_key_up)
    app.installNativeEventFilter(filt)
    logger.info("Raw Input 已注册 (INPUTSINK)")
    return filt, widget


def uninstall_raw_input(
    filt: Optional[RawInputFilter],
    widget: Optional[QWidget],
) -> None:
    app = QApplication.instance()
    if app is not None and filt is not None:
        try:
            app.removeNativeEventFilter(filt)
        except Exception:
            pass
    _unregister()
    if widget is not None:
        try:
            widget.deleteLater()
        except Exception:
            pass


def _register(hwnd: int) -> bool:
    devices = (RAWINPUTDEVICE * 2)()
    devices[0].usUsagePage = 0x01
    devices[0].usUsage = 0x02
    devices[0].dwFlags = RIDEV_INPUTSINK
    devices[0].hwndTarget = hwnd
    devices[1].usUsagePage = 0x01
    devices[1].usUsage = 0x06
    devices[1].dwFlags = RIDEV_INPUTSINK
    devices[1].hwndTarget = hwnd
    return bool(
        _user32_dll().RegisterRawInputDevices(
            devices, 2, ctypes.sizeof(RAWINPUTDEVICE)
        )
    )


def _unregister() -> None:
    if not is_windows():
        return
    try:
        devices = (RAWINPUTDEVICE * 2)()
        devices[0].usUsagePage = 0x01
        devices[0].usUsage = 0x02
        devices[0].dwFlags = RIDEV_REMOVE
        devices[0].hwndTarget = None
        devices[1].usUsagePage = 0x01
        devices[1].usUsage = 0x06
        devices[1].dwFlags = RIDEV_REMOVE
        devices[1].hwndTarget = None
        _user32_dll().RegisterRawInputDevices(
            devices, 2, ctypes.sizeof(RAWINPUTDEVICE)
        )
    except Exception:
        logger.debug("UnregisterRawInputDevices 失败", exc_info=True)


def _dispatch_raw(
    lparam: int,
    on_mouse_down: Callable[[int], None],
    on_mouse_up: Callable[[int], None],
    on_key_down: Callable[[int], None],
    on_key_up: Callable[[int], None],
) -> None:
    user32 = _user32_dll()
    header_size = ctypes.sizeof(RAWINPUTHEADER)
    size = wintypes.UINT(0)
    user32.GetRawInputData(
        lparam, RID_INPUT, None, ctypes.byref(size), header_size
    )
    if size.value == 0:
        return
    buf = ctypes.create_string_buffer(size.value)
    got = user32.GetRawInputData(
        lparam, RID_INPUT, buf, ctypes.byref(size), header_size
    )
    if got == 0xFFFFFFFF or got == 0:
        return
    header = RAWINPUTHEADER.from_buffer_copy(buf)
    if header.dwType == RIM_TYPEMOUSE:
        mouse = RAWMOUSE.from_buffer_copy(buf, header_size)
        flags = int(mouse.usButtonFlags)
        for bit, vk in _RI_MOUSE_DOWN:
            if flags & bit:
                on_mouse_down(vk)
        for bit, vk in _RI_MOUSE_UP:
            if flags & bit:
                on_mouse_up(vk)
    elif header.dwType == RIM_TYPEKEYBOARD:
        kb = RAWKEYBOARD.from_buffer_copy(buf, header_size)
        vk = int(kb.VKey)
        if vk in (0, 0xFF):
            return
        if int(kb.Flags) & RI_KEY_BREAK:
            on_key_up(vk)
        else:
            on_key_down(vk)
