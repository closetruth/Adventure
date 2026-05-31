"""数据模型 - Task / Reward / AppState。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional


class TaskStatus(str, Enum):
    ACTIVE = "active"        # 进行中
    PAUSED = "paused"        # 已暂停
    COMPLETED = "completed"  # 已完成


@dataclass
class Reward:
    """单次奖励掉落记录。"""
    gold: float = 0.0
    diamond: float = 0.0
    # 触发时所属的操作计数，便于排序回顾
    op_at: int = 0

    def is_empty(self) -> bool:
        return self.gold == 0 and self.diamond == 0


@dataclass
class Task:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    note: str = ""
    status: TaskStatus = TaskStatus.ACTIVE

    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    # 任务进行期间累计的操作数 (仅 active 时累加)
    operations: int = 0

    # 待领取奖励：完成任务后会进入用户背包
    pending_rewards: List[Reward] = field(default_factory=list)

    def pending_summary(self) -> Reward:
        total = Reward()
        for r in self.pending_rewards:
            total.gold += r.gold
            total.diamond += r.diamond
        return total

    @classmethod
    def from_dict(cls, data: Dict) -> "Task":
        rewards = [Reward(**r) for r in data.get("pending_rewards", [])]
        return cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            title=data.get("title", ""),
            note=data.get("note", ""),
            status=TaskStatus(data.get("status", "active")),
            created_at=data.get("created_at", time.time()),
            completed_at=data.get("completed_at"),
            operations=data.get("operations", 0),
            pending_rewards=rewards,
        )

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class Inventory:
    """玩家全局背包。"""
    gold: float = 0.0
    diamond: float = 0.00

    def add(self, reward: Reward) -> None:
        self.gold += reward.gold
        self.diamond += reward.diamond


@dataclass
class RollAccum:
    """自上次开奖检查点以来累计掉落到当前任务的奖励。"""
    gold: float = 0.0
    diamond: float = 0.0

    def is_empty(self) -> bool:
        return self.gold == 0.0 and self.diamond == 0.0


@dataclass
class RollHistoryEntry:
    """单次开奖结果（命中或未中）。"""
    op_at: int = 0
    at: float = field(default_factory=time.time)
    hit: bool = False
    gold: float = 0.0
    diamond: float = 0.0
    task_title: str = ""

    @classmethod
    def from_dict(cls, data: Dict) -> "RollHistoryEntry":
        return cls(
            op_at=int(data.get("op_at", 0)),
            at=float(data.get("at", time.time())),
            hit=bool(data.get("hit", False)),
            gold=float(data.get("gold", 0)),
            diamond=float(data.get("diamond", 0)),
            task_title=str(data.get("task_title", "")),
        )

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class AppState:
    """整体应用状态 (持久化对象)。"""
    inventory: Inventory = field(default_factory=Inventory)
    tasks: List[Task] = field(default_factory=list)
    total_operations: int = 0           # 全局历史操作数
    last_roll_at: int = 0               # 上一次开奖时所属的操作总数
    since_roll: RollAccum = field(default_factory=RollAccum)
    roll_history: List[RollHistoryEntry] = field(default_factory=list)
    settings: Dict = field(default_factory=lambda: {
        "pin_all_desktops": True,
        "always_on_top": True,
        "roll_interval": 10,           # 每多少次操作触发一次开奖
        "roll_chance": 0.35,           # 命中奖励的概率
        "gold_min": 0.1,
        "gold_max": 1.0,
        "diamond_chance": 0.08,        # 在命中奖励的前提下，钻石替代金币的概率
        "diamond_min": 0.01,
        "diamond_max": 0.1,
        "pet_best_round": 0,
    })

    def active_task(self) -> Optional[Task]:
        """当前唯一进行中的任务 (若有)。"""
        for t in self.tasks:
            if t.status == TaskStatus.ACTIVE:
                return t
        return None

    def to_dict(self) -> Dict:
        return {
            "inventory": asdict(self.inventory),
            "tasks": [t.to_dict() for t in self.tasks],
            "total_operations": self.total_operations,
            "last_roll_at": self.last_roll_at,
            "since_roll": asdict(self.since_roll),
            "roll_history": [e.to_dict() for e in self.roll_history],
            "settings": self.settings,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "AppState":
        inv = Inventory(**data.get("inventory", {}))
        tasks = [Task.from_dict(t) for t in data.get("tasks", [])]
        sr = data.get("since_roll", {})
        history = [RollHistoryEntry.from_dict(x) for x in data.get("roll_history", [])]
        s = cls(
            inventory=inv,
            tasks=tasks,
            total_operations=data.get("total_operations", 0),
            last_roll_at=data.get("last_roll_at", 0),
            since_roll=RollAccum(
                gold=float(sr.get("gold", 0)),
                diamond=float(sr.get("diamond", 0)),
            ),
            roll_history=history,
        )
        s.settings.update(data.get("settings", {}))
        return s
