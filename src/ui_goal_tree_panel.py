"""单目标树面板：与悬浮窗一致的树 + 添加栏 + 详情区。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .models import AppState, Subtask, Task, TaskStatus
from .task_manager import TaskManager
from .ui_task_tree import (
    TREE_INDENT_PX,
    SubtaskActionCallbacks,
    TreeRow,
    apply_goal_block_ui,
    apply_goal_root_row_state,
    apply_subtask_block_ui,
    build_subtask_action_buttons,
)
from .ui_text import (
    format_amount,
    format_goal_root_line_html,
    format_subgoals_focus_hint_html,
    format_tree_detail_html,
    format_tree_node_html,
)

SUBGOAL_INDENT_PX = TREE_INDENT_PX


class GoalTreePanel(QWidget):
    """单个目标的树形 UI：GoalBlock 树、外置添加栏、详情统计面板。"""

    action = Signal(str, str, str)  # task_id, action_name, extra

    def __init__(
        self,
        task: Task,
        manager: TaskManager,
        state: AppState,
        *,
        editable: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.task = task
        self.manager = manager
        self.state = state
        self._editable = editable

        self._selected_subtask_id = ""
        self._goal_expanded = True
        self._sub_add_parent_id: Optional[str] = None
        self._structure_sig: tuple | None = None
        self._goal_detail_actions_sig: tuple | None = None

        self._goal_root_row: TreeRow | None = None
        self._goal_root_line: QLabel | None = None
        self._goal_block: QWidget | None = None
        self._subgoal_line_labels: dict[str, QLabel] = {}
        self._tree_row_widgets: dict[str, TreeRow] = {}
        self._subtask_blocks: dict[str, QWidget] = {}

        self._build_ui()
        self.refresh(task)

    def selected_subtask_id(self) -> str:
        return self._selected_subtask_id

    def set_selected_subtask_id(self, subtask_id: str) -> None:
        self._selected_subtask_id = subtask_id
        since = self.state.since_roll
        self._apply_selection_ui(
            since_gold=since.gold,
            since_diamond=since.diamond,
        )

    def set_add_parent(self, parent_subtask_id: str) -> None:
        self._sub_add_parent_id = parent_subtask_id
        self._selected_subtask_id = parent_subtask_id
        parent = self.task.find_subtask(parent_subtask_id)
        if parent is not None:
            self._subgoal_input.setPlaceholderText(f"添加到「{parent.title}」下…")
        else:
            self._subgoal_input.setPlaceholderText("添加目标…")
        self._update_add_context()
        self._subgoal_input.setFocus()
        since = self.state.since_roll
        self._apply_selection_ui(
            since_gold=since.gold,
            since_diamond=since.diamond,
        )

    def refresh(
        self,
        task: Task | None = None,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
    ) -> None:
        if task is not None:
            self.task = task
        if since_gold == 0.0 and since_diamond == 0.0:
            since = self.state.since_roll
            since_gold = since.gold
            since_diamond = since.diamond

        sig = self._structure_signature()
        if sig != self._structure_sig:
            self._rebuild_tree(since_gold=since_gold, since_diamond=since_diamond)
        else:
            self._apply_selection_ui(
                since_gold=since_gold,
                since_diamond=since_diamond,
            )

        self._update_focus_hint()
        self._add_bar.setVisible(self._editable)
        self._refresh_detail_panel(since_gold=since_gold, since_diamond=since_diamond)

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._focus_hint = QLabel("")
        self._focus_hint.setObjectName("SubGoalHint")
        self._focus_hint.setWordWrap(True)
        self._focus_hint.hide()
        lay.addWidget(self._focus_hint)

        self._tree_host = QWidget()
        self._tree_layout = QVBoxLayout(self._tree_host)
        self._tree_layout.setContentsMargins(0, 0, 0, 0)
        self._tree_layout.setSpacing(0)
        lay.addWidget(self._tree_host)

        self._add_bar = QWidget()
        self._add_bar.setObjectName("SubGoalActions")
        add_outer = QVBoxLayout(self._add_bar)
        add_outer.setContentsMargins(0, 0, 0, 0)
        add_outer.setSpacing(4)

        add_row = QHBoxLayout()
        add_row.setSpacing(4)
        self._subgoal_input = QLineEdit()
        self._subgoal_input.setObjectName("SubGoalInput")
        self._subgoal_input.setPlaceholderText("添加目标…")
        self._subgoal_input.returnPressed.connect(self._on_add_subgoal)
        add_row.addWidget(self._subgoal_input, 1)

        default_min = max(
            1, int(self.state.settings.get("subtask_default_target_minutes", 10)),
        )
        self._subgoal_min_spin = QSpinBox()
        self._subgoal_min_spin.setObjectName("SubtaskMinSpin")
        self._subgoal_min_spin.setRange(1, 999)
        self._subgoal_min_spin.setValue(default_min)
        self._subgoal_min_spin.setPrefix("最少 ")
        self._subgoal_min_spin.setSuffix(" 分")
        self._subgoal_min_spin.setToolTip("新目标需运行的最短时间（完成后可领取）")
        self._subgoal_min_spin.setFixedWidth(96)
        add_row.addWidget(self._subgoal_min_spin)

        self._sub_add_btn = QPushButton("添加")
        self._sub_add_btn.setObjectName("SubAddBtn")
        self._sub_add_btn.setCursor(Qt.PointingHandCursor)
        self._sub_add_btn.clicked.connect(self._on_add_subgoal)
        add_row.addWidget(self._sub_add_btn)
        add_outer.addLayout(add_row)

        self._add_context = QLabel("")
        self._add_context.setObjectName("SubGoalHint")
        self._add_context.setWordWrap(True)
        self._add_context.hide()
        add_outer.addWidget(self._add_context)

        lay.addWidget(self._add_bar)

        self._detail_panel = QWidget()
        self._detail_panel.setObjectName("GoalDetailPanel")
        detail_lay = QVBoxLayout(self._detail_panel)
        detail_lay.setContentsMargins(8, 6, 8, 6)
        detail_lay.setSpacing(4)

        self._detail_title = QLabel("")
        self._detail_title.setObjectName("GoalDetailTitle")
        self._detail_title.setWordWrap(True)
        detail_lay.addWidget(self._detail_title)

        self._detail_stats = QLabel("")
        self._detail_stats.setObjectName("GoalDetailStats")
        self._detail_stats.setWordWrap(True)
        self._detail_stats.setTextFormat(Qt.RichText)
        detail_lay.addWidget(self._detail_stats)

        self._detail_btn_row = QWidget()
        self._detail_btn_lay = QHBoxLayout(self._detail_btn_row)
        self._detail_btn_lay.setContentsMargins(0, 0, 0, 0)
        self._detail_btn_lay.setSpacing(6)
        detail_lay.addWidget(self._detail_btn_row)

        self._detail_panel.hide()
        lay.addWidget(self._detail_panel)

    def _structure_signature(self) -> tuple:
        expanded = frozenset(self.manager.expanded_subtask_ids(self.task.id))
        if self._goal_expanded:
            sub_part = tuple(
                (
                    s.id,
                    s.title,
                    s.done,
                    s.rewards_claimed,
                    s.is_container(),
                )
                for _, s in self.manager.iter_visible_subtasks(self.task)
            )
        else:
            sub_part = ()
        return (
            self.task.id,
            self.task.title,
            self.task.status,
            self._goal_expanded,
            expanded,
            sub_part,
        )

    def _clear_tree_layout(self) -> None:
        self._goal_root_row = None
        self._goal_root_line = None
        self._goal_block = None
        self._subgoal_line_labels.clear()
        self._tree_row_widgets.clear()
        self._subtask_blocks.clear()
        self._goal_detail_actions_sig = None
        while self._tree_layout.count():
            item = self._tree_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                GoalTreePanel._clear_layout(item.layout())

    def _rebuild_tree(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
    ) -> None:
        self._clear_tree_layout()
        self._structure_sig = self._structure_signature()

        task = self.task
        is_running = task.status == TaskStatus.ACTIVE
        editable = self._editable
        root_selected = not self._selected_subtask_id

        block = QWidget()
        block.setObjectName("GoalBlock")
        block.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(0)

        root_row, root_line = self._make_goal_root_row(selected=root_selected)
        self._goal_root_row = root_row
        self._goal_root_line = root_line
        block_layout.addWidget(root_row)

        if self._goal_expanded:
            current = task.current_subtask() if editable else None
            current_id = current.id if current is not None else None

            if not task.subtasks and is_running:
                hint = QLabel("添加目标后开始累计奖励")
                hint.setObjectName("SubGoalList")
                hint.setWordWrap(True)
                hint.setContentsMargins(22, 0, 4, 0)
                block_layout.addWidget(hint)
            else:
                for depth, sub in self.manager.iter_visible_subtasks(task):
                    key = sub.id
                    row, line = self._make_tree_node_row(
                        sub,
                        depth=depth + 1,
                        selected=sub.id == self._selected_subtask_id,
                        is_current=sub.id == current_id,
                        editable=editable,
                        current_id=current_id,
                    )
                    self._subgoal_line_labels[key] = line
                    self._tree_row_widgets[key] = row

                    sub_block = QWidget()
                    sub_block.setObjectName("SubtaskBlock")
                    sub_block.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
                    sub_block_layout = QVBoxLayout(sub_block)
                    sub_block_layout.setContentsMargins(0, 0, 0, 0)
                    sub_block_layout.setSpacing(0)
                    sub_block_layout.addWidget(row)
                    self._subtask_blocks[key] = sub_block

                    indent_wrap = QWidget()
                    indent_wrap.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
                    indent_lay = QHBoxLayout(indent_wrap)
                    indent_lay.setContentsMargins(
                        (depth + 1) * SUBGOAL_INDENT_PX,
                        0,
                        0,
                        0,
                    )
                    indent_lay.setSpacing(0)
                    indent_lay.addWidget(sub_block)
                    block_layout.addWidget(indent_wrap)

        self._goal_block = block
        apply_goal_block_ui(
            block,
            is_running=is_running,
            selected=root_selected,
            focused=False,
        )
        self._tree_layout.addWidget(block, 0, Qt.AlignLeft)
        self._apply_selection_ui(since_gold=since_gold, since_diamond=since_diamond)

    def _make_goal_root_row(self, *, selected: bool) -> tuple[TreeRow, QLabel]:
        task = self.task
        is_running = task.status == TaskStatus.ACTIVE
        row = TreeRow()
        row.setObjectName("GoalRootRow")
        row.setCursor(Qt.PointingHandCursor)
        row.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        apply_goal_root_row_state(row, is_running=is_running)
        row.set_row_selected(selected)

        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(4, 3, 4, 3)
        row_lay.setSpacing(4)

        has_children = bool(task.subtasks) or is_running
        if has_children:
            btn_fold = QPushButton("v" if self._goal_expanded else ">")
            btn_fold.setObjectName("TreeFoldBtn")
            btn_fold.setCursor(Qt.PointingHandCursor)
            btn_fold.setFixedSize(18, 18)
            btn_fold.clicked.connect(self._on_goal_toggle_fold)
            row_lay.addWidget(btn_fold, 0, Qt.AlignVCenter)

        line = QLabel(
            format_goal_root_line_html(
                task,
                selected=selected,
                is_running=is_running,
                muted=task.status == TaskStatus.PAUSED,
            )
        )
        line.setObjectName("TaskTitle")
        line.setWordWrap(False)
        line.setTextFormat(Qt.RichText)
        line.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        row_lay.addWidget(line, 0)

        row.selected.connect(lambda: self._on_tree_select("", editable=False))
        row.style().unpolish(row)
        row.style().polish(row)
        return row, line

    def _make_tree_node_row(
        self,
        sub: Subtask,
        *,
        depth: int,
        selected: bool,
        is_current: bool,
        editable: bool,
        current_id: Optional[str],
    ) -> tuple[TreeRow, QLabel]:
        task = self.task
        row = TreeRow()
        row.setObjectName("TreeNodeRow")
        row.setCursor(Qt.PointingHandCursor)
        row.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        if depth > 0:
            row.setProperty("nested", True)
        row.set_row_selected(selected)

        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(4, 3, 4, 3)
        row_lay.setSpacing(4)

        if sub.is_container():
            expanded = self.manager.is_subtask_expanded(task.id, sub.id)
            btn_fold = QPushButton("v" if expanded else ">")
            btn_fold.setObjectName("TreeFoldBtn")
            btn_fold.setCursor(Qt.PointingHandCursor)
            btn_fold.setFixedSize(18, 18)
            btn_fold.clicked.connect(
                lambda _c=False, sid=sub.id: self._emit_toggle_fold(sid)
            )
            row_lay.addWidget(btn_fold, 0, Qt.AlignVCenter)

        show_stats = selected or is_current
        line = QLabel(
            format_tree_node_html(
                sub,
                selected=selected,
                is_current=is_current,
                expanded=self.manager.is_subtask_expanded(task.id, sub.id),
                show_stats=show_stats,
            )
        )
        line.setObjectName("SubGoalList")
        line.setWordWrap(False)
        line.setTextFormat(Qt.RichText)
        line.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        row_lay.addWidget(line, 0)

        callbacks = SubtaskActionCallbacks(
            on_claim=lambda sid=sub.id: self.action.emit(
                task.id, "subtask_claim", sid,
            ),
            on_focus=lambda sid=sub.id: self.action.emit(
                task.id, "subtask_focus", sid,
            ),
            on_pause=lambda: self.action.emit(task.id, "subtask_pause", ""),
            on_complete=lambda sid=sub.id: self.action.emit(
                task.id, "subtask_confirm_done", sid,
            ),
            on_decompose=lambda sid=sub.id: self._prompt_decompose(sid),
            on_delete=lambda sid=sub.id: self.action.emit(
                task.id, "subtask_delete", sid,
            ),
            on_add_child=lambda sid=sub.id: self.set_add_parent(sid),
        )
        actions = build_subtask_action_buttons(
            sub,
            editable=editable,
            current_id=current_id,
            callbacks=callbacks,
            parent=row,
        )
        row.set_actions_widget(actions)
        row_lay.addWidget(actions, 0, Qt.AlignVCenter)

        row.selected.connect(
            lambda s=sub, e=editable: self._on_tree_select(s.id, sub=s, editable=e)
        )
        row.style().unpolish(row)
        row.style().polish(row)
        return row, line

    def _on_goal_toggle_fold(self) -> None:
        self._goal_expanded = not self._goal_expanded
        since = self.state.since_roll
        self.refresh(since_gold=since.gold, since_diamond=since.diamond)

    def _emit_toggle_fold(self, subtask_id: str) -> None:
        self.action.emit(self.task.id, "subtask_toggle_fold", subtask_id)

    def _on_tree_select(
        self,
        subtask_id: str,
        *,
        sub: Subtask | None = None,
        editable: bool = False,
    ) -> None:
        self._selected_subtask_id = subtask_id
        since = self.state.since_roll
        self._apply_selection_ui(
            since_gold=since.gold,
            since_diamond=since.diamond,
        )
        if sub is not None and sub.is_container():
            self._emit_toggle_fold(sub.id)
            return
        if (
            editable
            and sub is not None
            and sub.is_leaf()
            and not sub.done
            and not sub.rewards_claimed
        ):
            self.action.emit(self.task.id, "subtask_focus", sub.id)

    def _apply_selection_ui(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
    ) -> None:
        self._apply_selection_chrome()
        self._refresh_tree_labels(
            since_gold=since_gold,
            since_diamond=since_diamond,
        )
        self._refresh_detail_panel(since_gold=since_gold, since_diamond=since_diamond)

    def _apply_selection_chrome(self) -> None:
        if self._goal_root_row is not None:
            self._goal_root_row.set_row_selected(not self._selected_subtask_id)
        for sid, row in self._tree_row_widgets.items():
            row.set_row_selected(sid == self._selected_subtask_id)
        for sid, sub_block in self._subtask_blocks.items():
            apply_subtask_block_ui(
                sub_block,
                selected=bool(self._selected_subtask_id)
                and sid == self._selected_subtask_id,
                focused=False,
            )
        if self._goal_block is not None:
            apply_goal_block_ui(
                self._goal_block,
                is_running=self.task.status == TaskStatus.ACTIVE,
                selected=not self._selected_subtask_id,
                focused=False,
            )

    def _refresh_tree_labels(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
        stats_only: bool = False,
    ) -> None:
        task = self.task
        editable = self._editable
        current = task.current_subtask() if editable else None
        current_id = current.id if current is not None else None

        if not stats_only and self._goal_root_line is not None:
            self._goal_root_line.setText(
                format_goal_root_line_html(
                    task,
                    selected=not self._selected_subtask_id,
                    is_running=task.status == TaskStatus.ACTIVE,
                    muted=task.status == TaskStatus.PAUSED,
                )
            )

        for sid, sub_line in self._subgoal_line_labels.items():
            sub = task.find_subtask(sid)
            if sub is None:
                continue
            is_selected = sid == self._selected_subtask_id
            is_current = sid == current_id
            if stats_only and not (is_selected or is_current):
                continue
            show_stats = is_selected or is_current
            sub_line.setText(
                format_tree_node_html(
                    sub,
                    selected=is_selected,
                    is_current=is_current,
                    expanded=self.manager.is_subtask_expanded(task.id, sub.id),
                    show_stats=show_stats,
                )
            )

    def _subtask_completion_bonus(self) -> float:
        return float(self.state.settings.get("subtask_completion_bonus_gold", 0.5))

    def _format_detail_stats_html(
        self,
        task: Task,
        sub: Subtask | None,
        *,
        since_gold: float,
        since_diamond: float,
    ) -> str:
        html = format_tree_detail_html(
            task,
            sub,
            since_roll_gold=since_gold,
            since_roll_diamond=since_diamond,
            completion_bonus=self._subtask_completion_bonus(),
        )
        if sub is None and task.status == TaskStatus.COMPLETED:
            settlement = (
                f'<span style="color:#8b93a8">结算 '
                f"金 {format_amount(task.completed_reward_gold)} "
                f"钻 {format_amount(task.completed_reward_diamond)}</span>"
            )
            html = f"{html}<br>{settlement}"
        return html

    @staticmethod
    def _goal_detail_actions_signature(
        task: Task,
        sub: Subtask | None,
    ) -> tuple:
        if sub is None:
            return ("goal", task.id, task.status)
        return (
            "sub",
            task.id,
            sub.id,
            sub.done,
            sub.rewards_claimed,
            sub.is_leaf(),
            sub.is_container(),
            sub.is_claimable(),
            sub.can_claim_pending(),
            sub.time_target_met(),
            task.current_subtask_id,
            task.status,
        )

    def _refresh_detail_panel(
        self,
        *,
        since_gold: float = 0.0,
        since_diamond: float = 0.0,
    ) -> None:
        task = self.task
        self._detail_panel.show()

        sub: Subtask | None = None
        if self._selected_subtask_id:
            sub = task.find_subtask(self._selected_subtask_id)

        title_text = sub.title if sub is not None else task.title
        self._detail_title.setText(title_text)
        self._detail_stats.setText(
            self._format_detail_stats_html(
                task,
                sub,
                since_gold=since_gold,
                since_diamond=since_diamond,
            )
        )

        actions_sig = self._goal_detail_actions_signature(task, sub)
        if actions_sig == self._goal_detail_actions_sig:
            return
        self._goal_detail_actions_sig = actions_sig
        self._clear_layout(self._detail_btn_lay)

        if sub is None:
            if task.status == TaskStatus.PAUSED:
                btn = QPushButton("开始")
                btn.setObjectName("GoalResumeBtn")
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(
                    lambda _c=False: self.action.emit(task.id, "resume", "")
                )
                self._detail_btn_lay.addWidget(btn)
            elif task.status == TaskStatus.ACTIVE:
                btn = QPushButton("暂停")
                btn.setObjectName("GoalPauseBtn")
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(
                    lambda _c=False: self.action.emit(task.id, "pause", "")
                )
                self._detail_btn_lay.addWidget(btn)

        self._detail_btn_lay.addStretch(1)

    def _update_focus_hint(self) -> None:
        if self.task.status != TaskStatus.ACTIVE:
            self._focus_hint.hide()
            return
        hint = format_subgoals_focus_hint_html(self.task)
        if hint:
            self._focus_hint.setTextFormat(Qt.RichText)
            self._focus_hint.setText(hint)
            self._focus_hint.show()
        else:
            self._focus_hint.hide()

    def _update_add_context(self) -> None:
        if self._sub_add_parent_id:
            parent = self.task.find_subtask(self._sub_add_parent_id)
            if parent is not None:
                self._add_context.setText(f"将添加到「{parent.title}」下")
                self._add_context.show()
                return
        self._add_context.hide()

    def _prompt_decompose(self, subtask_id: str) -> None:
        text, ok = QInputDialog.getText(
            self,
            "分解目标",
            "子项名称（多个用逗号分隔）：",
            text="子项1, 子项2",
        )
        if not ok:
            return
        titles = [p.strip() for p in text.replace("，", ",").split(",") if p.strip()]
        if not titles:
            return
        self.action.emit(
            self.task.id,
            "subtask_decompose",
            f"{subtask_id}|{','.join(titles)}",
        )

    def _on_add_subgoal(self) -> None:
        title = self._subgoal_input.text().strip()
        if not title:
            return
        target_minutes = self._subgoal_min_spin.value()
        self.action.emit(
            self.task.id,
            "subtask_add",
            f"{title}|{target_minutes}|{self._sub_add_parent_id or ''}",
        )
        self._subgoal_input.clear()
        self._sub_add_parent_id = None
        self._subgoal_input.setPlaceholderText("添加目标…")
        self._update_add_context()
