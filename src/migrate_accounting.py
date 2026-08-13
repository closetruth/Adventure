"""文件夹式目标计数：进度迁入 legacy 子叶子（加载迁移 / 分解 / 首次加子目标）。"""
from __future__ import annotations

import logging
from typing import List, Optional

from .models import LEGACY_TITLE_SUFFIX, AppState, Subtask, Task

logger = logging.getLogger(__name__)

LEGACY_SUFFIX = LEGACY_TITLE_SUFFIX


def subtask_has_stored_progress(sub: Subtask) -> bool:
    return bool(
        sub.operations
        or sub.earned_gold
        or sub.earned_diamond
        or sub.active_seconds
        or sub.pending_rewards
        or sub.done
    )


def task_has_stored_progress(task: Task) -> bool:
    return bool(
        task.operations
        or task.earned_gold
        or task.earned_diamond
        or task.active_seconds
        or task.pending_rewards
    )


def _clear_subtask_progress_fields(sub: Subtask) -> None:
    sub.operations = 0
    sub.earned_gold = 0.0
    sub.earned_diamond = 0.0
    sub.pending_rewards = []
    sub.done = False
    sub.rewards_claimed = False
    sub.active_seconds = 0.0
    sub.completed_at = None


def detach_subtask_progress_to_legacy(
    sub: Subtask,
    *,
    title: Optional[str] = None,
) -> Optional[Subtask]:
    """将 sub 自身进度迁入 legacy 子叶子并清零；无进度时返回 None。"""
    if not subtask_has_stored_progress(sub):
        return None
    legacy = Subtask(
        title=title or f"{sub.title}{LEGACY_SUFFIX}",
        target_seconds=sub.target_seconds,
        active_seconds=sub.active_seconds,
        operations=sub.operations,
        earned_gold=sub.earned_gold,
        earned_diamond=sub.earned_diamond,
        pending_rewards=list(sub.pending_rewards),
        done=sub.done,
        rewards_claimed=sub.rewards_claimed,
        is_legacy=True,
        created_at=sub.created_at,
        completed_at=sub.completed_at,
    )
    _clear_subtask_progress_fields(sub)
    return legacy


def detach_task_progress_to_legacy(task: Task) -> Optional[Subtask]:
    """将扁平目标上的进度迁入根级 legacy 子叶子并清零父字段。"""
    if not task_has_stored_progress(task):
        return None
    legacy = Subtask(
        title=f"{task.title}{LEGACY_SUFFIX}",
        target_seconds=600.0,
        active_seconds=task.active_seconds,
        operations=task.operations,
        earned_gold=task.earned_gold,
        earned_diamond=task.earned_diamond,
        pending_rewards=list(task.pending_rewards),
        is_legacy=True,
        created_at=task.created_at,
    )
    task.operations = 0
    task.earned_gold = 0.0
    task.earned_diamond = 0.0
    task.pending_rewards = []
    task.active_seconds = 0.0
    return legacy


def _migrate_subtask_tree(nodes: List[Subtask]) -> bool:
    changed = False
    for sub in nodes:
        if sub.is_container() and subtask_has_stored_progress(sub):
            legacy = detach_subtask_progress_to_legacy(sub)
            if legacy is not None:
                sub.children.insert(0, legacy)
                changed = True
        if sub.children and _migrate_subtask_tree(sub.children):
            changed = True
    return changed


def _fix_current_subtask_id(task: Task) -> bool:
    if task.current_subtask_id is None:
        return False
    sub = task.find_subtask(task.current_subtask_id)
    if sub is not None and not sub.done and sub.is_leaf():
        return False
    before = task.current_subtask_id
    for leaf in task.iter_leaves():
        if not leaf.done:
            task.current_subtask_id = leaf.id
            return task.current_subtask_id != before
    task.current_subtask_id = None
    return before is not None


def migrate_folder_accounting(state: AppState) -> bool:
    """加载后一次性迁移：文件夹/父目标上的进度 → （原进度）子叶子。"""
    changed = False
    for task in state.tasks:
        if task.subtasks and task_has_stored_progress(task):
            legacy = detach_task_progress_to_legacy(task)
            if legacy is not None:
                task.subtasks.insert(0, legacy)
                changed = True
                logger.info(
                    "迁移目标「%s」父级进度 → legacy 子叶子",
                    task.title,
                )
        if task.subtasks and _migrate_subtask_tree(task.subtasks):
            changed = True
        if _fix_current_subtask_id(task):
            changed = True
    return changed
