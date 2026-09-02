from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .storage import get_data_dir

logger = logging.getLogger(__name__)

MIN_DURATION_SEC = 1.0
MERGE_GAP_SEC = 2.0
CLOCK_JUMP_SEC = 3600.0
CRASH_MAX_AGE_SEC = 3600.0
FILE_NAME = "runtime_intervals.json"


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
