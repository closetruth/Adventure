# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bat
REM Install venv + dependencies
install.bat

REM Run the app (no console window)
run.bat

REM Manual run (dev)
.venv\Scripts\pythonw.exe run.py

REM Run a game subprocess standalone (debugging)
python run.py --game pet <session_in.json>
python run.py --game grid <session_in.json>

REM Fix pygame-ce only (when games fail to start)
fix_game.bat

REM Build redistributable .exe
build.bat
```

- **Python 3.12 or 3.13** recommended. Python 3.14 **must** use `pygame-ce`, not the official `pygame` wheel (requirements.txt already pins `pygame-ce`).
- No test suite exists in this repo — verify changes by running the app manually.

## Architecture

### Entry point

`run.py` is the single entry point. Without `--game`, it calls `src.main.main()` — the PySide6 Qt desktop app. With `--game`, it dispatches to `games/pet_arena.py` or `games/pixel_tactics.py` as a **subprocess** launched by the main app.

### Threading model

```
pynput listener (daemon thread)
    └─ on_op callback ──→ OpBridge.op_happened (Qt Signal, QueuedConnection)
                              └─ Application._on_operation() (main thread)
                                   ├─ maybe_roll(state)
                                   ├─ TaskManager.record_operation()
                                   └─ widget.refresh() + dialog refreshes
```

- **pynput** runs two daemon listeners (keyboard + mouse) in background threads. Each *first press* (not hold-repeat) fires the callback once.
- `OpBridge` (a `QObject`) bridges the listener thread to the Qt main thread via `Signal` + `QueuedConnection`.
- All state mutation happens on the main thread — no manual locking needed beyond the listener's internal dedup sets.

### Data model (`src/models.py`)

- `AppState` is the single root state object — inventory, task list, roll history, settings dict.
- `Task` has `status: ACTIVE | PAUSED | COMPLETED`. Only **one** ACTIVE task is allowed at a time.
- `Reward` is a simple gold+diamond value object.
- `RollAccum` tracks rewards accumulated *since* the last roll checkpoint (stored per-task for display).

### Core modules

| Module | Role |
|--------|------|
| `src/main.py` | `Application` class: wires everything — Qt app, tray, widget, input monitor, timers, dialogs |
| `src/widget.py` | `FloatingWidget`: frameless topmost window, drag, right-click menu, 1s refresh timer |
| `src/task_manager.py` | `TaskManager`: CRUD + state transitions (create/pause/resume/complete/delete) + operation recording |
| `src/reward_system.py` | `maybe_roll(state)`: roll check on each operation; mutates state inline, returns `Reward` or `None` |
| `src/input_monitor.py` | `InputMonitor`: pynput wrapper with key/button dedup; optional (gracefully degrades if pynput missing) |
| `src/storage.py` | `load_state()` / `save_state()`: atomic JSON persistence to `%APPDATA%\Adventure\data.json`; corrupt data → backup to `.broken.json` |
| `src/game_launcher.py` | `launch_pet_arena()` / `launch_pixel_tactics()`: validate entry cost, write session JSON, spawn subprocess, read result JSON, update state |
| `src/game_protocol.py` | `GameSession` / `GameResult` dataclasses: JSON protocol between main app and game subprocess via `%APPDATA%\Adventure\game_sessions\` |

### UI helpers

- `src/ui_task_stats.py` — `TaskRewardStrip`: the big-number chips (task ops, pending gold/diamond, 1-min rate, since-roll) on the floating widget.
- `src/ui_text.py` — formatting functions: amounts (max 1 decimal), durations, roll history lines. **No emoji** — intentional, because Windows default fonts render them as tofu.
- `src/op_tracker.py` — `OpRateTracker`: sliding 60s window of operation timestamps (in-memory only, not persisted).
- `src/active_time.py` — `ActiveTimeTracker`: increments `active_seconds` on the active task every 1s tick; paused tasks don't tick.
- `src/win_utils.py` — `pin_window_to_all_desktops` (pyvda), `set_startup` (registry Run key). Graceful no-ops on non-Windows.

### Game subprocess protocol

1. Main app writes `{session_id}_in.json` → spawns `python run.py --game <type> <in_path>`.
2. Game reads the session file, runs, writes `{session_id}_out.json` (a `GameResult`).
3. Main app reads the result, validates `session_id`, updates inventory.

### Settings (in `data.json` → `settings`)

Key tunables: `roll_interval` (ops per roll), `roll_chance`, `gold_min`/`gold_max`, `diamond_chance`, `diamond_min`/`diamond_max`. Defaults in `AppState.__init__` (`src/models.py`).

### Save behavior

- Auto-save every 15 seconds (`QTimer` in `Application.__init__`).
- Save on quit.
- Atomic write: tempfile → `os.replace()` (avoids corrupting the file on crash mid-write).

## Style notes

- All `src/` files use `from __future__ import annotations` for deferred evaluation.
- Type hints throughout (`from typing import Optional, List, Dict, ...`).
- Qt stylesheets are module-level constants (e.g. `WIDGET_STYLESHEET`, `TASK_STATS_QSS`).
- String formatting uses f-strings; `%APPDATA%` resolved via `os.environ`.
- Games are in `games/` and import `pygame-ce`; they receive session data via CLI arg, not stdin.
