"""目标级操作（完成 / 删除）共享 UI 逻辑。"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from .task_manager import TaskManager
from .ui_confirm import ask_yes_no
from .ui_text import format_reward_gain


def try_complete_goal(parent: QWidget, manager: TaskManager, task_id: str) -> bool:
    """尝试完成目标；成功返回 True。"""
    task = manager.get(task_id)
    if task is None:
        return False
    if not manager.can_complete_task(task_id):
        QMessageBox.information(
            parent,
            "提示",
            "请先完成所有子目标，再完成此目标。",
        )
        return False
    reward = manager.complete(task_id)
    if reward is not None and not reward.is_empty():
        QMessageBox.information(
            parent,
            "恭喜",
            f"目标「{task.title}」已完成！\n获得 {format_reward_gain(reward.gold, reward.diamond)}",
        )
    else:
        QMessageBox.information(
            parent,
            "完成",
            f"目标「{task.title}」已完成。本次没有累计到奖励。",
        )
    return True


def try_delete_goal(parent: QWidget, manager: TaskManager, task_id: str) -> bool:
    """尝试删除目标；用户确认并删除后返回 True。"""
    task = manager.get(task_id)
    if task is None:
        return False
    if not ask_yes_no(
        parent,
        "删除目标",
        f"确定要删除「{task.title}」吗？\n未领取的奖励将一并丢失。",
    ):
        return False
    manager.delete(task_id)
    return True
