"""轻量级 JSON 持久化。"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

from .models import AppState

# 滚动备份：每次成功保存前，把当前 data.json 依次落到 .bak / .bak2
_BACKUP_FILES = ("data.json.bak", "data.json.bak2")


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


def _backup_paths(data_dir: Path) -> list[Path]:
    return [data_dir / name for name in _BACKUP_FILES]


def _file_is_blank(raw: bytes) -> bool:
    if not raw:
        return True
    stripped = raw.strip(b" \t\r\n")
    if not stripped:
        return True
    return stripped == b"\x00" * len(stripped)


def _validate_state_file(path: Path) -> bool:
    """确认文件非空、JSON 合法且能还原为 AppState。"""
    try:
        if not path.is_file():
            return False
        if path.stat().st_size < 2:
            return False
        raw = path.read_bytes()
        if _file_is_blank(raw):
            return False
        data = json.loads(raw.decode("utf-8"))
        AppState.from_dict(data)
        return True
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, KeyError):
        return False


def _load_from_file(path: Path) -> AppState:
    with path.open("r", encoding="utf-8") as f:
        return AppState.from_dict(json.load(f))


def _archive_corrupt(path: Path) -> None:
    """把无法读取的主存档挪到带时间戳的 broken 文件，避免覆盖旧备份。"""
    if not path.exists():
        return
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = path.with_name(f"data.broken.{stamp}.json")
    try:
        path.replace(dest)
    except OSError:
        pass


def _rotate_backups(main_path: Path) -> None:
    """保存前：当前 data.json 若有效，则滚动备份 .bak <- 主文件，.bak2 <- 旧 .bak。"""
    if not _validate_state_file(main_path):
        return
    data_dir = main_path.parent
    backups = _backup_paths(data_dir)
    try:
        if backups[0].exists():
            backups[0].replace(backups[1])
        shutil.copy2(main_path, backups[0])
    except OSError:
        pass


def load_state() -> AppState:
    path = get_data_file()
    candidates = [path, *_backup_paths(path.parent)]
    for i, candidate in enumerate(candidates):
        if not _validate_state_file(candidate):
            continue
        try:
            state = _load_from_file(candidate)
        except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
            continue
        if i > 0:
            # 主文件坏了，从备份恢复：尽量写回 data.json
            try:
                shutil.copy2(candidate, path)
            except OSError:
                pass
        return state

    if path.exists():
        _archive_corrupt(path)
    return AppState()


def save_state(state: AppState) -> None:
    """原子写入：临时文件 → 校验 → 备份当前文件 → replace。"""
    path = get_data_file()
    data = state.to_dict()
    tmp_path: Optional[str] = None
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix="adventure_", suffix=".json", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

        tmp = Path(tmp_path)
        if not _validate_state_file(tmp):
            raise OSError("save rejected: temp file failed validation")

        _rotate_backups(path)
        os.replace(tmp_path, path)
        tmp_path = None
    except OSError:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
