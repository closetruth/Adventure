"""启动 pygame 小游戏子进程并结算奖励。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from .game_protocol import GameResult, GameSession
from .models import AppState


ENTRY_GOLD_COST = 10


def project_root() -> Path:
    """项目根目录；打包后为 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def python_for_subprocess() -> str:
    """子进程用 python.exe（不用 pythonw），否则 pygame 可能无法启动。"""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        py = exe.with_name("python.exe")
        if py.exists():
            return str(py)
    return str(exe)


def game_script_path() -> Path:
    return project_root() / "games" / "pet_arena.py"


def pygame_available() -> bool:
    try:
        import pygame  # noqa: F401
        return True
    except ImportError:
        return False


def build_game_command(session_in: Path) -> List[str]:
    """构造启动小游戏的命令行（开发态 / 打包态通用）。"""
    session_str = str(session_in.resolve())
    py = python_for_subprocess()
    if getattr(sys, "frozen", False):
        return [py, "--game", session_str]

    root = project_root()
    run_py = root / "run.py"
    if run_py.exists():
        return [py, str(run_py), "--game", session_str]

    script = game_script_path()
    if script.exists():
        return [py, str(script), session_str]

    return [py, "-m", "games.pet_arena", session_str]


def can_start_game(state: AppState) -> Tuple[bool, str]:
    if not pygame_available():
        return (
            False,
            "未安装 pygame。\n"
            "Python 3.14 请安装 pygame-ce（不要用 pygame）：\n"
            "  双击 fix_game.bat\n"
            "或执行：\n"
            "  .venv\\Scripts\\python.exe -m pip install pygame-ce\n"
            "推荐用 Python 3.12 重建环境：install.bat",
        )
    if state.inventory.gold < ENTRY_GOLD_COST:
        return (
            False,
            f"至少需要 {ENTRY_GOLD_COST} 金币才能进入竞技场。\n"
            f"当前背包金币：{state.inventory.gold}",
        )
    if not getattr(sys, "frozen", False):
        root = project_root()
        if not (root / "games" / "pet_arena.py").exists() and not (root / "run.py").exists():
            return False, "找不到小游戏文件 games/pet_arena.py"
    return True, ""


def _format_proc_error(proc: subprocess.CompletedProcess[str]) -> str:
    chunks = []
    if proc.stderr and proc.stderr.strip():
        chunks.append(proc.stderr.strip())
    if proc.stdout and proc.stdout.strip():
        chunks.append(proc.stdout.strip())
    if chunks:
        return "\n".join(chunks)[:800]
    return f"退出码 {proc.returncode}"


def launch_pet_arena(state: AppState) -> Tuple[bool, str, Optional[GameResult]]:
    """启动小游戏，成功返回 (True, 提示, GameResult)。"""
    ok, msg = can_start_game(state)
    if not ok:
        return False, msg, None

    session = GameSession.create(
        gold=state.inventory.gold,
        diamond=state.inventory.diamond,
    )
    in_path = session.write()
    result_path = session.result_path()
    if result_path.exists():
        result_path.unlink()

    cmd = build_game_command(in_path)
    cwd = str(project_root())
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as e:
        return False, f"启动失败：{e}\n命令：{' '.join(cmd)}", None

    if proc.returncode != 0 and not result_path.exists():
        detail = _format_proc_error(proc)
        return False, f"游戏未能正常启动。\n{detail}\n\n命令：{' '.join(cmd)}", None

    result = GameResult.read(result_path)
    if result is None:
        detail = _format_proc_error(proc) if proc.returncode != 0 else ""
        extra = f"\n{detail}" if detail else ""
        return False, f"未读取到游戏结算文件。{extra}", None

    if result.session_id and result.session_id != session.session_id:
        return False, "结算会话不匹配，已忽略。", None

    state.inventory.gold = max(0, state.inventory.gold + result.gold_delta)
    state.inventory.diamond = max(0, state.inventory.diamond + result.diamond_delta)

    tip = result.message or "游戏结束"
    if result.gold_delta or result.diamond_delta:
        parts = []
        if result.gold_delta:
            sign = "+" if result.gold_delta > 0 else ""
            parts.append(f"金币 {sign}{result.gold_delta}")
        if result.diamond_delta:
            sign = "+" if result.diamond_delta > 0 else ""
            parts.append(f"钻石 {sign}{result.diamond_delta}")
        tip = f"{tip}\n（{', '.join(parts)}）"

    return True, tip, result
