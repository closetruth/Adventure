"""主程序与小游戏之间的 JSON 会话/结果协议。"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .storage import get_data_dir


def _sessions_dir() -> Path:
    d = get_data_dir() / "game_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class GameSession:
    session_id: str
    gold: float
    diamond: float
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.time()

    @classmethod
    def create(cls, gold: float, diamond: float) -> "GameSession":
        return cls(session_id=uuid.uuid4().hex[:16], gold=gold, diamond=diamond)

    def session_path(self) -> Path:
        return _sessions_dir() / f"{self.session_id}_in.json"

    def result_path(self) -> Path:
        return _sessions_dir() / f"{self.session_id}_out.json"

    def write(self) -> Path:
        path = self.session_path()
        with path.open("w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def read(cls, path: Path) -> "GameSession":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            session_id=data["session_id"],
            gold=float(data["gold"]),
            diamond=float(data["diamond"]),
            created_at=float(data.get("created_at", 0)),
        )


@dataclass
class GameResult:
    session_id: str
    gold_delta: float = 0.0
    diamond_delta: float = 0.0
    waves_cleared: int = 0
    message: str = ""

    @classmethod
    def read(cls, path: Path) -> Optional["GameResult"]:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(
                session_id=data.get("session_id", ""),
                gold_delta=float(data.get("gold_delta", 0)),
                diamond_delta=float(data.get("diamond_delta", 0)),
                waves_cleared=int(data.get("waves_cleared", 0)),
                message=str(data.get("message", "")),
            )
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            return None

    def write(self, path: Path) -> None:
        with path.open("w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
