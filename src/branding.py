"""AimLoot 产品品牌文案（窗口标题、托盘等共用）。"""
from __future__ import annotations

APP_NAME = "AimLoot"
APP_NAME_ZH = "目标奖励管理工具"
TRAY_TOOLTIP = f"{APP_NAME} - {APP_NAME_ZH}"


def window_title(suffix: str = "") -> str:
    """无 suffix → AimLoot；有 suffix →「{suffix} - AimLoot」。"""
    s = (suffix or "").strip()
    return f"{s} - {APP_NAME}" if s else APP_NAME
