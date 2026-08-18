# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

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
QTimer @ 50ms (main thread)
 └─ GetAsyncKeyState 轮询 ──→ _count_op() ──→ OpBridge.op_happened (Qt Signal, AutoConnection)
 └─ Application._on_operation() (main thread)
 ├─ maybe_roll(state)
 ├─ TaskManager.record_operation()
 └─ widget.refresh() + dialog refreshes
```

- **InputMonitor** uses a `QTimer` (50ms) to poll keyboard/mouse state via `GetAsyncKeyState`. No system-wide hooks. Detects first-press transitions (not hold-repeat). Falls back to pynput hooks on non-Windows.
- `OpBridge` (a `QObject`) emits a Qt `Signal`; `AutoConnection` handles thread detection automatically (polling = same thread, hook = cross-thread).
- All state mutation happens on the main thread — no manual locking needed.

### Data model (`src/models.py`)

- `AppState` is the single root state object — inventory, task list, roll history, `roll_runtime`, settings dict.
- `Task` has `status: ACTIVE | PAUSED | COMPLETED`. Only **one** ACTIVE task is allowed at a time.
- `Task.current_subtask_id` points at the focused **leaf** subtask (when the task has a subtask tree). `Task.active_focus_path_ids()` returns the root-to-leaf path for UI highlighting.
- `Subtask` forms a tree: **leaf** nodes accumulate ops/time/rewards; **container** nodes (`children` non-empty) rollup from descendants via `rollup_operations()`, `rollup_earned()`, etc. Leaves have `target_seconds`, `pending_rewards`, `done`, `rewards_claimed`.
- `Reward` is a simple gold+diamond value object.
- `RollAccum` tracks rewards accumulated *since* the last roll checkpoint (global display).
- `RollRuntime` holds the current roll cycle: `next_roll_at`, `roll_span`, `segment_colors`, `gold_chance` / `diamond_chance`, amount ranges, `last_shuffle_at`. Persisted; `settings` roll fields are migration-only.

### Operation accounting

On each keyboard/mouse op (when an ACTIVE task exists):

1. `maybe_roll(state)` may award gold/diamond (independent gold/diamond rolls at cycle end).
2. `TaskManager.record_operation(reward)`:
   - **No subtasks**: increment `task.operations`; apply roll reward to `task.pending_rewards`.
   - **Has subtasks**: only if `task.current_subtask()` is a non-done leaf — increment that leaf's `operations` and apply roll reward to the leaf's `pending_rewards`; otherwise drop subtask rewards.
3. `tick_active_time()` (1s timer): adds seconds to the focused leaf, or to the flat task when no subtasks. Skips when paused or screen off (`power_monitor`).

Folder-style accounting: parent task `earned_*` / display totals sync from subtask rollup (`sync_earned_from_subtasks`); do not mirror leaf progress into parent fields when subtasks exist.

### Core modules

| Module | Role |
|--------|------|
| `src/main.py` | `Application` class: wires everything — Qt app, tray, widget, input monitor, timers, dialogs |
| `src/widget.py` | `FloatingWidget`: frameless topmost window, **directory-style goal tree**, detail panel, roll bar; deferred refresh via `QTimer.singleShot(0)`; `_refreshing` reentrancy guard |
| `src/task_manager.py` | `TaskManager`: task/subtask CRUD, `focus_subtask` / `start_subtask` / `pause` / `decompose_subtask` / `delete_subtask`; `_subtask_expanded` (in-memory UI only) |
| `src/reward_system.py` | `maybe_roll(state)`, `reshuffle_roll_params`, random 6–14 op cycles, `RollRuntime` migration |
| `src/input_monitor.py` | `InputMonitor`: QTimer + GetAsyncKeyState polling with key/button dedup (pynput hook fallback for non-Windows) |
| `src/storage.py` | `load_state()` / `save_state()`: atomic JSON persistence to `%APPDATA%\Adventure\data.json`; corrupt data → backup to `.broken.json` |
| `src/game_launcher.py` | `launch_pet_arena()` / `launch_pixel_tactics()`: validate entry cost, write session JSON, spawn subprocess, read result JSON, update state |
| `src/game_protocol.py` | `GameSession` / `GameResult` dataclasses: JSON protocol between main app and game subprocess via `%APPDATA%\Adventure\game_sessions\` |
| `src/migrate_accounting.py` | Flat-task → nested subtask migration; `detach_subtask_progress_to_legacy` for decompose |

### UI helpers

- `src/ui_task_tree.py` — `TreeRow`, `build_subtask_action_buttons`, `append_subtask_detail_actions`, `_connect_callback` (wraps `QPushButton.clicked` so `checked` is not passed to user callbacks).
- `src/ui_goal_tree_panel.py` — `GoalTreePanel`: shared goal tree embedded in `TaskCard` (`task_dialog.py`).
- `src/goal_actions.py` — `try_complete_goal`, `try_delete_goal` with confirmation.
- `src/ui_confirm.py` — `ask_yes_no`: topmost styled confirm dialog.
- `src/ui_text.py` — formatting functions: amounts (max 1 decimal), durations, tree node HTML. **No emoji** — intentional, because Windows default fonts render them as tofu.
- `src/ui_roll_bar.py` — `SegmentedRollBar`: colored segment roll progress widget.
- `src/op_tracker.py` — `OpRateTracker`: sliding 60s window of operation timestamps (in-memory only, not persisted).
- `src/active_time.py` — `ActiveTimeTracker`: increments focused leaf or flat task `active_seconds` every 1s tick; paused tasks don't tick.
- `src/power_monitor.py` — `should_count_time()`: false when display is off.
- `src/sfx.py` — roll hit sounds via Qt Multimedia (`QMediaPlayer`).
- `src/win_utils.py` — `pin_window_to_all_desktops` (pyvda), `set_startup` (registry Run key). Graceful no-ops on non-Windows.

### Game subprocess protocol

1. Main app writes `{session_id}_in.json` → spawns `python run.py --game <type> <in_path>`.
2. Game reads the session file, runs, writes `{session_id}_out.json` (a `GameResult`).
3. Main app reads the result, validates `session_id`, updates inventory.

### Settings (in `data.json` → `settings`)

Key tunables: `roll_interval`, `roll_chance` / `gold_chance`, `gold_min`/`gold_max`, `diamond_chance`, `diamond_min`/`diamond_max`, `subtask_default_target_minutes`, `subtask_completion_bonus_gold`, window/sound flags. Runtime roll values live in `roll_runtime`; settings roll fields are for **legacy migration** only. Defaults in `AppState.__init__` (`src/models.py`).

### Save behavior

- Auto-save every 15 seconds (`QTimer` in `Application.__init__`).
- Save on quit.
- Atomic write: tempfile → `os.replace()` (avoids corrupting the file on crash mid-write).

## Style notes

- All `src/` files use `from __future__ import annotations` for deferred evaluation.
- Type hints throughout (`from typing import Optional, List, Dict, ...`).
- Qt stylesheets are module-level constants (e.g. `WIDGET_STYLESHEET` in `ui_widget_qss.py`).
- String formatting uses f-strings; `%APPDATA%` resolved via `os.environ`.
- Games are in `games/` and import `pygame-ce`; they receive session data via CLI arg, not stdin.
