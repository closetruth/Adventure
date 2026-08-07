"""Windows 显示器开/关状态监听。"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Optional

from PySide6.QtWidgets import QWidget

from .win_utils import is_windows

logger = logging.getLogger(__name__)

WM_POWERBROADCAST = 0x0218
PBT_POWERSETTINGCHANGE = 0x8013
DEVICE_NOTIFY_WINDOW_HANDLE = 0


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


GUID_CONSOLE_DISPLAY_STATE = GUID(
    0x6FE69556,
    0x704A,
    0x47A0,
    (wintypes.BYTE * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47),
)


class POWERBROADCAST_SETTING_HDR(ctypes.Structure):
    _fields_ = [
        ("PowerSetting", GUID),
        ("DataLength", wintypes.DWORD),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def _guid_equal(a: GUID, b: GUID) -> bool:
    return (
        a.Data1 == b.Data1
        and a.Data2 == b.Data2
        and a.Data3 == b.Data3
        and bytes(a.Data4) == bytes(b.Data4)
    )


class PowerMonitor:
    """监听主显示器开/关；非 Windows 平台始终视为亮屏。"""

    def __init__(self) -> None:
        self.display_on: bool = True
        self._installed = False
        self._notification_handle: Optional[int] = None

    def should_count_time(self) -> bool:
        return self.display_on

    def install_on(self, widget: QWidget) -> bool:
        if not is_windows() or self._installed:
            return False
        try:
            hwnd = int(widget.winId())
            if not hwnd:
                return False
            handle = ctypes.windll.user32.RegisterPowerSettingNotification(
                hwnd,
                ctypes.byref(GUID_CONSOLE_DISPLAY_STATE),
                DEVICE_NOTIFY_WINDOW_HANDLE,
            )
            if not handle:
                logger.warning("RegisterPowerSettingNotification 失败")
                return False
            self._notification_handle = handle
            self._installed = True
            logger.debug("已注册显示器电源状态监听")
            return True
        except Exception:
            logger.exception("注册显示器电源状态监听失败")
            return False

    def handle_native_event(self, eventType, message) -> None:
        if not is_windows():
            return
        try:
            if bytes(eventType) != b"windows_generic_MSG":
                return
            msg = MSG.from_address(int(message))
            if msg.message != WM_POWERBROADCAST:
                return
            if msg.wParam != PBT_POWERSETTINGCHANGE:
                return
            setting = POWERBROADCAST_SETTING_HDR.from_address(msg.lParam)
            if not _guid_equal(setting.PowerSetting, GUID_CONSOLE_DISPLAY_STATE):
                return
            if setting.DataLength < 4:
                return
            data_ptr = msg.lParam + ctypes.sizeof(POWERBROADCAST_SETTING_HDR)
            state = ctypes.c_uint32.from_address(data_ptr).value
            self._set_display_state(state)
        except Exception:
            logger.exception("处理电源事件失败")

    def _set_display_state(self, state: int) -> None:
        # 0=关屏, 1=亮屏, 2=变暗（视为亮屏）
        on = state != 0
        if on != self.display_on:
            self.display_on = on
            logger.info("显示器 %s", "亮起" if on else "关闭")
