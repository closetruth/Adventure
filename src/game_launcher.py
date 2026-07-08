"""启动 pygame 小游戏子进程并结算奖励。"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from .game_protocol import GameResult, GameSession
from .models import AppState
from .ui_text import format_amount

logger = logging.getLogger(__name__)


ENTRY_GOLD_COST = 10
GRID_GAME_ENTRY_GOLD_COST = 12


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


def game_script_path(game_key: str) -> Path:
    mapping = {
        "pet": "pet_arena.py",
        "grid": "pixel_tactics.py",
    }
    return project_root() / "games" / mapping.get(game_key, "pet_arena.py")


def pygame_available() -> bool:
    try:
        import pygame  # noqa: F401
        return True
    except ImportError:
        return False


def build_game_command(game_key: str, session_in: Path) -> List[str]:
    """构造启动小游戏的命令行（开发态 / 打包态通用）。"""
    session_str = str(session_in.resolve())
    py = python_for_subprocess()
    if getattr(sys, "frozen", False):
        return [py, "--game", game_key, session_str]

    root = project_root()
    run_py = root / "run.py"
    if run_py.exists():
        return [py, str(run_py), "--game", game_key, session_str]

    script = game_script_path(game_key)
    if script.exists():
        return [py, str(script), session_str]

    module = "games.pet_arena" if game_key == "pet" else "games.pixel_tactics"
    return [py, "-m", module, session_str]


def can_start_game(state: AppState, game_key: str) -> Tuple[bool, str]:
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
    need = ENTRY_GOLD_COST if game_key == "pet" else GRID_GAME_ENTRY_GOLD_COST
    if state.inventory.gold < need:
        return (
            False,
            f"至少需要 {need} 金币才能进入游戏。\n"
            f"当前背包金币：{state.inventory.gold}",
        )
    if not getattr(sys, "frozen", False):
        root = project_root()
        if not game_script_path(game_key).exists() and not (root / "run.py").exists():
            return False, f"找不到小游戏文件 {game_script_path(game_key).name}"
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


def _launch_game(state: AppState, game_key: str) -> Tuple[bool, str, Optional[GameResult]]:
    ok, msg = can_start_game(state, game_key)
    if not ok:
        return False, msg, None

    # 扣除入场费
    need = ENTRY_GOLD_COST if game_key == "pet" else GRID_GAME_ENTRY_GOLD_COST
    before_gold = state.inventory.gold
    state.inventory.gold = max(0, state.inventory.gold - need)
    logger.info("游戏启动(%s): 扣除入场费 %d gold (%.1f→%.1f)",
                game_key, need, before_gold, state.inventory.gold)

    session = GameSession.create(
        gold=state.inventory.gold,
        diamond=state.inventory.diamond,
    )
    in_path = session.write()
    result_path = session.result_path()
    if result_path.exists():
        result_path.unlink()

    cmd = build_game_command(game_key, in_path)
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
        logger.error("游戏(%s) 启动失败 (rc=%d): %s", game_key, proc.returncode, detail[:200])
        return False, f"游戏未能正常启动。\n{detail}\n\n命令：{' '.join(cmd)}", None

    result = GameResult.read(result_path)
    if result is None:
        detail = _format_proc_error(proc) if proc.returncode != 0 else ""
        extra = f"\n{detail}" if detail else ""
        logger.warning("游戏(%s) 未能读取结算文件", game_key)
        return False, f"未读取到游戏结算文件。{extra}", None

    if result.session_id and result.session_id != session.session_id:
        return False, "结算会话不匹配，已忽略。", None

    state.inventory.gold = max(0, state.inventory.gold + result.gold_delta)
    state.inventory.diamond = max(0, state.inventory.diamond + result.diamond_delta)
    logger.info("游戏(%s) 结算: gold_delta=%+.1f diamond_delta=%+.1f waves=%d",
                game_key, result.gold_delta, result.diamond_delta, result.waves_cleared)
    state.settings["pet_best_round"] = max(
        int(state.settings.get("pet_best_round", 0)),
        int(result.waves_cleared),
    )

    tip = result.message or "游戏结束"
    if result.gold_delta or result.diamond_delta:
        parts = []
        if result.gold_delta:
            sign = "+" if result.gold_delta > 0 else ""
            parts.append(f"金币 {sign}{format_amount(result.gold_delta)}")
        if result.diamond_delta:
            sign = "+" if result.diamond_delta > 0 else ""
            parts.append(f"钻石 {sign}{format_amount(result.diamond_delta)}")
        tip = f"{tip}\n（{', '.join(parts)}）"

    return True, tip, result


def launch_pet_arena(state: AppState) -> Tuple[bool, str, Optional[GameResult]]:
    """启动 AutoPet 竞技场。"""
    return _launch_game(state, "pet")


def launch_pixel_tactics(state: AppState) -> Tuple[bool, str, Optional[GameResult]]:
    """启动像素格子战场（类金铲铲）。"""
    return _launch_game(state, "grid")
