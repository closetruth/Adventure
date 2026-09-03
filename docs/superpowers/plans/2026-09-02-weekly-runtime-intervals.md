# Weekly Runtime Intervals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Goal Manager "本周" tab that shows a Monday–Sunday calendar of real run intervals for the top-level goal and focused leaf, recorded forever with calendar dates.

**Architecture:** A `RuntimeIntervalLog` in `src/runtime_intervals.py` opens/closes wall-clock segments from the same `recording` predicate as `tick_active_time`. Persist to `%APPDATA%\Adventure\runtime_intervals.json` (never `data.json`). `src/ui_week_runtime.py` paints seven vertical 0–24 columns. `TaskDialog` hosts the tab; the floating widget is unchanged.

**Tech Stack:** Python 3.12/3.13, PySide6, stdlib `unittest`, existing `TaskManager` / `PowerMonitor` / `get_data_dir()`.

## Global Constraints

- No emoji in UI copy or comments (Windows tofu).
- Copy is Chinese, exact strings from the spec (状态行、悬停、`运行记录已重置`、Tab 名 `本周`).
- Intervals file is separate from `data.json`; never put intervals on `AppState`.
- Do not add the week axis to `FloatingWidget` / `GoalTreeArea`.
- Tests: `.venv\Scripts\python.exe -m unittest …` (not pytest). Offscreen UI uses `QT_QPA_PLATFORM=offscreen`.
- Color identity: `zlib.crc32` of `task_id + "\0" + (leaf_id or "")`, not Python `hash()` (salted per process).
- Forward clock jump > 1 hour closes the open interval at `_last_now` (do not count the gap), then reapplies `recording` at `now`.
- Grouping containers never record; only a focused leaf or a flat top-level task.

## File map

| File | Role |
|------|------|
| Create `src/runtime_intervals.py` | Interval dataclass, log tick/close/merge, load/save, week slice, color |
| Create `src/ui_week_runtime.py` | Status/hover/legend text, 7-column paint widget, week nav panel |
| Create `tests/test_runtime_intervals.py` | Pure logic: tick, persist, week, crash |
| Create `tests/test_task_dialog_week.py` | Offscreen: fourth tab, 7 columns |
| Modify `src/task_manager.py` | Drive the log from `tick_active_time`; persist on mutate |
| Modify `src/main.py` | Load log on start; save with auto/manual save; close open on quit |
| Modify `src/task_dialog.py` | Tab `本周`, width ~640, `refresh_stats` paints the week |

---

### Task 1: In-memory interval log

**Files:**
- Create: `src/runtime_intervals.py`
- Test: `tests/test_runtime_intervals.py`

**Interfaces:**
- Consumes: nothing from later tasks
- Produces:
  - `class RuntimeInterval` with `task_id: str`, `title: str`, `leaf_id: Optional[str]`, `leaf_title: Optional[str]`, `start: float`, `end: Optional[float]`
  - `RuntimeInterval.identity() -> tuple[str, Optional[str]]`
  - `class RuntimeIntervalLog` with `intervals: list[RuntimeInterval]`, `open: Optional[RuntimeInterval]`, `load_reset: bool`
  - `RuntimeIntervalLog.tick(*, recording: bool, task_id: Optional[str], title: str = "", leaf_id: Optional[str] = None, leaf_title: Optional[str] = None, now: float) -> bool`
  - `RuntimeIntervalLog.close_open(now: float) -> bool`
  - Constants: `MIN_DURATION_SEC = 1.0`, `MERGE_GAP_SEC = 2.0`, `CLOCK_JUMP_SEC = 3600.0`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_runtime_intervals.py`:

```python
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.runtime_intervals import RuntimeIntervalLog


def _tick(log, now, *, rec=True, task="T", title="顶", leaf=None, leaf_title=None):
    return log.tick(
        recording=rec,
        task_id=task if rec else None,
        title=title,
        leaf_id=leaf,
        leaf_title=leaf_title,
        now=now,
    )


class IntervalTickTests(unittest.TestCase):
    def test_open_then_close(self):
        log = RuntimeIntervalLog()
        self.assertTrue(_tick(log, 100.0))
        self.assertIsNotNone(log.open)
        self.assertEqual(log.open.task_id, "T")
        self.assertIsNone(log.open.leaf_id)
        self.assertTrue(_tick(log, 110.0, rec=False))
        self.assertIsNone(log.open)
        self.assertEqual(len(log.intervals), 1)
        self.assertEqual(log.intervals[0].start, 100.0)
        self.assertEqual(log.intervals[0].end, 110.0)

    def test_same_identity_does_not_split(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0, leaf="L", leaf_title="叶")
        self.assertFalse(_tick(log, 101.0, leaf="L", leaf_title="叶"))
        self.assertEqual(log.open.start, 100.0)

    def test_switch_leaf_closes_and_opens(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0, leaf="A", leaf_title="甲")
        self.assertTrue(_tick(log, 110.0, leaf="B", leaf_title="乙"))
        self.assertEqual(log.intervals[0].leaf_id, "A")
        self.assertEqual(log.intervals[0].end, 110.0)
        self.assertEqual(log.open.leaf_id, "B")
        self.assertEqual(log.open.start, 110.0)

    def test_switch_top_level_splits(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0, task="A", title="甲")
        _tick(log, 110.0, task="B", title="乙")
        self.assertEqual(log.intervals[0].task_id, "A")
        self.assertEqual(log.open.task_id, "B")

    def test_discard_shorter_than_one_second(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0)
        _tick(log, 100.5, rec=False)
        self.assertEqual(log.intervals, [])
        self.assertIsNone(log.open)

    def test_merge_same_identity_gap_under_two_seconds(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0)
        _tick(log, 110.0, rec=False)
        _tick(log, 111.5)
        _tick(log, 120.0, rec=False)
        self.assertEqual(len(log.intervals), 1)
        self.assertEqual(log.intervals[0].end, 120.0)

    def test_different_leaf_does_not_merge(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0, leaf="A", leaf_title="甲")
        _tick(log, 110.0, rec=False)
        _tick(log, 111.0, leaf="B", leaf_title="乙")
        _tick(log, 120.0, rec=False)
        self.assertEqual(len(log.intervals), 2)

    def test_clock_jump_back_drops_open(self):
        log = RuntimeIntervalLog()
        _tick(log, 10_000.0)
        _tick(log, 100.0, rec=False)
        self.assertIsNone(log.open)
        self.assertEqual(log.intervals, [])

    def test_clock_jump_forward_closes_at_last_now(self):
        log = RuntimeIntervalLog()
        _tick(log, 100.0)
        _tick(log, 10_000.0)
        self.assertEqual(len(log.intervals), 1)
        self.assertEqual(log.intervals[0].end, 100.0)
        self.assertIsNotNone(log.open)
        self.assertEqual(log.open.start, 10_000.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m unittest tests.test_runtime_intervals -v`

Expected: `FAIL` / `ERROR` with `ModuleNotFoundError: No module named 'src.runtime_intervals'`

- [ ] **Step 3: Write minimal implementation**

Create `src/runtime_intervals.py` with only the in-memory log (persist/week helpers come in later tasks; keep them out of this file until those tasks, **or** add stub-free complete classes now and unused functions in Task 2–3). Put the tick logic here in full:

```python
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
        if now - cur.start < MIN_DURATION_SEC:
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
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv\Scripts\python.exe -m unittest tests.test_runtime_intervals -v`

Expected: all `IntervalTickTests` PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_runtime_intervals.py src/runtime_intervals.py
git commit -m "运行时段日志：开段关段，换叶子或顶层会切段"
```

---

### Task 2: Persist, corrupt backup, crash recover

**Files:**
- Modify: `src/runtime_intervals.py` (add load/save/`recover_open`/`intervals_path`)
- Modify: `tests/test_runtime_intervals.py`

**Interfaces:**
- Consumes: `RuntimeIntervalLog`, `RuntimeInterval.to_dict` / `from_dict` from Task 1
- Produces:
  - `intervals_path() -> Path` → `get_data_dir() / "runtime_intervals.json"`
  - `load_log(path: Optional[Path] = None, *, data_mtime: Optional[float] = None, now: Optional[float] = None, recover: bool = True) -> RuntimeIntervalLog` — `recover=False` keeps a saved `open` as-is (same-process roundtrip); startup uses default `True`
  - `save_log(log: RuntimeIntervalLog, path: Optional[Path] = None) -> None`
  - `RuntimeIntervalLog.recover_open(*, data_mtime: Optional[float], now: float) -> None`
  - Corrupt file renamed to `runtime_intervals.broken.<YYYYMMDD_HHMMSS>.json`
  - On JSON/OS/schema error: empty log with `load_reset=True`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_runtime_intervals.py` (add `json`, `tempfile`, `Path` imports):

```python
import json
import tempfile
from pathlib import Path

from src.runtime_intervals import load_log, save_log, RuntimeIntervalLog


class IntervalPersistTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "runtime_intervals.json"

    def test_roundtrip_open_and_closed(self):
        log = RuntimeIntervalLog()
        log.tick(recording=True, task_id="T", title="顶", leaf_id="L", leaf_title="叶", now=100.0)
        log.tick(recording=False, task_id=None, now=110.0)
        log.tick(recording=True, task_id="T", title="顶", now=200.0)
        save_log(log, self.path)
        loaded = load_log(self.path, now=200.0, recover=False)
        self.assertEqual(len(loaded.intervals), 1)
        self.assertEqual(loaded.intervals[0].leaf_id, "L")
        self.assertIsNotNone(loaded.open)
        self.assertEqual(loaded.open.start, 200.0)
        self.assertFalse(loaded.load_reset)

    def test_corrupt_file_archived_and_reset(self):
        self.path.write_text("{not json", encoding="utf-8")
        loaded = load_log(self.path, now=1.0)
        self.assertTrue(loaded.load_reset)
        self.assertEqual(loaded.intervals, [])
        broken = list(Path(self._tmp.name).glob("runtime_intervals.broken.*.json"))
        self.assertEqual(len(broken), 1)

    def test_crash_recover_uses_mtime(self):
        payload = {
            "version": 1,
            "intervals": [],
            "open": {"task_id": "T", "title": "顶", "leaf_id": None, "leaf_title": None, "start": 100.0},
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_log(self.path, data_mtime=150.0, now=160.0)
        self.assertIsNone(loaded.open)
        self.assertEqual(loaded.intervals[0].end, 150.0)

    def test_crash_recover_drops_stale_open(self):
        payload = {
            "version": 1,
            "intervals": [],
            "open": {"task_id": "T", "title": "顶", "leaf_id": None, "leaf_title": None, "start": 100.0},
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_log(self.path, data_mtime=150.0, now=10_000.0)
        self.assertIsNone(loaded.open)
        self.assertEqual(loaded.intervals, [])

    def test_crash_recover_no_mtime_drops_open(self):
        payload = {
            "version": 1,
            "intervals": [],
            "open": {"task_id": "T", "title": "顶", "leaf_id": None, "leaf_title": None, "start": 100.0},
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_log(self.path, data_mtime=None, now=160.0)
        self.assertIsNone(loaded.open)
        self.assertEqual(loaded.intervals, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m unittest tests.test_runtime_intervals.IntervalPersistTests -v`

Expected: `FAIL` importing `load_log` / `save_log`

- [ ] **Step 3: Write minimal implementation**

Add to `src/runtime_intervals.py`:

```python
import json
import os
import tempfile
import time
from pathlib import Path

from .storage import get_data_dir

FILE_NAME = "runtime_intervals.json"


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
```

On `RuntimeIntervalLog`, add:

```python
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
```

```python
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
        raw_intervals = data.get("intervals") or []
        log.intervals = [RuntimeInterval.from_dict(x) for x in raw_intervals]
        open_d = data.get("open")
        if open_d:
            opened = RuntimeInterval.from_dict(open_d)
            if opened.end is not None:
                log.intervals.append(opened)
            else:
                log.open = opened
                if recover:
                    log.recover_open(data_mtime=data_mtime, now=now)
        return log
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
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
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv\Scripts\python.exe -m unittest tests.test_runtime_intervals -v`

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/runtime_intervals.py tests/test_runtime_intervals.py
git commit -m "运行时段日志写入独立 json，损坏则归档重置"
```

---

### Task 3: Week query, day split, stable color

**Files:**
- Modify: `src/runtime_intervals.py`
- Modify: `tests/test_runtime_intervals.py`

**Interfaces:**
- Consumes: `RuntimeIntervalLog.intervals` / `.open`
- Produces:
  - `class DaySlice` with `date: str` (`YYYY-MM-DD`), `t0: float`, `t1: float` (hours in `[0, 24]`), plus the four identity/title fields
  - `local_week_start(now: float) -> float` — local Monday 00:00 containing `now`
  - `add_weeks(week_start: float, n: int) -> float`
  - `slices_for_week(log: RuntimeIntervalLog, week_start: float, now: float) -> list[DaySlice]`
  - `identity_color(task_id: str, leaf_id: Optional[str]) -> str`
  - `PALETTE: tuple[str, ...]` length 8

- [ ] **Step 1: Write the failing tests**

```python
from datetime import datetime, timedelta

from src.runtime_intervals import (
    RuntimeIntervalLog,
    add_weeks,
    identity_color,
    local_week_start,
    slices_for_week,
)


def _local(y, m, d, hh, mm=0, ss=0) -> float:
    return datetime(y, m, d, hh, mm, ss).timestamp()


class WeekSliceTests(unittest.TestCase):
    def test_week_start_is_monday(self):
        # 2026-09-02 is Wednesday
        start = local_week_start(_local(2026, 9, 2, 15))
        monday = datetime.fromtimestamp(start)
        self.assertEqual(monday.weekday(), 0)
        self.assertEqual(monday.hour, 0)
        self.assertEqual(monday.day, 31)
        self.assertEqual(monday.month, 8)

    def test_split_across_midnight(self):
        log = RuntimeIntervalLog()
        log.tick(
            recording=True, task_id="T", title="顶",
            leaf_id="L", leaf_title="叶",
            now=_local(2026, 8, 31, 23, 0),
        )
        log.tick(
            recording=False, task_id=None,
            now=_local(2026, 9, 1, 1, 0),
        )
        week = local_week_start(_local(2026, 8, 31, 12))
        parts = slices_for_week(log, week, _local(2026, 9, 2, 0))
        dates = [p.date for p in parts]
        self.assertIn("2026-08-31", dates)
        self.assertIn("2026-09-01", dates)
        mon = next(p for p in parts if p.date == "2026-08-31")
        tue = next(p for p in parts if p.date == "2026-09-01")
        self.assertAlmostEqual(mon.t0, 23.0, places=5)
        self.assertAlmostEqual(mon.t1, 24.0, places=5)
        self.assertAlmostEqual(tue.t0, 0.0, places=5)
        self.assertAlmostEqual(tue.t1, 1.0, places=5)
        self.assertEqual(mon.leaf_id, "L")
        self.assertEqual(tue.leaf_title, "叶")

    def test_week_query_excludes_other_weeks(self):
        log = RuntimeIntervalLog()
        log.tick(recording=True, task_id="T", title="顶", now=_local(2026, 8, 20, 10))
        log.tick(recording=False, task_id=None, now=_local(2026, 8, 20, 12))
        week = local_week_start(_local(2026, 8, 31, 12))
        self.assertEqual(slices_for_week(log, week, _local(2026, 9, 2, 0)), [])

    def test_open_interval_uses_now_as_end(self):
        log = RuntimeIntervalLog()
        log.tick(recording=True, task_id="T", title="顶", now=_local(2026, 9, 2, 9, 0))
        week = local_week_start(_local(2026, 9, 2, 12))
        parts = slices_for_week(log, week, _local(2026, 9, 2, 10, 0))
        self.assertEqual(len(parts), 1)
        self.assertAlmostEqual(parts[0].t0, 9.0, places=5)
        self.assertAlmostEqual(parts[0].t1, 10.0, places=5)

    def test_identity_color_stable_and_leaf_differs(self):
        a = identity_color("T", "A")
        b = identity_color("T", "B")
        self.assertEqual(a, identity_color("T", "A"))
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("#"))

    def test_add_weeks(self):
        week = local_week_start(_local(2026, 8, 31, 12))
        nxt = add_weeks(week, 1)
        self.assertEqual(datetime.fromtimestamp(nxt).day, 7)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m unittest tests.test_runtime_intervals.WeekSliceTests -v`

Expected: `FAIL` importing `slices_for_week`

- [ ] **Step 3: Write minimal implementation**

Add to `src/runtime_intervals.py`:

```python
import zlib
from datetime import datetime, timedelta

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


def identity_color(task_id: str, leaf_id: Optional[str]) -> str:
    key = f"{task_id}\0{leaf_id or ''}".encode("utf-8")
    return PALETTE[zlib.crc32(key) % len(PALETTE)]


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
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv\Scripts\python.exe -m unittest tests.test_runtime_intervals -v`

Expected: all PASS. If `test_week_start_is_monday` fails because the machine TZ is not UTC+8, keep using naive `datetime` local time — 2026-09-02 local Wednesday still has Monday 8-31 in any TZ that does not jump the calendar date. If a TZ test fails, switch the fixture to `datetime.fromtimestamp(local_week_start(now)).weekday() == 0` plus `hour == 0` without asserting month/day, **and** keep the midnight-split test which uses the same `_local` helper (self-consistent).

- [ ] **Step 5: Commit**

```bash
git add src/runtime_intervals.py tests/test_runtime_intervals.py
git commit -m "运行时段按自然周切开，跨午夜落在相邻两天"
```

---

### Task 4: Drive the log from TaskManager and Application save

**Files:**
- Modify: `src/task_manager.py`
- Modify: `src/main.py`
- Modify: `tests/test_task_manager.py`
- Modify: `tests/test_runtime_intervals.py` only if you add a helper test here instead — prefer `tests/test_task_manager.py`

**Interfaces:**
- Consumes: `RuntimeIntervalLog.tick`, `load_log`, `save_log`, `intervals_path`
- Produces:
  - `TaskManager.runtime_log: RuntimeIntervalLog`
  - `TaskManager._intervals_path: Optional[Path]` (tests inject a temp path)
  - `TaskManager._recording_identity(counting: bool) -> tuple[bool, Optional[str], str, Optional[str], Optional[str]]` → `(recording, task_id, title, leaf_id, leaf_title)`
  - `TaskManager.persist_runtime_log() -> None` — swallows `OSError`, logs warning
  - `TaskManager.load_runtime_log(*, data_mtime: Optional[float] = None) -> None`
  - `TaskManager.close_runtime_log(now: Optional[float] = None) -> None` — `close_open` then persist
  - `tick_active_time` calls `runtime_log.tick` **even when `seconds == 0`** (first ActiveTimeTracker tick)
  - `Application.__init__` after `TaskManager(...)`: `self.manager.load_runtime_log(data_mtime=get_data_file().stat().st_mtime if get_data_file().exists() else None)`
  - `_safe_save` / `_auto_save`: also `self.manager.persist_runtime_log()`
  - `quit`: `self.manager.close_runtime_log()` then `_safe_save`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_task_manager.py`:

```python
import tempfile
from pathlib import Path
from unittest import mock

from src.runtime_intervals import load_log


class RuntimeLogHookTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "runtime_intervals.json"
        self.state, self.manager = _make()
        self.manager._intervals_path = self.path
        self.manager.note_activity()

    def test_tick_opens_for_flat_task(self):
        t = self.manager.create("甲")
        with mock.patch("src.task_manager.time.time", return_value=1_000.0):
            self.manager.tick_active_time()
        self.assertIsNotNone(self.manager.runtime_log.open)
        self.assertEqual(self.manager.runtime_log.open.task_id, t.id)
        self.assertIsNone(self.manager.runtime_log.open.leaf_id)

    def test_pause_closes_interval(self):
        t = self.manager.create("甲")
        with mock.patch("src.task_manager.time.time", return_value=1_000.0):
            self.manager.tick_active_time()
        self.manager.pause(t.id)
        with mock.patch("src.task_manager.time.time", return_value=1_030.0):
            self.manager.tick_active_time()
        self.assertIsNone(self.manager.runtime_log.open)
        self.assertEqual(self.manager.runtime_log.intervals[0].end, 1_030.0)

    def test_switch_leaf_splits(self):
        t = self.manager.create("甲")
        a = self.manager.add_subtask(t.id, "A", target_minutes=10)
        b = self.manager.add_subtask(t.id, "B", target_minutes=10)
        self.manager.focus_subtask(t.id, a.id)
        with mock.patch("src.task_manager.time.time", return_value=1_000.0):
            self.manager.tick_active_time()
        self.manager.focus_subtask(t.id, b.id)
        with mock.patch("src.task_manager.time.time", return_value=1_040.0):
            self.manager.tick_active_time()
        self.assertEqual(self.manager.runtime_log.intervals[0].leaf_id, a.id)
        self.assertEqual(self.manager.runtime_log.open.leaf_id, b.id)

    def test_unfocused_tree_does_not_record(self):
        t = self.manager.create("甲")
        self.manager.add_subtask(t.id, "A", target_minutes=10)
        t.current_subtask_id = None
        with mock.patch("src.task_manager.time.time", return_value=1_000.0):
            self.manager.tick_active_time()
        self.assertIsNone(self.manager.runtime_log.open)

    def test_persist_on_close(self):
        self.manager.create("甲")
        with mock.patch("src.task_manager.time.time", return_value=1_000.0):
            self.manager.tick_active_time()
        with mock.patch("src.task_manager.time.time", return_value=1_020.0):
            self.manager.pause(self.state.active_task().id)
            self.manager.tick_active_time()
        loaded = load_log(self.path, now=1_020.0)
        self.assertEqual(len(loaded.intervals), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m unittest tests.test_task_manager.RuntimeLogHookTests -v`

Expected: `FAIL` (`TaskManager` has no `runtime_log`)

- [ ] **Step 3: Write minimal implementation**

In `src/task_manager.py`:

- Import `Path` from `pathlib`, `RuntimeIntervalLog`, `load_log`, `save_log`, `intervals_path` from `.runtime_intervals`.
- In `__init__`, after `_active_time`:

```python
self.runtime_log = RuntimeIntervalLog()
self._intervals_path: Optional[Path] = None
```

- Add methods:

```python
def _recording_identity(
    self, counting: bool
) -> tuple[bool, Optional[str], str, Optional[str], Optional[str]]:
    if not counting:
        return False, None, "", None, None
    active = self.state.active_task()
    if active is None:
        return False, None, "", None, None
    if active.subtasks:
        sub = active.current_subtask()
        if sub is None:
            return False, None, "", None, None
        return True, active.id, active.title, sub.id, sub.title
    return True, active.id, active.title, None, None

def persist_runtime_log(self) -> None:
    path = self._intervals_path or intervals_path()
    try:
        save_log(self.runtime_log, path)
    except OSError:
        logger.warning("写入运行日志失败", exc_info=True)

def load_runtime_log(self, *, data_mtime: Optional[float] = None) -> None:
    path = self._intervals_path or intervals_path()
    self.runtime_log = load_log(path, data_mtime=data_mtime, now=time.time())

def close_runtime_log(self, now: Optional[float] = None) -> None:
    self.runtime_log.close_open(time.time() if now is None else now)
    self.persist_runtime_log()
```

- Replace `tick_active_time` with:

```python
def tick_active_time(self) -> bool:
    """每秒调用：累加聚焦叶子或扁平目标时长（关屏 / 空闲不计）。"""
    counting = self.power_monitor.should_count_time() and not self._is_idle()
    seconds = self._active_time.tick(counting_enabled=counting)
    rec, task_id, title, leaf_id, leaf_title = self._recording_identity(counting)
    mutated = self.runtime_log.tick(
        recording=rec,
        task_id=task_id,
        title=title,
        leaf_id=leaf_id,
        leaf_title=leaf_title,
        now=time.time(),
    )
    if mutated:
        self.persist_runtime_log()
    active = self.state.active_task()
    if active is None or seconds <= 0:
        return False
    if active.subtasks:
        sub = active.current_subtask()
        if sub is not None:
            sub.active_seconds += seconds
    else:
        active.active_seconds += seconds
    return False
```

Existing `test_tick_active_time_*` must still pass (they mock `time.monotonic` only; `time.time` for the log is fine).

In `src/main.py`:

- Import `get_data_file` from `.storage` (already imports `load_state` / `save_state` / `get_data_dir` — add `get_data_file` to that import).
- After `self.manager = TaskManager(...)`:

```python
data_path = get_data_file()
mtime = data_path.stat().st_mtime if data_path.exists() else None
self.manager.load_runtime_log(data_mtime=mtime)
```

- `_safe_save`: after successful `save_state(self.state)`, call `self.manager.persist_runtime_log()`. On `SaveRejectedError` / other save failure, still try `persist_runtime_log()` so intervals are not blocked by a rejected `data.json` (intervals are independent). Call persist in a nested try so interval IO errors never surface as the data-save dialog.

```python
def _persist_runtime_quiet(self) -> None:
    try:
        self.manager.persist_runtime_log()
    except Exception:
        logger.warning("运行日志保存失败", exc_info=True)
```

Call `_persist_runtime_quiet()` at the end of `_safe_save` (both success and failure paths) and `_auto_save`.

- `quit`: before `_safe_save()`:

```python
try:
    self.manager.close_runtime_log()
except Exception:
    logger.warning("退出时关闭运行段失败", exc_info=True)
```

(`close_runtime_log` already persists; `_safe_save` persisting again is idempotent.)

- [ ] **Step 4: Run the tests and make sure they pass**

Run:

```
.venv\Scripts\python.exe -m unittest tests.test_task_manager tests.test_runtime_intervals -v
```

Expected: all PASS, including old `test_tick_active_time_*`.

- [ ] **Step 5: Commit**

```bash
git add src/task_manager.py src/main.py tests/test_task_manager.py
git commit -m "运行时段随 tick 记账，存档和退出时写盘"
```

---

### Task 5: Week panel widget (status, grid, legend)

**Files:**
- Create: `src/ui_week_runtime.py`
- Modify: `tests/test_runtime_intervals.py` (formatters can live next to grid tests, or add `tests/test_week_runtime_text.py` — keep formatters tests in `tests/test_runtime_intervals.py` only if they import UI; **prefer** putting text helpers in `src/ui_week_runtime.py` and testing them in `tests/test_task_dialog_week.py` Task 6. For TDD this task, add `tests/test_week_runtime_text.py`.)

**Interfaces:**
- Consumes: `slices_for_week`, `local_week_start`, `add_weeks`, `identity_color`, `DaySlice`, `RuntimeIntervalLog`, `format_duration` from `ui_text`, `AppState`
- Produces:
  - `format_running_status(state: AppState) -> str`
  - `format_slice_hover(slice: DaySlice) -> str`
  - `format_legend_label(title: str, leaf_title: Optional[str], *, running: bool) -> str`
  - `format_clock_hours(hours: float) -> str` → `09:00` / `24:00`
  - `class WeekRuntimePanel(QWidget)`:
    - `__init__(state: AppState, manager: TaskManager, parent=None)`
    - `refresh() -> None`
    - `grid` with `column_count == 7` (attribute for tests)
    - Prev/next week buttons; next disabled when `add_weeks(week_start, 1) > local_week_start(now)`
    - 1s `QTimer` started in `showEvent`, stopped in `hideEvent`
    - Reset hint QLabel visible iff `manager.runtime_log.load_reset`

Exact copy:

| Situation | String |
|-----------|--------|
| Leaf focused | `正在运行  顶层「{top}」  ·  「{leaf}」` |
| Flat active | `正在运行  顶层「{top}」` |
| Else | `当前没有运行中的目标` |
| Hover with leaf | `{top} · {leaf}  {t0}–{t1}  （{dur}）` |
| Hover flat | `{top}  {t0}–{t1}  （{dur}）` |
| Legend running | `{label}  运行中` |
| Reset | `运行记录已重置` |

- [ ] **Step 1: Write the failing tests**

Create `tests/test_week_runtime_text.py`:

```python
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import AppState
from src.runtime_intervals import DaySlice
from src.task_manager import TaskManager
from src.ui_week_runtime import (
    format_clock_hours,
    format_legend_label,
    format_running_status,
    format_slice_hover,
)
from src.power_monitor import PowerMonitor


class WeekRuntimeTextTests(unittest.TestCase):
    def test_status_leaf_and_flat_and_idle(self):
        state = AppState()
        m = TaskManager(state, PowerMonitor())
        self.assertEqual(format_running_status(state), "当前没有运行中的目标")
        t = m.create("写文档")
        self.assertEqual(format_running_status(state), "正在运行  顶层「写文档」")
        leaf = m.add_subtask(t.id, "第 3 章", target_minutes=10)
        t.current_subtask_id = None
        self.assertEqual(format_running_status(state), "当前没有运行中的目标")
        m.focus_subtask(t.id, leaf.id)
        self.assertEqual(
            format_running_status(state),
            "正在运行  顶层「写文档」  ·  「第 3 章」",
        )

    def test_hover_and_clock(self):
        sl = DaySlice(
            date="2026-09-02", t0=9.0, t1=11.0 + 20 / 60.0,
            task_id="T", title="写文档", leaf_id="L", leaf_title="第 3 章",
        )
        self.assertEqual(format_clock_hours(9.0), "09:00")
        self.assertEqual(format_clock_hours(24.0), "24:00")
        text = format_slice_hover(sl)
        self.assertIn("写文档 · 第 3 章", text)
        self.assertIn("09:00", text)
        self.assertIn("11:20", text)
        flat = DaySlice(
            date="2026-09-02", t0=9.0, t1=10.0,
            task_id="T", title="写文档", leaf_id=None, leaf_title=None,
        )
        self.assertNotIn("·", format_slice_hover(flat))

    def test_legend_running_suffix(self):
        self.assertEqual(
            format_legend_label("写文档", "第 3 章", running=True),
            "写文档 · 第 3 章  运行中",
        )
        self.assertEqual(
            format_legend_label("写文档", None, running=False),
            "写文档",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m unittest tests.test_week_runtime_text -v`

Expected: `ModuleNotFoundError: src.ui_week_runtime`

- [ ] **Step 3: Write minimal implementation**

Create `src/ui_week_runtime.py` with the formatters **and** the panel.

Formatters:

```python
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .models import AppState
from .runtime_intervals import (
    DaySlice,
    add_weeks,
    identity_color,
    local_week_start,
    slices_for_week,
)
from .task_manager import TaskManager
from .ui_styles import FONT_FAMILY, TEXT_MUTED, TEXT_PRIMARY
from .ui_text import format_duration


def format_running_status(state: AppState) -> str:
    active = state.active_task()
    if active is None:
        return "当前没有运行中的目标"
    if active.subtasks:
        leaf = active.current_subtask()
        if leaf is None:
            return "当前没有运行中的目标"
        return f"正在运行  顶层「{active.title}」  ·  「{leaf.title}」"
    return f"正在运行  顶层「{active.title}」"


def format_clock_hours(hours: float) -> str:
    total = int(round(float(hours) * 3600))
    total = max(0, min(24 * 3600, total))
    h, rem = divmod(total, 3600)
    m = rem // 60
    if h >= 24:
        return "24:00"
    return f"{h:02d}:{m:02d}"


def format_slice_hover(sl: DaySlice) -> str:
    t0 = format_clock_hours(sl.t0)
    t1 = format_clock_hours(sl.t1)
    dur = format_duration((sl.t1 - sl.t0) * 3600)
    if sl.leaf_title:
        return f"{sl.title} · {sl.leaf_title}  {t0}–{t1}  （{dur}）"
    return f"{sl.title}  {t0}–{t1}  （{dur}）"


def format_legend_label(title: str, leaf_title: Optional[str], *, running: bool) -> str:
    base = f"{title} · {leaf_title}" if leaf_title else title
    if running:
        return f"{base}  运行中"
    return base
```

`WeekGrid(QWidget)`:

- `column_count = 7`
- `set_slices(slices: list[DaySlice], *, week_start: float, now: float, open_identity: Optional[tuple])`
- `paintEvent`: left gutter 28px for `0 6 12 18 24` (0 at top). Seven equal columns. Header 22px: weekday `一`…`日` plus `datetime.fromtimestamp(week_start) + timedelta(days=i)` formatted `%-d` (on Windows use `day` via `strftime("%d").lstrip("0")` or `f"{dt.day:02d}"` matching spec `一 31`). Fill each slice as `QRect` with `identity_color`. If `open_identity == slice.identity()` and slice is today, draw a 1px lighter outline. Today: horizontal now-line at `wall hour / 24`.
- `mouseMoveEvent`: hit-test slices, `QToolTip.showText` with `format_slice_hover`.

`WeekRuntimePanel(QWidget)`:

```python
class WeekRuntimePanel(QWidget):
    def __init__(self, state: AppState, manager: TaskManager, parent=None):
        super().__init__(parent)
        self.state = state
        self.manager = manager
        self._week_start = local_week_start(time.time())
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("←")
        self.btn_next = QPushButton("→")
        self.lbl_range = QLabel("")
        self.lbl_range.setAlignment(Qt.AlignCenter)
        self.btn_prev.clicked.connect(self._prev_week)
        self.btn_next.clicked.connect(self._next_week)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.lbl_range, 1)
        nav.addWidget(self.btn_next)
        self.lbl_status = QLabel("")
        self.lbl_reset = QLabel("运行记录已重置")
        self.lbl_reset.setStyleSheet(f"color: {TEXT_MUTED};")
        self.lbl_reset.hide()
        self.grid = WeekGrid(self)
        self.grid.setMinimumHeight(280)
        self.grid.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.legend = QLabel("")
        self.legend.setWordWrap(True)
        self.legend.setStyleSheet(f"color: {TEXT_PRIMARY}; font-family: {FONT_FAMILY};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(nav)
        lay.addWidget(self.lbl_status)
        lay.addWidget(self.lbl_reset)
        lay.addWidget(self.grid, 1)
        lay.addWidget(self.legend)
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()
        self.refresh()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _prev_week(self) -> None:
        self._week_start = add_weeks(self._week_start, -1)
        self.refresh()

    def _next_week(self) -> None:
        nxt = add_weeks(self._week_start, 1)
        if nxt <= local_week_start(time.time()):
            self._week_start = nxt
            self.refresh()

    def refresh(self) -> None:
        now = time.time()
        current = local_week_start(now)
        self.btn_next.setEnabled(add_weeks(self._week_start, 1) <= current)
        mon = datetime.fromtimestamp(self._week_start)
        sun = mon + timedelta(days=6)
        self.lbl_range.setText(
            f"{mon.strftime('%Y-%m-%d')} ~ {sun.strftime('%Y-%m-%d')}"
        )
        self.lbl_status.setText(format_running_status(self.state))
        self.lbl_reset.setVisible(self.manager.runtime_log.load_reset)
        slices = slices_for_week(self.manager.runtime_log, self._week_start, now)
        ident = None
        rec, task_id, _t, leaf_id, _lt = self.manager._recording_identity(
            self.manager.power_monitor.should_count_time()
            and not self.manager._is_idle()
        )
        if rec and task_id:
            ident = (task_id, leaf_id)
        self.grid.set_slices(
            slices, week_start=self._week_start, now=now, open_identity=ident
        )
        # legend: unique identities in slices order
        seen: list[tuple] = []
        labels = []
        for sl in slices:
            key = sl.identity()
            if key in seen:
                continue
            seen.append(key)
            running = ident == key
            labels.append(format_legend_label(sl.title, sl.leaf_title, running=running))
        self.legend.setText("    ".join(labels))
```

WeekGrid painting details the implementer must follow:

```python
WEEKDAYS = "一二三四五六日"
GUTTER = 28
HEADER = 22

class WeekGrid(QWidget):
    column_count = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slices: list[DaySlice] = []
        self._week_start = 0.0
        self._now = 0.0
        self._open_identity = None
        self._col_rects: list[QRect] = []
        self.setMouseTracking(True)

    def set_slices(self, slices, *, week_start, now, open_identity):
        self._slices = slices
        self._week_start = week_start
        self._now = now
        self._open_identity = open_identity
        self.update()

    def _body_rect(self) -> QRect:
        return QRect(
            GUTTER, HEADER,
            max(1, self.width() - GUTTER),
            max(1, self.height() - HEADER),
        )

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setFont(QFont("Microsoft YaHei UI", 8))
        body = self._body_rect()
        col_w = body.width() / 7.0
        self._col_rects = []
        for i in range(7):
            x = int(body.x() + i * col_w)
            w = int(body.x() + (i + 1) * col_w) - x
            self._col_rects.append(QRect(x, body.y(), w, body.height()))
        p.setPen(QColor(TEXT_MUTED))
        for hour in (0, 6, 12, 18, 24):
            y = body.y() + int(body.height() * (hour / 24.0))
            p.drawText(0, y - 6, GUTTER - 2, 12, int(Qt.AlignRight | Qt.AlignVCenter), str(hour))
        mon = datetime.fromtimestamp(self._week_start)
        today = datetime.fromtimestamp(self._now).date()
        for i, rect in enumerate(self._col_rects):
            day = mon + timedelta(days=i)
            p.setPen(QColor(TEXT_PRIMARY))
            p.drawText(
                rect.x(), 0, rect.width(), HEADER,
                int(Qt.AlignCenter),
                f"{WEEKDAYS[i]} {day.day:02d}",
            )
            p.setPen(QColor("#2a2d38"))
            p.drawRect(rect.adjusted(0, 0, -1, -1))
        for sl in self._slices:
            idx = (datetime.strptime(sl.date, "%Y-%m-%d").date() - mon.date()).days
            if idx < 0 or idx > 6:
                continue
            rect = self._col_rects[idx]
            y0 = rect.y() + int(rect.height() * (sl.t0 / 24.0))
            y1 = rect.y() + int(rect.height() * (sl.t1 / 24.0))
            block = QRect(rect.x() + 2, y0, rect.width() - 4, max(2, y1 - y0))
            color = QColor(identity_color(sl.task_id, sl.leaf_id))
            p.fillRect(block, color)
            if self._open_identity == sl.identity() and datetime.strptime(sl.date, "%Y-%m-%d").date() == today:
                p.setPen(QPen(color.lighter(140), 2))
                p.drawRect(block.adjusted(0, 0, -1, -1))
        now_dt = datetime.fromtimestamp(self._now)
        if mon.date() <= now_dt.date() <= (mon + timedelta(days=6)).date():
            idx = (now_dt.date() - mon.date()).days
            rect = self._col_rects[idx]
            hour = now_dt.hour + now_dt.minute / 60.0 + now_dt.second / 3600.0
            y = rect.y() + int(rect.height() * (hour / 24.0))
            p.setPen(QPen(QColor("#e8eaf0"), 1))
            p.drawLine(rect.left(), y, rect.right(), y)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        mon = datetime.fromtimestamp(self._week_start)
        for sl in self._slices:
            idx = (datetime.strptime(sl.date, "%Y-%m-%d").date() - mon.date()).days
            if idx < 0 or idx > 6 or idx >= len(self._col_rects):
                continue
            rect = self._col_rects[idx]
            y0 = rect.y() + int(rect.height() * (sl.t0 / 24.0))
            y1 = rect.y() + int(rect.height() * (sl.t1 / 24.0))
            block = QRect(rect.x() + 2, y0, rect.width() - 4, max(2, y1 - y0))
            if block.contains(pos):
                QToolTip.showText(event.globalPosition().toPoint(), format_slice_hover(sl), self)
                return
        QToolTip.hideText()
```

Avoid calling `_is_idle` if you want a stricter public API: duplicate the recording check via a new `TaskManager.recording_identity() -> tuple[...]` public method (same body as `_recording_identity` using internal counting). Prefer renaming to public `recording_identity(self) -> tuple[...]` that computes `counting` itself, and keep `_recording_identity(counting)` private. Panel then calls `manager.recording_identity()`.

Add public method on `TaskManager`:

```python
def recording_identity(
    self,
) -> tuple[bool, Optional[str], str, Optional[str], Optional[str]]:
    counting = self.power_monitor.should_count_time() and not self._is_idle()
    return self._recording_identity(counting)
```

Panel uses `self.manager.recording_identity()`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `.venv\Scripts\python.exe -m unittest tests.test_week_runtime_text tests.test_task_manager tests.test_runtime_intervals -v`

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/ui_week_runtime.py src/task_manager.py tests/test_week_runtime_text.py
git commit -m "本周面板文案与七列小时格绘制"
```

---

### Task 6: Goal Manager tab + offscreen check

**Files:**
- Modify: `src/task_dialog.py`
- Create: `tests/test_task_dialog_week.py`

**Interfaces:**
- Consumes: `WeekRuntimePanel`
- Produces: fourth tab titled `本周`; dialog default size `640 x 640`; `refresh_stats` and `refresh` call `self.week_panel.refresh()`; existing tabs 0–2 texts unchanged

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_dialog_week.py`:

```python
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from src.models import AppState
from src.power_monitor import PowerMonitor
from src.task_dialog import TaskDialog
from src.task_manager import TaskManager

_app = QApplication.instance() or QApplication([])


class TaskDialogWeekTabTests(unittest.TestCase):
    def test_has_week_tab_with_seven_columns(self):
        state = AppState()
        manager = TaskManager(state, PowerMonitor())
        dlg = TaskDialog(state, manager)
        self.assertEqual(dlg.tabs.count(), 4)
        self.assertEqual(dlg.tabs.tabText(3), "本周")
        self.assertEqual(dlg.week_panel.grid.column_count, 7)
        self.assertGreaterEqual(dlg.width(), 540)
        dlg.refresh_stats()
        dlg.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m unittest tests.test_task_dialog_week -v`

Expected: `FAIL` `tabs.count() == 3` or missing `week_panel`

- [ ] **Step 3: Write minimal implementation**

In `src/task_dialog.py`:

- Import `WeekRuntimePanel` from `.ui_week_runtime`.
- Change `self.resize(540, 640)` to `self.resize(640, 640)`.
- In `_build`, after the three status tabs:

```python
self.week_panel = WeekRuntimePanel(self.state, self.manager)
self.tabs.addTab(self.week_panel, "本周")
```

- In `refresh_stats`, after updating cards:

```python
self.week_panel.refresh()
```

- In `refresh`, after filling the three list tabs (do not change `setTabText` indices 0–2):

```python
self.week_panel.refresh()
```

Do not touch `src/widget.py`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run:

```
.venv\Scripts\python.exe -m unittest tests.test_task_dialog_week tests.test_week_runtime_text tests.test_task_manager tests.test_runtime_intervals tests.test_widget_smoke -v
```

Expected: all PASS. `test_widget_smoke` still ≤ 600 height (floating widget unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/task_dialog.py tests/test_task_dialog_week.py
git commit -m "目标管理增加本周 Tab，七列显示顶层与叶子时段"
```

---

## Self-review (spec coverage)

| Spec item | Task |
|-----------|------|
| Separate `runtime_intervals.json`, schema version 1, title snapshots, leaf fields | 1–2 |
| `recording` same as active time; switch leaf/top splits; flat `leaf_id=null` | 1, 4 |
| Discard < 1s; merge same identity gap < 2s | 1 |
| Crash: `data.json` mtime; missing file drops open; stale > 1h drops | 2 |
| Clock jump back drops open; forward closes at last now | 1 |
| Week Mon–Sun local; midnight split; open uses now | 3 |
| Tab 本周 only in Goal Manager; 7 columns hours 0 top; now line; hover; legend 运行中 | 5–6 |
| Status line top + leaf | 5 |
| Corrupt → broken file + `运行记录已重置` | 2, 5 |
| Persist every 15s via auto-save; immediate on mutate/quit | 4 |
| No floating widget axis; no `data.json` intervals; no backfill | 4, 6 (non-goals) |
| unittest list in spec | 1–6 |

No remaining TBD. Public `TaskManager.recording_identity()` is the name later tasks must use (Task 5 panel, Task 4 tick).
