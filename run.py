"""开发模式入口：``python run.py``。

小游戏子进程：
  python run.py --game pet <session_in.json>
  python run.py --game grid <session_in.json>

兼容旧参数：
  python run.py --game <session_in.json>  # 默认 pet
"""
from __future__ import annotations

import sys


def _run_game_cli() -> int:
    if len(sys.argv) < 3:
        print("用法: run.py --game <pet|grid> <session_in.json>")
        return 2

    # 兼容旧调用：--game <session>
    if len(sys.argv) == 3:
        game_name = "pet"
        session_path = sys.argv[2]
    else:
        game_name = sys.argv[2]
        session_path = sys.argv[3]

    if game_name == "pet":
        from games.pet_arena import run_session
        return run_session(session_path)
    if game_name == "grid":
        from games.pixel_tactics import run_session
        return run_session(session_path)

    print(f"未知游戏类型: {game_name}")
    return 2


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--game":
        raise SystemExit(_run_game_cli())
    from src.main import main

    raise SystemExit(main())
