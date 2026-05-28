"""开发模式入口：``python run.py``。

小游戏子进程：``python run.py --game <session_in.json>``
打包后的 exe：``Adventure.exe --game <session_in.json>``
"""
from __future__ import annotations

import sys


def _run_game_cli() -> int:
    if len(sys.argv) < 3:
        print("用法: run.py --game <session_in.json>")
        return 2
    from games.pet_arena import run_session

    return run_session(sys.argv[2])


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--game":
        raise SystemExit(_run_game_cli())
    from src.main import main

    raise SystemExit(main())
