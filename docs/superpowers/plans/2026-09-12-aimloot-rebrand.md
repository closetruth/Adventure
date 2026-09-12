# AimLoot Rebrand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the product from Adventure to AimLoot (ZH subtitle 目标奖励管理工具), migrate `%APPDATA%\Adventure` → `%APPDATA%\AimLoot`, and update UI, registry, build, and docs.

**Architecture:** Add `src/branding.py` for display constants. Extend `src/storage.py` with legacy path helpers and copy-based migration that returns which directory to use (new on success / already migrated; old on failure with a warning string). Wire UI/main/games/sfx/win_utils/docs/build to AimLoot.

**Tech Stack:** Python 3.12+, stdlib `unittest`, `shutil.copytree`, PySide6, PyInstaller spec, Windows registry via `winreg`.

## Global Constraints

- English product name: `AimLoot` (exact spelling/casing).
- Chinese subtitle: `目标奖励管理工具`.
- Tray tooltip: `AimLoot - 目标奖励管理工具`.
- New data dir: Windows `%APPDATA%\AimLoot`; else `~/.aimloot`.
- Legacy data dir: Windows `%APPDATA%\Adventure`; else `~/.adventure`.
- Migration: **copy** only; never delete legacy directory.
- On migration failure: use legacy dir this session + warning string for UI; do not treat incomplete new dir as valid.
- GitHub remote rename is out of band; docs may already say `closetruth/AimLoot`.
- Do not commit unless the user asks (workspace user rule).

---

## File map

| File | Role |
|------|------|
| `src/branding.py` | `APP_NAME`, `APP_NAME_ZH`, `TRAY_TOOLTIP`, helpers |
| `src/storage.py` | New/legacy paths, `resolve_data_dir()`, migration warning |
| `tests/test_branding.py` | Constant smoke tests |
| `tests/test_data_dir_migration.py` | Three migration branches + failure rollback |
| `src/sfx.py` | Use `get_data_dir()` for `sfx_cache` |
| `src/win_utils.py` | Run key `AimLoot`; clear legacy `Adventure` |
| `src/main.py`, `widget.py`, `task_dialog.py`, `inventory_dialog.py`, `__init__.py` | UI strings |
| `games/*.py`, `games/__init__.py` | Captions / package docstring |
| `Adventure.spec` → `AimLoot.spec` | PyInstaller name |
| `*.bat`, `README.md`, `RELEASE_NOTES.md`, `docs/*`, `CLAUDE.md`, `AGENTS.md` | Docs/scripts |
| `src/task_manager.py` | Drop hard-coded Adventure debug paths if present |

---

### Task 1: Branding constants

**Files:**
- Create: `src/branding.py`
- Create: `tests/test_branding.py`

**Interfaces:**
- Produces: `APP_NAME: str`, `APP_NAME_ZH: str`, `TRAY_TOOLTIP: str`, `def window_title(suffix: str = "") -> str`

- [ ] **Step 1: Write failing test**

```python
# tests/test_branding.py
from __future__ import annotations
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.branding import APP_NAME, APP_NAME_ZH, TRAY_TOOLTIP, window_title

class BrandingTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(APP_NAME, "AimLoot")
        self.assertEqual(APP_NAME_ZH, "目标奖励管理工具")
        self.assertEqual(TRAY_TOOLTIP, "AimLoot - 目标奖励管理工具")

    def test_window_title(self):
        self.assertEqual(window_title(), "AimLoot")
        self.assertEqual(window_title("目标管理"), "目标管理 - AimLoot")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test — expect fail (no module)**

Run: `.venv\Scripts\python.exe -m unittest tests.test_branding -v`  
Expected: `ModuleNotFoundError` or import error for `src.branding`.

- [ ] **Step 3: Implement**

```python
# src/branding.py
from __future__ import annotations

APP_NAME = "AimLoot"
APP_NAME_ZH = "目标奖励管理工具"
TRAY_TOOLTIP = f"{APP_NAME} - {APP_NAME_ZH}"

def window_title(suffix: str = "") -> str:
    s = (suffix or "").strip()
    return f"{s} - {APP_NAME}" if s else APP_NAME
```

- [ ] **Step 4: Run test — expect PASS**

Run: `.venv\Scripts\python.exe -m unittest tests.test_branding -v`

- [ ] **Step 5: Commit only if user requested** (skip by default)

---

### Task 2: Data-dir migration (TDD)

**Files:**
- Modify: `src/storage.py` (`get_data_dir`, add helpers)
- Create: `tests/test_data_dir_migration.py`

**Interfaces:**
- Produces:
  - `default_data_dir() -> Path` — AimLoot path (mkdir)
  - `legacy_data_dir() -> Path` — Adventure path (no mkdir required)
  - `has_valid_save(data_dir: Path) -> bool` — `data.json` exists, non-empty, parses as object (or at least starts with `{` after strip)
  - `migrate_legacy_data_dir(new_dir: Path, old_dir: Path) -> tuple[Path, str | None]` — returns `(dir_to_use, warning_or_None)`
  - `get_data_dir() -> Path` — calls resolve/migrate once per process (module cache OK)
  - `take_migration_warning() -> str | None` — optional mirror of `take_load_warning` if warning stored at module level

**Behavior for `migrate_legacy_data_dir`:**
1. If `has_valid_save(new_dir)` → `(new_dir, None)`
2. Elif not `old_dir.exists()` or old has no files worth copying and no valid save → ensure `new_dir` exists, `(new_dir, None)`
3. Elif old has data (valid save OR any files) and new lacks valid save:
   - Copy tree into a temp staging under parent or into `new_dir` carefully:
     - Prefer: if `new_dir` empty/missing, `shutil.copytree(old_dir, new_dir, dirs_exist_ok=False)` after ensuring parent exists.
     - If copy raises or `not has_valid_save(new_dir)` after copy when old had valid save: remove incomplete `new_dir` if we created it (or clear incomplete contents), return `(old_dir, warning_zh)`.
   - Success → `(new_dir, None)`; leave `old_dir` intact.
4. Never delete `old_dir`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_data_dir_migration.py — key cases:
# 1) new has data.json with "{}" → use new, no copy
# 2) new empty, old has data.json + runtime_intervals.json → copy, both exist, get_data_dir==new
# 3) neither has save → new created empty-ish, path is new
# 4) simulate copy failure (mock shutil.copytree raise) → returns old + warning
```

Patch `os.name` / env `APPDATA` via temp dirs by calling `migrate_legacy_data_dir` directly (do not rely on real APPDATA).

- [ ] **Step 2: Run tests — expect FAIL**

Run: `.venv\Scripts\python.exe -m unittest tests.test_data_dir_migration -v`

- [ ] **Step 3: Implement in `storage.py`**

Update docstring for Windows/non-Windows paths. Keep existing `get_data_file()` using `get_data_dir()`.

Module-level `_migration_warning: str | None = None` and `take_migration_warning()`.

`get_data_dir()`:
```python
_resolved_data_dir: Path | None = None

def get_data_dir() -> Path:
    global _resolved_data_dir, _migration_warning
    if _resolved_data_dir is not None:
        return _resolved_data_dir
    new_dir = default_data_dir_path()  # without mkdir side effects beyond parent
    old_dir = legacy_data_dir_path()
    used, warn = migrate_legacy_data_dir(new_dir, old_dir)
    _migration_warning = warn
    used.mkdir(parents=True, exist_ok=True)
    _resolved_data_dir = used
    return used
```

For tests that patch `get_data_dir`, existing tests keep working. Migration tests call `migrate_legacy_data_dir` directly and may reset `_resolved_data_dir` via a test helper `reset_data_dir_cache()` exported for tests.

- [ ] **Step 4: Run migration + storage tests — PASS**

Run: `.venv\Scripts\python.exe -m unittest tests.test_data_dir_migration tests.test_storage -v`

- [ ] **Step 5: Commit only if user requested**

---

### Task 3: Wire main / sfx / startup registry

**Files:**
- Modify: `src/main.py` — `APP_NAME`, tray, messages; show `take_migration_warning()` like load warning
- Modify: `src/sfx.py` — `_cache_dir` uses `get_data_dir() / "sfx_cache"`
- Modify: `src/win_utils.py` — Run key AimLoot; on enable/disable also delete legacy `Adventure`

**Interfaces:**
- Consumes: `src.branding.APP_NAME`, `TRAY_TOOLTIP`; `storage.take_migration_warning`

- [ ] **Step 1: Update `win_utils.set_startup`**

```python
from .branding import APP_NAME
LEGACY_STARTUP_NAME = "Adventure"
# enable: SetValueEx AimLoot; try DeleteValue Adventure
# disable: DeleteValue AimLoot; try DeleteValue Adventure
```

- [ ] **Step 2: Fix `sfx._cache_dir`**

```python
from .storage import get_data_dir
def _cache_dir() -> Path:
    d = get_data_dir() / "sfx_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

- [ ] **Step 3: Update `main.py` strings** to branding constants; after load, if `take_migration_warning()`: `QMessageBox.warning(..., APP_NAME, warn)`.

- [ ] **Step 4: Smoke unittest** already covering storage; run `tests.test_branding tests.test_data_dir_migration -v`

---

### Task 4: UI + games string sweep

**Files:**
- Modify: `src/widget.py`, `src/task_dialog.py`, `src/inventory_dialog.py`, `src/__init__.py`
- Modify: `games/pet_arena.py`, `games/pixel_tactics.py`, `games/word_arena.py`, `games/__init__.py`
- Modify: `src/task_manager.py` — remove or retarget hard-coded `...\Adventure\debug-*.log` paths to AimLoot / drop dead debug paths

- [ ] **Step 1:** Replace user-visible `Adventure` with `APP_NAME` / `window_title(...)` / `TRAY_TOOLTIP`.
- [ ] **Step 2:** Game captions: `f"{APP_NAME} - ..."`.
- [ ] **Step 3:** Grep for `\bAdventure\b` under `src/` and `games/` — only legacy migration strings / comments about old path may remain in `storage.py`.

---

### Task 5: Build scripts + docs

**Files:**
- Rename: `Adventure.spec` → `AimLoot.spec` (change `name='AimLoot'` in EXE and COLLECT)
- Modify: `build.bat`, `install.bat`, `run.bat`, `fix_game.bat`, `run_game.bat`
- Modify: `README.md`, `RELEASE_NOTES.md`, `docs/README.md`, `docs/probability-design.md`, `docs/engagement-mechanics.md`, `CLAUDE.md`, `AGENTS.md`
- Light touch: `docs/superpowers/specs/2026-09-02-weekly-runtime-intervals-design.md` path line; plan file path line optional
- Leave `probe_frozen.spec` user path alone or only if it says product Adventure

- [ ] **Step 1:** Rename spec + update bat references to `AimLoot.spec` / `dist\AimLoot\AimLoot.exe`
- [ ] **Step 2:** Replace product/repo/zip/path strings in docs
- [ ] **Step 3:** Grep repo for `Adventure` — remaining hits only: legacy path constants, migration tests, this plan/spec history, intentional "旧称 Adventure" notes

---

### Task 6: Full verification

- [ ] **Step 1:** `.venv\Scripts\python.exe -m unittest discover -s tests -v` — all PASS
- [ ] **Step 2:** Confirm `AimLoot.spec` exists and `Adventure.spec` gone
- [ ] **Step 3:** Report summary to user; ask before git commit / GitHub repo rename

---

## Self-review vs spec

| Spec item | Task |
|-----------|------|
| Branding constants + UI | 1, 3, 4 |
| Data migration copy + failure fallback | 2 |
| sfx via get_data_dir | 3 |
| Registry key rename + clear old | 3 |
| Build/docs/GitHub links text | 5 |
| Unittest three branches | 2, 6 |
| Keep old dir | 2 |
| Out-of-band GitHub rename | noted in Task 6 report |
