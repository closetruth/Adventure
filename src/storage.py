"""轻量级 JSON 持久化。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

from .models import AppState, validate_state_invariants

# 滚动备份：每次成功保存前，把当前 data.json 依次落到 .bak1 ~ .bak5
_BACKUP_FILES = (
    "data.json.bak1",
    "data.json.bak2",
    "data.json.bak3",
    "data.json.bak4",
    "data.json.bak5",
)

# 旧版备份命名（仍参与恢复，并在成功加载后迁移到新命名）
_LEGACY_BACKUP_FILES = ("data.json.bak", "data.json.bak2")

# 紧急备份：当新状态疑似损坏时，保留旧存档不被级联覆盖
_SAFETY_BACKUP = "data.json.safety"

# 可靠快照：不参与滚动轮转，仅在通过校验的保存后按策略更新
_ANCHOR_FILE = "data.json.anchor"
# 快照刷新：距上次至少 N 秒，或 ops 至少增加 N 次
_ANCHOR_MIN_INTERVAL_S = 600
_ANCHOR_MIN_OPS_DELTA = 100

# 时间戳快照：不参与滚动轮转，按时间间隔创建，保留多份历史版本
_SNAPSHOT_GLOB = "data.snap.*.json"
# 每小时快照：保留最近 24 份
_MAX_HOURLY_SNAPSHOTS = 24
# 每日快照：保留最近 7 份
_MAX_DAILY_SNAPSHOTS = 7

# 内容哈希 JSON key
_HASH_KEY = "_content_hash"

_load_warning: Optional[str] = None


def take_load_warning() -> Optional[str]:
    """读取并清除启动时的存档加载警告（供 UI 弹窗）。"""
    global _load_warning
    msg, _load_warning = _load_warning, None
    return msg


class SaveRejectedError(OSError):
    """内存状态未通过保存前校验，拒绝写入磁盘。"""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


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
    """确认文件非空、JSON 合法且能还原为 AppState。

    如果文件中包含内容哈希，则同时校验哈希是否匹配。
    """
    try:
        if not path.is_file():
            return False
        if path.stat().st_size < 2:
            return False
        raw = path.read_bytes()
        if _file_is_blank(raw):
            return False
        data = json.loads(raw.decode("utf-8"))
        # 校验内容哈希（若存在）
        stored_hash = data.pop(_HASH_KEY, None)
        if stored_hash is not None:
            computed = _compute_content_hash(data)
            if computed != stored_hash:
                return False
        AppState.from_dict(data)
        return True
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, KeyError):
        return False


def _load_from_file(path: Path) -> AppState:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data.pop(_HASH_KEY, None)  # 去掉存储层字段，避免污染模型
    return AppState.from_dict(data)


def _read_data_dict(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data.pop(_HASH_KEY, None)
    return data


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


def _compute_content_hash(data: dict) -> str:
    """计算状态数据的 SHA256 哈希（排除哈希字段自身）。"""
    raw = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _compute_health(data: dict) -> dict:
    """提取状态关键指标，用于退化检测。"""
    inv = data.get("inventory", {}) if isinstance(data.get("inventory"), dict) else {}
    tasks = data.get("tasks", []) if isinstance(data.get("tasks"), list) else []
    return {
        "gold": max(0.0, float(inv.get("gold", 0))),
        "diamond": max(0.0, float(inv.get("diamond", 0))),
        "task_count": len(tasks),
        "total_ops": max(0, int(data.get("total_operations", 0))),
    }


def _is_degraded(old_health: dict, new_health: dict) -> bool:
    """判断新状态是否相比旧状态「可疑退化」。

    仅当多个信号同时指向数据丢失时才触发，避免误报正常操作
    （如花费金币、删除任务）。
    """
    gold_old = old_health["gold"]
    gold_new = new_health["gold"]
    diamond_old = old_health["diamond"]
    diamond_new = new_health["diamond"]
    tasks_old = old_health["task_count"]
    tasks_new = new_health["task_count"]
    ops_old = old_health["total_ops"]
    ops_new = new_health["total_ops"]

    # 信号 1：金币骤降 >50% 且操作数没有倒退（排除了回档到旧存档的情况）
    gold_crash = (
        gold_old > 1.0
        and gold_new < gold_old * 0.5
        and ops_new >= ops_old
    )

    # 信号 2：钻石骤降 >50% 且操作数没有倒退
    diamond_crash = (
        diamond_old > 0.01
        and diamond_new < diamond_old * 0.5
        and ops_new >= ops_old
    )

    # 信号 3：任务数减少 且 操作数持平或增长（正常完成任务会保留，不会消失）
    tasks_lost = tasks_new < tasks_old and ops_new >= ops_old

    # 信号 4：全局操作数异常回退（不应发生）
    ops_regression = ops_old > 100 and ops_new < ops_old * 0.5

    # 需要至少两个信号同时触发，或单一极端信号
    signals = sum([gold_crash, diamond_crash, tasks_lost, ops_regression])

    if signals >= 2:
        return True

    # 极端情况：金币、钻石、任务同时归零
    if (
        gold_old > 0 and gold_new == 0
        and diamond_old > 0 and diamond_new == 0
        and tasks_old > 0 and tasks_new == 0
    ):
        return True

    # 操作数严重回退（>90%）
    if ops_old > 500 and ops_new < ops_old * 0.1:
        return True

    return False


def _rotate_backups(main_path: Path) -> None:
    """保存前：当前 data.json 若有效，则级联滚动备份。

    bak4 → bak5  → 丢弃
    bak3 → bak4
    bak2 → bak3
    bak1 → bak2
    data.json → bak1
    """
    if not _validate_state_file(main_path):
        return

    data_dir = main_path.parent
    backups = _backup_paths(data_dir)
    try:
        # 从最旧的开始级联后移（反向遍历避免覆盖）
        for i in range(len(backups) - 1, 0, -1):
            if backups[i - 1].exists():
                backups[i - 1].replace(backups[i])
        shutil.copy2(main_path, backups[0])
    except OSError:
        pass


def _save_safety_backup(main_path: Path) -> None:
    """将当前 data.json 保存为紧急安全备份（不会被自动轮转覆盖）。"""
    if not main_path.is_file():
        return
    safety = main_path.with_name(_SAFETY_BACKUP)
    try:
        shutil.copy2(main_path, safety)
    except OSError:
        pass


def _preserve_good_snapshot(main_path: Path) -> None:
    """拒绝写入前，把当前磁盘上的有效主存档复制到 safety。"""
    if _validate_state_file(main_path):
        _save_safety_backup(main_path)


def _check_save_allowed(main_path: Path, new_data: dict) -> Optional[str]:
    """保存前比对磁盘基准与可靠快照；返回拒绝原因，None 表示允许。"""
    new_health = _compute_health(new_data)

    if main_path.is_file() and _validate_state_file(main_path):
        try:
            disk_health = _compute_health(_read_data_dict(main_path))
        except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
            disk_health = None
        if disk_health is not None:
            if new_health["total_ops"] < disk_health["total_ops"]:
                return (
                    f"操作数异常回退（内存 {new_health['total_ops']} "
                    f"< 磁盘 {disk_health['total_ops']}）"
                )
            # 单次保存丢失 >1 个目标（正常逐个删除每次只少 1 个）
            tasks_dropped = disk_health["task_count"] - new_health["task_count"]
            if tasks_dropped > 1 and new_health["total_ops"] >= disk_health["total_ops"]:
                return f"单次保存丢失 {tasks_dropped} 个目标"
            if _is_degraded(disk_health, new_health):
                return "相较当前存档数据异常退化"

    anchor = main_path.with_name(_ANCHOR_FILE)
    if _validate_state_file(anchor):
        try:
            anchor_health = _compute_health(_read_data_dict(anchor))
        except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
            anchor_health = None
        if anchor_health is not None:
            if _is_degraded(anchor_health, new_health):
                return "相较可靠快照 data.json.anchor 数据异常退化"
            # anchor 周期内丢失多个目标（允许逐个删除后分次保存）
            anchor_tasks_dropped = anchor_health["task_count"] - new_health["task_count"]
            if (
                anchor_tasks_dropped > 1
                and new_health["total_ops"] >= anchor_health["total_ops"]
            ):
                return f"相较可靠快照丢失 {anchor_tasks_dropped} 个目标"

    return None


def _maybe_update_anchor(main_path: Path) -> None:
    """按时间/ops 策略刷新 anchor；不参与滚动备份。"""
    if not _validate_state_file(main_path):
        return
    anchor = main_path.with_name(_ANCHOR_FILE)
    if not anchor.exists():
        try:
            shutil.copy2(main_path, anchor)
        except OSError:
            pass
        return
    try:
        now = time.time()
        anchor_mtime = anchor.stat().st_mtime
        main_health = _compute_health(_read_data_dict(main_path))
        anchor_health = _compute_health(_read_data_dict(anchor))
        ops_delta = main_health["total_ops"] - anchor_health["total_ops"]
    except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
        return
    if now - anchor_mtime >= _ANCHOR_MIN_INTERVAL_S or ops_delta >= _ANCHOR_MIN_OPS_DELTA:
        try:
            shutil.copy2(main_path, anchor)
        except OSError:
            pass


def _manage_snapshots(main_path: Path) -> None:
    """保存成功后：按需创建时间戳快照，并清理过期快照。

    每小时留一份（保留 24 份），每日留一份（保留 7 份）。
    快照仅追加、不轮转，提供比滚动备份更长的时间回溯窗口。
    """
    if not main_path.is_file():
        return
    data_dir = main_path.parent
    now = time.localtime()

    hourly_stamp = time.strftime("%Y%m%d_%H", now)
    hourly_path = data_dir / f"data.snap.{hourly_stamp}.json"
    if not hourly_path.exists():
        try:
            shutil.copy2(main_path, hourly_path)
        except OSError:
            pass

    daily_stamp = time.strftime("%Y%m%d", now)
    daily_path = data_dir / f"data.snap.{daily_stamp}.json"
    if not daily_path.exists():
        try:
            shutil.copy2(main_path, daily_path)
        except OSError:
            pass

    _cleanup_snapshots(data_dir)


def _cleanup_snapshots(data_dir: Path) -> None:
    """清理过期快照：每小时最多 24 份，每日最多 7 份。"""
    snapshots = sorted(data_dir.glob(_SNAPSHOT_GLOB), key=lambda p: p.name)

    hourly: list[Path] = []
    daily: list[Path] = []
    for p in snapshots:
        # data.snap.20260707_14.json → hourly
        # data.snap.20260707.json     → daily
        stem = p.name[len("data.snap."):-len(".json")]
        if "_" in stem:
            hourly.append(p)
        else:
            daily.append(p)

    for p in hourly[:-_MAX_HOURLY_SNAPSHOTS] if _MAX_HOURLY_SNAPSHOTS > 0 else hourly:
        try:
            p.unlink()
        except OSError:
            pass

    for p in daily[:-_MAX_DAILY_SNAPSHOTS] if _MAX_DAILY_SNAPSHOTS > 0 else daily:
        try:
            p.unlink()
        except OSError:
            pass


def _legacy_backup_paths(data_dir: Path) -> list[Path]:
    return [data_dir / name for name in _LEGACY_BACKUP_FILES]


def _migrate_legacy_backups(data_dir: Path) -> None:
    """把旧版 .bak / .bak2 迁移到 bak1 / bak2，避免下次加载找不到。"""
    legacy = _legacy_backup_paths(data_dir)
    modern = _backup_paths(data_dir)
    try:
        for i, old in enumerate(legacy):
            if not old.is_file() or i >= len(modern):
                continue
            new = modern[i]
            if new.exists():
                continue
            shutil.copy2(old, new)
    except OSError:
        pass


def load_state() -> AppState:
    global _load_warning
    _load_warning = None
    path = get_data_file()
    data_dir = path.parent
    safety = path.with_name(_SAFETY_BACKUP)
    anchor = path.with_name(_ANCHOR_FILE)
    candidates = [
        path,
        safety,
        anchor,
        *_backup_paths(data_dir),
        *sorted(data_dir.glob(_SNAPSHOT_GLOB), key=lambda p: p.stat().st_mtime, reverse=True),
        *_legacy_backup_paths(data_dir),
    ]
    had_any_file = any(c.exists() for c in candidates)
    recovered_from: Optional[str] = None
    for i, candidate in enumerate(candidates):
        if not _validate_state_file(candidate):
            continue
        try:
            state = _load_from_file(candidate)
        except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
            continue
        if i > 0:
            recovered_from = candidate.name
            # 主文件坏了，从备份恢复：尽量写回 data.json
            try:
                shutil.copy2(candidate, path)
            except OSError:
                pass
        _migrate_legacy_backups(data_dir)
        if recovered_from:
            _load_warning = (
                f"主存档已损坏，已从备份「{recovered_from}」恢复。\n"
                "若仍有数据缺失，请检查 data.json.anchor / data.json.safety / .bak* / .snap.*。"
            )
        _maybe_update_anchor(path)
        return state

    if path.exists():
        _archive_corrupt(path)
    if had_any_file:
        _load_warning = (
            "无法读取任何有效存档（可能因异常退出导致文件损坏）。\n"
            "已新建空白存档；请查看 %APPDATA%\\Adventure 下的 .bak 备份文件。"
        )
    return AppState()


def save_state(state: AppState) -> None:
    """原子写入：校验 → 退化检测 → 备份轮转 → replace → 刷新 anchor。

    若内存状态未通过不变量/退化检测，拒绝整次写入（磁盘与滚动备份均不变）。
    """
    path = get_data_file()

    inv_err = validate_state_invariants(state)
    if inv_err:
        _preserve_good_snapshot(path)
        raise SaveRejectedError(f"内存状态校验失败：{inv_err}")

    data = state.to_dict()
    data_without_hash = dict(data)

    reject = _check_save_allowed(path, data_without_hash)
    if reject:
        _preserve_good_snapshot(path)
        raise SaveRejectedError(f"{reject}，已拒绝写入以保护备份")

    content_hash = _compute_content_hash(data_without_hash)
    data[_HASH_KEY] = content_hash
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
        _maybe_update_anchor(path)
        _manage_snapshots(path)
    except OSError:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
