from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

MIN_DURATION_SEC = 1.0
MERGE_GAP_SEC = 2.0
CLOCK_JUMP_SEC = 3600.0
CRASH_MAX_AGE_SEC = 3600.0


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
