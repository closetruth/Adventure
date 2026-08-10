"""任务 CRUD 与状态变更逻辑。"""
from __future__ import annotations

import logging
import time
from typing import Iterator, List, Optional, Set, Tuple

from .active_time import ActiveTimeTracker
from .migrate_accounting import detach_subtask_progress_to_legacy, detach_task_progress_to_legacy
from .models import AppState, Reward, Subtask, Task, TaskStatus
from .power_monitor import PowerMonitor

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(
        self,
        state: AppState,
        power_monitor: Optional[PowerMonitor] = None,
    ):
        self.state = state
        self.power_monitor = power_monitor or PowerMonitor()
        self._active_time = ActiveTimeTracker()
        self._subtask_expanded: dict[str, Set[str]] = {}
        for t in state.tasks:
            if t.subtasks:
                t.sync_earned_from_subtasks()
            if t.status == TaskStatus.ACTIVE:
                self._sync_current_subtask(t)
                self.expand_all_subtasks(t)
                self.sync_subtask_expand_to_focus(t)

    # ----- 查询 -----
    def all(self) -> List[Task]:
        return list(self.state.tasks)

    def by_status(self, status: TaskStatus) -> List[Task]:
        return [t for t in self.state.tasks if t.status == status]

    def get(self, task_id: str) -> Optional[Task]:
        for t in self.state.tasks:
            if t.id == task_id:
                return t
        return None

    def _get_subtask(self, task: Task, subtask_id: str) -> Optional[Subtask]:
        return task.find_subtask(subtask_id)

    def _sync_current_subtask(self, task: Task) -> None:
        for leaf in task.iter_leaves():
            if not leaf.done:
                task.current_subtask_id = leaf.id
                self.sync_subtask_expand_to_focus(task)
                return
        task.current_subtask_id = None
        self.sync_subtask_expand_to_focus(task)

    # ----- 子目标展开（UI 状态，不持久化） -----
    def subtask_container_ancestor_ids(
        self,
        task: Task,
        subtask_id: str,
    ) -> Set[str]:
        """路径上所有分组祖先的 id（不含叶子自身）。"""
        path_ids = task.subtask_path_ids(subtask_id)
        ancestors: Set[str] = set()
        for sid in path_ids[:-1]:
            sub = task.find_subtask(sid)
            if sub is not None and sub.is_container():
                ancestors.add(sid)
        return ancestors

    def expanded_subtask_ids(self, task_id: str) -> Set[str]:
        return set(self._subtask_expanded.get(task_id, set()))

    def is_subtask_expanded(self, task_id: str, subtask_id: str) -> bool:
        return subtask_id in self._subtask_expanded.get(task_id, set())

    def sync_subtask_expand_to_focus(self, task: Task) -> None:
        """确保聚焦路径上的分组已展开（不折叠其它已展开分组）。"""
        if not task.current_subtask_id:
            return
        expanded = self._subtask_expanded.setdefault(task.id, set())
        expanded |= self.subtask_container_ancestor_ids(
            task,
            task.current_subtask_id,
        )

    def expand_all_subtasks(self, task: Task) -> None:
        """展开树上所有分组（默认全树可见）。"""
        expanded: Set[str] = set()
        for sub in task.iter_subtasks():
            if sub.is_container():
                expanded.add(sub.id)
        self._subtask_expanded[task.id] = expanded

    def toggle_subtask_expand(self, task_id: str, subtask_id: str) -> bool:
        t = self.get(task_id)
        if t is None:
            return False
        sub = self._get_subtask(t, subtask_id)
        if sub is None or not sub.is_container():
            return False
        expanded = self._subtask_expanded.setdefault(task_id, set())
        if subtask_id in expanded:
            expanded.discard(subtask_id)
        else:
            expanded.add(subtask_id)
        return True

    def iter_visible_subtasks(self, task: Task) -> Iterator[Tuple[int, Subtask]]:
        expanded = self.expanded_subtask_ids(task.id)

        def walk(nodes: List[Subtask], depth: int) -> Iterator[Tuple[int, Subtask]]:
            for node in nodes:
                yield depth, node
                if node.is_container() and node.id in expanded:
                    yield from walk(node.children, depth + 1)

        yield from walk(task.subtasks, 0)

    def _prune_subtask_expanded(self, task: Task, subtask_id: str) -> None:
        expanded = self._subtask_expanded.get(task.id)
        if not expanded:
            return
        sub = self._get_subtask(task, subtask_id)
        if sub is None:
            return
        remove_ids = {node.id for node in sub.iter_subtree()}
        expanded -= remove_ids

    def _remove_subtask(self, task: Task, subtask_id: str) -> bool:
        for index, sub in enumerate(task.subtasks):
            if sub.id == subtask_id:
                task.subtasks.pop(index)
                return True
            if self._remove_subtask_from_node(sub, subtask_id):
                return True
        return False

    @staticmethod
    def _remove_subtask_from_node(parent: Subtask, subtask_id: str) -> bool:
        for index, child in enumerate(parent.children):
            if child.id == subtask_id:
                parent.children.pop(index)
                return True
            if TaskManager._remove_subtask_from_node(child, subtask_id):
                return True
        return False

    def _completion_bonus(self) -> float:
        return float(self.state.settings.get("subtask_completion_bonus_gold", 0.5))

    def _settle_subtask_rewards(
        self,
        task: Task,
        *,
        only_claimable: bool = False,
    ) -> bool:
        """将子目标 pending 结算进背包（完成固定奖仅 done 时加）。

        only_claimable=True 时，只结算已完成且未领取的子目标，
        避免把进行中子目标的 pending 提前静默进背包。
        """
        bonus = self._completion_bonus()
        changed = False
        for sub in task.iter_subtasks():
            if sub.rewards_claimed or not sub.pending_rewards:
                continue
            if only_claimable and not sub.is_claimable() and not sub.can_claim_pending():
                continue
            total = sub.pending_summary()
            if sub.done and sub.is_leaf():
                total.gold += bonus
            self.state.inventory.add(total)
            sub.pending_rewards.clear()
            if sub.is_leaf():
                sub.rewards_claimed = True
            changed = True
        return changed

    def recover_stuck_subtask_rewards(self) -> bool:
        """启动时修复：只结算「已完成但未领取」的子目标，或已完成父目标上的残留 pending。"""
        changed = False
        for t in self.state.tasks:
            if t.status == TaskStatus.COMPLETED:
                if self._settle_subtask_rewards(t, only_claimable=False):
                    logger.info("启动恢复: 结算已完成目标「%s」的残留子任务奖励", t.title)
                    changed = True
                continue
            if self._settle_subtask_rewards(t, only_claimable=True):
                logger.info("启动恢复: 结算目标「%s」的可领取子任务奖励", t.title)
                changed = True
        return changed

    def preview_claim(self, task_id: str, subtask_id: str) -> Optional[Reward]:
        """预览领取总额（pending + 完成固定奖）。"""
        t = self.get(task_id)
        if not t:
            return None
        sub = self._get_subtask(t, subtask_id)
        if not sub or not sub.is_leaf():
            return None
        if not sub.is_claimable():
            return None
        total = sub.pending_summary()
        total.gold += self._completion_bonus()
        return total

    def _mark_subtask_done(self, task: Task, sub: Subtask) -> None:
        if sub.done:
            return
        sub.done = True
        sub.completed_at = time.time()
        if sub.active_seconds < sub.target_seconds:
            sub.active_seconds = sub.target_seconds
        self._sync_current_subtask(task)

    # ----- 变更 -----
    def create(self, title: str, note: str = "") -> Task:
        title = (title or "").strip() or "未命名目标"
        has_active = self.state.active_task() is not None
        status = TaskStatus.PAUSED if has_active else TaskStatus.ACTIVE
        task = Task(title=title, note=note, status=status)
        self.state.tasks.insert(0, task)
        if status == TaskStatus.ACTIVE:
            self._sync_current_subtask(task)
        else:
            self._subtask_expanded[task.id] = set()
        logger.info("创建目标「%s」(id=%s, status=%s)", title, task.id, status.value)
        return task

    def pause(self, task_id: str) -> Optional[Task]:
        t = self.get(task_id)
        if not t or t.status != TaskStatus.ACTIVE:
            return t
        t.status = TaskStatus.PAUSED
        logger.info("暂停目标「%s」(id=%s)", t.title, task_id)
        return t

    def resume(self, task_id: str) -> Optional[Task]:
        t = self.get(task_id)
        if not t or t.status != TaskStatus.PAUSED:
            return t
        current = self.state.active_task()
        if current and current.id != t.id:
            logger.info("自动暂停「%s」(id=%s)", current.title, current.id)
            current.status = TaskStatus.PAUSED
        t.status = TaskStatus.ACTIVE
        self._sync_current_subtask(t)
        self.expand_all_subtasks(t)
        self.sync_subtask_expand_to_focus(t)
        logger.info("恢复目标「%s」(id=%s)", t.title, task_id)
        return t

    def complete(self, task_id: str) -> Optional[Reward]:
        """完成任务并把待领取奖励转入背包，返回本次结算的总奖励。"""
        t = self.get(task_id)
        if not t or t.status == TaskStatus.COMPLETED:
            return None
        if t.has_unclaimed_subtasks():
            return None
        self._settle_subtask_rewards(t)
        total = t.pending_summary()
        self.state.inventory.add(total)
        t.completed_reward_gold, t.completed_reward_diamond = t.earned_totals()
        t.pending_rewards.clear()
        t.status = TaskStatus.COMPLETED
        t.completed_at = time.time()
        t.current_subtask_id = None
        logger.info("完成任务「%s」(id=%s) 结算 gold=%.1f diamond=%.1f",
                    t.title, task_id, total.gold, total.diamond)
        return total

    def can_complete_task(self, task_id: str) -> bool:
        t = self.get(task_id)
        if not t or t.status == TaskStatus.COMPLETED:
            return False
        return not t.has_unclaimed_subtasks()

    def delete(self, task_id: str) -> bool:
        t = self.get(task_id)
        before = len(self.state.tasks)
        self.state.tasks = [t for t in self.state.tasks if t.id != task_id]
        if len(self.state.tasks) != before:
            logger.info("删除目标「%s」(id=%s)", t.title if t else "?", task_id)
            return True
        return False

    # ----- 子任务 -----
    def add_subtask(
        self,
        task_id: str,
        title: str,
        target_minutes: Optional[int] = None,
        parent_subtask_id: Optional[str] = None,
    ) -> Optional[Subtask]:
        t = self.get(task_id)
        if not t or t.status == TaskStatus.COMPLETED:
            return None
        title = (title or "").strip()
        if not title:
            return None
        if target_minutes is None:
            target_minutes = int(self.state.settings.get("subtask_default_target_minutes", 10))
        target_minutes = max(1, int(target_minutes))
        sub = Subtask(title=title, target_seconds=float(target_minutes * 60))
        if parent_subtask_id:
            parent = self._get_subtask(t, parent_subtask_id)
            if parent is None:
                return None
            parent.children.append(sub)
            self._subtask_expanded.setdefault(task_id, set()).add(parent_subtask_id)
            if t.current_subtask_id == parent_subtask_id:
                self._sync_current_subtask(t)
        else:
            if not parent_subtask_id and not t.subtasks:
                legacy = detach_task_progress_to_legacy(t)
                if legacy is not None:
                    t.subtasks.append(legacy)
            t.subtasks.append(sub)
            if t.status == TaskStatus.ACTIVE and t.current_subtask_id is None:
                self._sync_current_subtask(t)
        self.expand_all_subtasks(t)
        logger.info(
            "添加子目标「%s」(task_id=%s, parent=%s, target=%dmin)",
            title,
            task_id,
            parent_subtask_id or "-",
            target_minutes,
        )
        return sub

    def confirm_manual_complete_subtask(self, task_id: str, subtask_id: str) -> bool:
        """手动确认完成：仅 mark done，不领取；须子目标时长达标。"""
        t = self.get(task_id)
        if not t or t.status == TaskStatus.COMPLETED:
            return False
        sub = self._get_subtask(t, subtask_id)
        if not sub or sub.done:
            return False
        if not t.can_complete_sub(sub):
            return False
        self._mark_subtask_done(t, sub)
        logger.info("手动完成子目标「%s」(task_id=%s)", sub.title, task_id)
        return True

    def subtask_time_met(self, task_id: str, subtask_id: str) -> bool:
        t = self.get(task_id)
        if not t:
            return False
        sub = self._get_subtask(t, subtask_id)
        if not sub:
            return False
        return t.can_complete_sub(sub)

    def claim_subtask_reward(self, task_id: str, subtask_id: str) -> Optional[Reward]:
        """领取子任务奖励：pending → 背包；叶子完成奖另加固定金。"""
        t = self.get(task_id)
        if not t:
            return None
        sub = self._get_subtask(t, subtask_id)
        if not sub or not sub.is_leaf():
            return None
        if not sub.is_claimable() and not sub.can_claim_pending():
            return None
        if sub.is_claimable():
            total = sub.pending_summary()
            total.gold += self._completion_bonus()
        else:
            total = sub.pending_summary()
        self.state.inventory.add(total)
        sub.pending_rewards.clear()
        sub.rewards_claimed = True
        logger.info("领取子目标「%s」(task_id=%s) gold=%.1f diamond=%.1f",
                    sub.title, task_id, total.gold, total.diamond)
        return total

    def decompose_subtask(
        self,
        task_id: str,
        subtask_id: str,
        child_titles: List[str],
    ) -> bool:
        """将未完成叶子拆成分组：原进度迁入 legacy 子叶子，用户新叶子从 0 开始。"""
        t = self.get(task_id)
        if not t or t.status != TaskStatus.ACTIVE:
            return False
        sub = self._get_subtask(t, subtask_id)
        if sub is None or sub.done or not sub.is_leaf():
            return False
        titles = [(x or "").strip() for x in child_titles if (x or "").strip()]
        if not titles:
            return False
        target_minutes = int(self.state.settings.get("subtask_default_target_minutes", 10))
        target_seconds = float(max(1, target_minutes) * 60)
        was_focused = t.current_subtask_id == subtask_id

        legacy = detach_subtask_progress_to_legacy(sub)
        new_children: List[Subtask] = []
        for title in titles:
            new_children.append(Subtask(title=title, target_seconds=target_seconds))
        sub.children = ([legacy] if legacy is not None else []) + new_children

        first_user_child = new_children[0] if new_children else None
        if was_focused and first_user_child is not None:
            t.current_subtask_id = first_user_child.id
        self.expand_all_subtasks(t)
        self.sync_subtask_expand_to_focus(t)
        logger.info(
            "分解子目标「%s」→ %s + %d 个新子项 (task_id=%s)",
            sub.title,
            "legacy" if legacy is not None else "无 legacy",
            len(titles),
            task_id,
        )
        return True

    def focus_subtask(self, task_id: str, subtask_id: str) -> bool:
        """将叶子子目标设为 current（开始累计 ops/时长/奖励）。"""
        t = self.get(task_id)
        if not t or t.status != TaskStatus.ACTIVE:
            return False
        sub = self._get_subtask(t, subtask_id)
        if not sub or sub.done or not sub.is_leaf():
            return False
        t.current_subtask_id = subtask_id
        self.sync_subtask_expand_to_focus(t)
        logger.debug("聚焦子目标「%s」(task_id=%s)", sub.title, task_id)
        return True

    def pause_subtask_focus(self, task_id: str) -> bool:
        """取消子目标聚焦（暂停子目标累计）。"""
        t = self.get(task_id)
        if not t or t.status != TaskStatus.ACTIVE:
            return False
        if t.current_subtask_id is None:
            return False
        logger.debug("暂停子目标聚焦 (task_id=%s)", task_id)
        t.current_subtask_id = None
        self.sync_subtask_expand_to_focus(t)
        return True

    def complete_and_claim_subtask(
        self, task_id: str, subtask_id: str,
    ) -> Optional[Reward]:
        """已可领则直接领；时长达标则 mark done 后立即领取。"""
        t = self.get(task_id)
        if not t:
            return None
        sub = self._get_subtask(t, subtask_id)
        if not sub:
            return None
        if sub.is_claimable() or sub.can_claim_pending():
            return self.claim_subtask_reward(task_id, subtask_id)
        if not sub.done and t.can_complete_sub(sub):
            self._mark_subtask_done(t, sub)
            return self.claim_subtask_reward(task_id, subtask_id)
        return None

    def delete_subtask(self, task_id: str, subtask_id: str) -> bool:
        t = self.get(task_id)
        if not t or t.status == TaskStatus.COMPLETED:
            return False
        sub = self._get_subtask(t, subtask_id)
        if sub is None:
            return False
        if not self._remove_subtask(t, subtask_id):
            return False
        self._prune_subtask_expanded(t, subtask_id)
        logger.info("删除子目标「%s」(task_id=%s)", sub.title, task_id)
        self._sync_current_subtask(t)
        self._sync_task_earned_from_subtasks(t)
        return True

    def tick_active_time(self) -> bool:
        """每秒调用：累加聚焦叶子或扁平目标时长（关屏不计）。"""
        seconds = self._active_time.tick(
            counting_enabled=self.power_monitor.should_count_time(),
        )
        active = self.state.active_task()
        if active is None or seconds <= 0:
            return False
        if active.subtasks:
            sub = active.current_subtask()
            if sub is not None:
                sub.active_seconds += seconds
        else:
            active.active_seconds += seconds
        return False

    def _sync_task_earned_from_subtasks(self, task: Task) -> None:
        task.sync_earned_from_subtasks()

    def _apply_roll_to_task(self, task: Task, reward: Reward) -> None:
        task.pending_rewards.append(reward)
        task.earned_gold += reward.gold
        task.earned_diamond += reward.diamond
        self.state.since_roll.gold += reward.gold
        self.state.since_roll.diamond += reward.diamond

    def _apply_roll_to_subtask(self, task: Task, sub: Subtask, reward: Reward) -> None:
        sub.pending_rewards.append(reward)
        sub.earned_gold += reward.gold
        sub.earned_diamond += reward.diamond
        self.state.since_roll.gold += reward.gold
        self.state.since_roll.diamond += reward.diamond

    # ----- 操作数与奖励 -----
    def record_operation(self, reward: Optional[Reward]) -> Optional[Reward]:
        """处理一次操作：仅记入聚焦叶子或无子树时的目标本身。

        返回实际记入的奖励；未记入时返回 None。
        """
        active = self.state.active_task()
        if active is None:
            return None

        if active.subtasks:
            sub = active.current_subtask()
            if sub is None:
                return None
            sub.operations += 1
            if reward is not None and not reward.is_empty():
                self._apply_roll_to_subtask(active, sub, reward)
                return reward
            return None

        active.operations += 1
        if reward is not None and not reward.is_empty():
            self._apply_roll_to_task(active, reward)
            return reward
        return None
