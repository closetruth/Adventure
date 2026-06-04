"""轻量级 JSON 持久化。"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from .models import AppState


def get_data_dir() -> Path:
    """返回数据存放目录，跨平台兼容。

    Windows: %APPDATA%\\Adventure
    其他:    ~/.adventure
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        d = Path(base) / "Adventure"
    else:
        d = Path.home() / ".adventure"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_data_file() -> Path:
    return get_data_dir() / "data.json"


def load_state() -> AppState:
    path = get_data_file()
    if not path.exists():
        return AppState()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return AppState.from_dict(data)
    except (json.JSONDecodeError, OSError, ValueError):
        # 数据损坏时备份并重置
        try:
            backup = path.with_suffix(".broken.json")
            path.replace(backup)
        except OSError:
            pass
        return AppState()


def save_state(state: AppState) -> None:
    """原子写入：先写临时文件再 rename。"""
    path = get_data_file()
    state.sync_active_timers_for_save()
    data = state.to_dict()
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix="adventure_", suffix=".json", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
