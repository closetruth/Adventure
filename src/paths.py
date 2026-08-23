"""开发态 / 打包态的项目根目录。"""
from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path:
    """开发态为仓库根；打包后为内置资源目录(PyInstaller 6 onedir 为 _internal/)。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent
