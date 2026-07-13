"""数据模型 - Task / Reward / AppState。"""
from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


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
class Subtask:
    """目标下的子项：时长达标后完成，点击领取才进背包。"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    target_seconds: float = 600.0
    active_seconds: float = 0.0
    operations: int = 0
    earned_gold: float = 0.0
    earned_diamond: float = 0.0
    pending_rewards: List[Reward] = field(default_factory=list)
    done: bool = False
    rewards_claimed: bool = False
    created_at: Optional[float] = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def pending_summary(self) -> Reward:
        total = Reward()
        for r in self.pending_rewards:
            total.gold += r.gold
            total.diamond += r.diamond
        return total

    def is_claimable(self) -> bool:
        return self.done and not self.rewards_claimed

    def time_target_met(self) -> bool:
        return self.active_seconds >= self.target_seconds

    @classmethod
    def from_dict(cls, data: Dict) -> "Subtask":
        pending = [Reward(**r) for r in data.get("pending_rewards", [])]
        if "target_seconds" in data:
            target_seconds = float(data["target_seconds"])
        elif "target_ops" in data:
            target_seconds = max(60.0, float(data["target_ops"]) * 60.0)
            logger.debug("Subtask.from_dict: 旧版 target_ops 迁移 → target_seconds=%.0f", target_seconds)
        else:
            target_seconds = 600.0
        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            title=data.get("title", ""),
            target_seconds=max(1.0, target_seconds),
            active_seconds=float(data.get("active_seconds", 0)),
            operations=int(data.get("operations", 0)),
            earned_gold=float(data.get("earned_gold", 0)),
            earned_diamond=float(data.get("earned_diamond", 0)),
            pending_rewards=pending,
            done=bool(data.get("done", False)),
            rewards_claimed=bool(data.get("rewards_claimed", False)),
            created_at=data.get("created_at"),
            completed_at=data.get("completed_at"),
        )

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Task:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    note: str = ""
    status: TaskStatus = TaskStatus.ACTIVE
    subtasks: List[Subtask] = field(default_factory=list)
    current_subtask_id: Optional[str] = None

    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    # 任务进行期间累计的操作数 (仅 active 时累加)
    operations: int = 0
    earned_gold: float = 0.0
    earned_diamond: float = 0.0

    # 仅「进行中」状态的累计时长（秒）；悬浮窗定时器每 1s 触发时 +1
    active_seconds: float = 0.0

    # 待领取奖励：完成任务后会进入用户背包
    pending_rewards: List[Reward] = field(default_factory=list)

    # 完成任务时领取的奖励合计（写入背包后保留记录）
    completed_reward_gold: float = 0.0
    completed_reward_diamond: float = 0.0

    def active_duration_seconds(self) -> float:
        """进行中累计秒数（暂停与休眠不计）。"""
        return self.active_seconds

    def pending_summary(self) -> Reward:
        total = Reward()
        for r in self.pending_rewards:
            total.gold += r.gold
            total.diamond += r.diamond
        return total

    def subtask_progress(self) -> tuple[int, int]:
        """返回 (已完成数, 总数)。"""
        total = len(self.subtasks)
        done = sum(1 for s in self.subtasks if s.done)
        return done, total

    def earned_totals(self) -> tuple[float, float]:
        """展示用累计奖励：有子目标时为各子目标之和，否则用父目标字段。"""
        if self.subtasks:
            gold = sum(s.earned_gold for s in self.subtasks)
            diamond = sum(s.earned_diamond for s in self.subtasks)
            return gold, diamond
        return self.earned_gold, self.earned_diamond

    def sync_earned_from_subtasks(self) -> None:
        """将父目标 earned_* 与子目标合计对齐（有子目标时）。"""
        if not self.subtasks:
            return
        gold, diamond = self.earned_totals()
        self.earned_gold = gold
        self.earned_diamond = diamond

    def current_subtask(self) -> Optional[Subtask]:
        """当前聚焦的子目标（仅 current_subtask_id 指向的未完成项）。"""
        if not self.current_subtask_id:
            return None
        for s in self.subtasks:
            if s.id == self.current_subtask_id and not s.done:
                return s
        return None

    def has_unclaimed_subtasks(self) -> bool:
        """子目标仍有 pending 或未领取的完成奖励时，不可完成父目标。"""
        for s in self.subtasks:
            if s.rewards_claimed:
                continue
            if s.is_claimable() or s.pending_rewards:
                return True
        return False

    def current_subtask_pending(self) -> Reward:
        sub = self.current_subtask()
        if sub is None:
            return Reward()
        return sub.pending_summary()

    def can_complete_sub(self, sub: Subtask) -> bool:
        return sub.time_target_met()

    @classmethod
    def from_dict(cls, data: Dict) -> "Task":
        rewards = [Reward(**r) for r in data.get("pending_rewards", [])]
        subtasks = [Subtask.from_dict(s) for s in data.get("subtasks", [])]
        task = cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            title=data.get("title", ""),
            note=data.get("note", ""),
            status=TaskStatus(data.get("status", "active")),
            subtasks=subtasks,
            current_subtask_id=data.get("current_subtask_id"),
            created_at=data.get("created_at", time.time()),
            completed_at=data.get("completed_at"),
            operations=data.get("operations", 0),
            earned_gold=float(data.get("earned_gold", 0)),
            earned_diamond=float(data.get("earned_diamond", 0)),
            active_seconds=float(data.get("active_seconds", 0)),
            pending_rewards=rewards,
            completed_reward_gold=float(data.get("completed_reward_gold", 0)),
            completed_reward_diamond=float(data.get("completed_reward_diamond", 0)),
        )
        return task

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
class RollRuntime:
    """当前开奖周期与有效随机参数（内置机制，每 10 分钟重抽概率/范围）。"""
    next_roll_at: int = 10
    roll_span: int = 10
    segment_colors: List[str] = field(default_factory=list)
    roll_chance: float = 0.35
    diamond_chance: float = 0.08
    gold_min: float = 0.1
    gold_max: float = 1.0
    diamond_min: float = 0.01
    diamond_max: float = 0.1
    last_shuffle_at: float = 0.0

    @classmethod
    def from_dict(cls, data: Dict) -> "RollRuntime":
        return cls(
            next_roll_at=int(data.get("next_roll_at", 10)),
            roll_span=max(1, int(data.get("roll_span", 10))),
            segment_colors=list(data.get("segment_colors", [])),
            roll_chance=float(data.get("roll_chance", 0.35)),
            diamond_chance=float(data.get("diamond_chance", 0.08)),
            gold_min=float(data.get("gold_min", 0.1)),
            gold_max=float(data.get("gold_max", 1.0)),
            diamond_min=float(data.get("diamond_min", 0.01)),
            diamond_max=float(data.get("diamond_max", 0.1)),
            last_shuffle_at=float(data.get("last_shuffle_at", 0.0)),
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
    roll_runtime: RollRuntime = field(default_factory=RollRuntime)
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
        "subtask_default_target_minutes": 10,
        "subtask_completion_bonus_gold": 0.5,
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
            "roll_runtime": self.roll_runtime.to_dict(),
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
            roll_runtime=RollRuntime.from_dict(data.get("roll_runtime", {})),
        )
        s.settings.update(data.get("settings", {}))
        return s


def validate_state_invariants(state: AppState) -> Optional[str]:
    """检查内存状态的业务不变量；返回错误描述，None 表示通过。"""
    if state.total_operations < 0:
        return "total_operations 为负"
    if state.last_roll_at < 0:
        return "last_roll_at 为负"
    if state.last_roll_at > state.total_operations:
        return "last_roll_at 超过 total_operations"

    inv = state.inventory
    for name, val in (("gold", inv.gold), ("diamond", inv.diamond)):
        if not math.isfinite(val) or val < 0:
            return f"inventory.{name} 非法"

    active_count = 0
    task_ids: set[str] = set()
    for t in state.tasks:
        if not t.id:
            return "存在空目标 id"
        if t.id in task_ids:
            return f"目标 id 重复: {t.id}"
        task_ids.add(t.id)

        if t.status == TaskStatus.ACTIVE:
            active_count += 1
        if t.operations < 0:
            return f"目标「{t.title}」operations 为负"
        if not math.isfinite(t.active_seconds) or t.active_seconds < 0:
            return f"目标「{t.title}」active_seconds 非法"

        sub_ids: set[str] = set()
        for s in t.subtasks:
            if not s.id:
                return "存在空子目标 id"
            if s.id in sub_ids:
                return f"子目标 id 重复: {s.id}"
            sub_ids.add(s.id)
            if s.operations < 0:
                return f"子目标「{s.title}」operations 为负"
            if not math.isfinite(s.target_seconds) or s.target_seconds <= 0:
                return f"子目标「{s.title}」target_seconds 非法"
            if not math.isfinite(s.active_seconds) or s.active_seconds < 0:
                return f"子目标「{s.title}」active_seconds 非法"

        if t.current_subtask_id is not None:
            sub = next((s for s in t.subtasks if s.id == t.current_subtask_id), None)
            if sub is None:
                return f"目标「{t.title}」current_subtask_id 指向不存在的子目标"
            if sub.done:
                return f"目标「{t.title}」current_subtask_id 指向已完成的子目标"

    if active_count > 1:
        return f"存在 {active_count} 个进行中目标（最多 1 个）"

    sr = state.since_roll
    if not math.isfinite(sr.gold) or sr.gold < 0:
        return "since_roll.gold 非法"
    if not math.isfinite(sr.diamond) or sr.diamond < 0:
        return "since_roll.diamond 非法"

    rt = state.roll_runtime
    if rt.roll_span < 1:
        return "roll_runtime.roll_span 非法"
    if rt.next_roll_at < state.last_roll_at:
        return "roll_runtime.next_roll_at 早于 last_roll_at"
    for name, val in (
        ("roll_chance", rt.roll_chance),
        ("diamond_chance", rt.diamond_chance),
        ("gold_min", rt.gold_min),
        ("gold_max", rt.gold_max),
        ("diamond_min", rt.diamond_min),
        ("diamond_max", rt.diamond_max),
    ):
        if not math.isfinite(val) or val < 0:
            return f"roll_runtime.{name} 非法"

    return None
