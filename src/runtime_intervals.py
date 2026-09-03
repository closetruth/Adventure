from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from typing import TYPE_CHECKING

from .storage import get_data_dir

if TYPE_CHECKING:
    from .models import AppState

logger = logging.getLogger(__name__)

MIN_DURATION_SEC = 1.0
MERGE_GAP_SEC = 2.0
CLOCK_JUMP_SEC = 3600.0
CRASH_MAX_AGE_SEC = 3600.0
FILE_NAME = "runtime_intervals.json"

PALETTE = (
    "#6ee7a0",
    "#5ec8f2",
    "#f5c842",
    "#ff9f6b",
    "#c4b5fd",
    "#f472b6",
    "#94a3b8",
    "#9ec5ff",
)


@dataclass
class RuntimeInterval:
    task_id: str
    title: str
    leaf_id: Optional[str]
    leaf_title: Optional[str]
    start: float
    end: Optional[float] = None

    def identity(self) -> tuple[str, Optional[str]]:
        return (self.task_id, self.leaf_id)

    def to_dict(self) -> dict:
        data = {
            "task_id": self.task_id,
            "title": self.title,
            "leaf_id": self.leaf_id,
            "leaf_title": self.leaf_title,
            "start": self.start,
        }
        if self.end is not None:
            data["end"] = self.end
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "RuntimeInterval":
        leaf_id = data.get("leaf_id")
        if leaf_id == "":
            leaf_id = None
        end = data.get("end")
        return cls(
            task_id=str(data.get("task_id") or ""),
            title=str(data.get("title") or ""),
            leaf_id=None if leaf_id is None else str(leaf_id),
            leaf_title=None if data.get("leaf_title") is None else str(data.get("leaf_title")),
            start=float(data["start"]),
            end=None if end is None else float(end),
        )


@dataclass
class DaySlice:
    date: str
    t0: float
    t1: float
    task_id: str
    title: str
    leaf_id: Optional[str]
    leaf_title: Optional[str]

    def identity(self) -> tuple[str, Optional[str]]:
        return (self.task_id, self.leaf_id)


def identity_color(task_id: str, leaf_id: Optional[str] = None) -> str:
    """Stable palette color by top-level task; leaf_id ignored (same top => same color)."""
    _ = leaf_id
    return PALETTE[zlib.crc32(task_id.encode("utf-8")) % len(PALETTE)]


def local_week_start(now: float) -> float:
    dt = datetime.fromtimestamp(now)
    monday = (dt - timedelta(days=dt.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday.timestamp()


def add_weeks(week_start: float, n: int) -> float:
    return (datetime.fromtimestamp(week_start) + timedelta(weeks=n)).timestamp()


def _wall_hour(ts: float) -> float:
    dt = datetime.fromtimestamp(ts)
    return (
        dt.hour
        + dt.minute / 60.0
        + dt.second / 3600.0
        + dt.microsecond / 3_600_000_000.0
    )


def _day_start(ts: float) -> datetime:
    return datetime.fromtimestamp(ts).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _closed_view(log: RuntimeIntervalLog, now: float) -> list[RuntimeInterval]:
    items = list(log.intervals)
    if log.open is not None:
        items.append(
            RuntimeInterval(
                task_id=log.open.task_id,
                title=log.open.title,
                leaf_id=log.open.leaf_id,
                leaf_title=log.open.leaf_title,
                start=log.open.start,
                end=now,
            )
        )
    return items


def _split_days(iv: RuntimeInterval, a: float, b: float) -> list[DaySlice]:
    out: list[DaySlice] = []
    cur = a
    while cur < b - 1e-9:
        day0 = _day_start(cur)
        day1_ts = (day0 + timedelta(days=1)).timestamp()
        end = min(b, day1_ts)
        t0 = _wall_hour(cur)
        t1 = 24.0 if end >= day1_ts - 1e-6 else _wall_hour(end)
        if t1 > t0:
            out.append(
                DaySlice(
                    date=day0.strftime("%Y-%m-%d"),
                    t0=t0,
                    t1=t1,
                    task_id=iv.task_id,
                    title=iv.title,
                    leaf_id=iv.leaf_id,
                    leaf_title=iv.leaf_title,
                )
            )
        cur = end
    return out


def slices_for_week(
    log: RuntimeIntervalLog,
    week_start: float,
    now: float,
) -> list[DaySlice]:
    week_end = add_weeks(week_start, 1)
    out: list[DaySlice] = []
    for iv in _closed_view(log, now):
        if iv.end is None:
            continue
        a = max(iv.start, week_start)
        b = min(iv.end, week_end)
        if b <= a:
            continue
        out.extend(_split_days(iv, a, b))
    return out


def resolve_runtime_labels(
    state: "AppState",
    task_id: str,
    leaf_id: Optional[str],
    *,
    fallback_title: str = "",
    fallback_leaf_title: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    """有叶子则从树上现查顶层；扁平目标用 task_id。删掉的用快照回退。"""
    if leaf_id:
        for task in state.tasks:
            sub = task.find_subtask(leaf_id)
            if sub is not None:
                return task.title, sub.title
        top = fallback_title
        for task in state.tasks:
            if task.id == task_id:
                top = task.title
                break
        return (top or fallback_title or "已删除"), fallback_leaf_title
    for task in state.tasks:
        if task.id == task_id:
            return task.title, None
    return (fallback_title or "已删除"), None


def enrich_slices(state: "AppState", slices: list[DaySlice]) -> list[DaySlice]:
    """显示前用现树刷新顶层/叶子标题。"""
    out: list[DaySlice] = []
    for sl in slices:
        title, leaf_title = resolve_runtime_labels(
            state,
            sl.task_id,
            sl.leaf_id,
            fallback_title=sl.title,
            fallback_leaf_title=sl.leaf_title,
        )
        out.append(
            DaySlice(
                date=sl.date,
                t0=sl.t0,
                t1=sl.t1,
                task_id=sl.task_id,
                title=title,
                leaf_id=sl.leaf_id,
                leaf_title=leaf_title,
            )
        )
    return out


class RuntimeIntervalLog:
    def __init__(self) -> None:
        self.intervals: list[RuntimeInterval] = []
        self.open: Optional[RuntimeInterval] = None
        self.load_reset: bool = False
        self._last_now: Optional[float] = None

    def tick(
        self,
        *,
        recording: bool,
        task_id: Optional[str],
        title: str = "",
        leaf_id: Optional[str] = None,
        leaf_title: Optional[str] = None,
        now: float,
    ) -> bool:
        mutated = False
        if self._last_now is not None:
            delta = now - self._last_now
            if delta < -CLOCK_JUMP_SEC:
                if self.open is not None:
                    self.open = None
                    mutated = True
            elif delta > CLOCK_JUMP_SEC:
                if self.close_open(self._last_now):
                    mutated = True
        self._last_now = now

        if recording and task_id:
            ident = (task_id, leaf_id)
            if self.open is None:
                self.open = RuntimeInterval(
                    task_id=task_id,
                    title=title,
                    leaf_id=leaf_id,
                    leaf_title=leaf_title,
                    start=now,
                )
                return True
            if self.open.identity() != ident:
                self.close_open(now)
                self.open = RuntimeInterval(
                    task_id=task_id,
                    title=title,
                    leaf_id=leaf_id,
                    leaf_title=leaf_title,
                    start=now,
                )
                return True
            return mutated
        if self.close_open(now):
            return True
        return mutated

    def close_open(self, now: float) -> bool:
        cur = self.open
        if cur is None:
            return False
        self.open = None
        if 0 < now - cur.start < MIN_DURATION_SEC:
            return True
        cur.end = now
        if self.intervals:
            prev = self.intervals[-1]
            if (
                prev.end is not None
                and prev.identity() == cur.identity()
                and (cur.start - prev.end) < MERGE_GAP_SEC
            ):
                prev.end = cur.end
                return True
        self.intervals.append(cur)
        return True

    def recover_open(self, *, data_mtime: Optional[float], now: float) -> None:
        if self.open is None:
            return
        if data_mtime is None:
            self.open = None
            return
        if data_mtime >= self.open.start and (now - data_mtime) <= CRASH_MAX_AGE_SEC:
            self.close_open(data_mtime)
            return
        self.open = None


def intervals_path() -> Path:
    return get_data_dir() / FILE_NAME


def _archive_corrupt(path: Path) -> None:
    if not path.exists():
        return
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = path.with_name(f"runtime_intervals.broken.{stamp}.json")
    try:
        path.replace(dest)
    except OSError:
        logger.warning("无法归档损坏的运行日志 %s", path)


def load_log(
    path: Optional[Path] = None,
    *,
    data_mtime: Optional[float] = None,
    now: Optional[float] = None,
    recover: bool = True,
) -> RuntimeIntervalLog:
    now = time.time() if now is None else now
    path = path or intervals_path()
    log = RuntimeIntervalLog()
    if not path.exists():
        return log
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise TypeError("runtime intervals root must be an object")
        raw_intervals = data.get("intervals") or []
        if not isinstance(raw_intervals, list):
            raise TypeError("intervals must be a list")
        if any(not isinstance(x, dict) for x in raw_intervals):
            raise TypeError("interval entries must be objects")
        log.intervals = [RuntimeInterval.from_dict(x) for x in raw_intervals]
        open_d = data.get("open")
        if open_d:
            if not isinstance(open_d, dict):
                raise TypeError("open must be an object")
            opened = RuntimeInterval.from_dict(open_d)
            if opened.end is not None:
                log.intervals.append(opened)
            else:
                log.open = opened
                if recover:
                    log.recover_open(data_mtime=data_mtime, now=now)
        return log
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        logger.warning("运行日志损坏，已重置: %s", path)
        _archive_corrupt(path)
        reset = RuntimeIntervalLog()
        reset.load_reset = True
        return reset


def save_log(log: RuntimeIntervalLog, path: Optional[Path] = None) -> None:
    path = path or intervals_path()
    payload = {
        "version": 1,
        "intervals": [item.to_dict() for item in log.intervals],
        "open": None if log.open is None else log.open.to_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix="adventure_rt_", suffix=".json", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
