"""
任务状态机 — 标准化状态流转

状态流: created → planning → executing → evaluating → repairing → completed → learning
                                                   ↑                   │
                                                   └───── (重试) ──────┘
异常分支: 任意状态 → failed

每次状态流转持久化到 SQLite tasks 表。
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from .db import Database

logger = logging.getLogger(__name__)

# 合法状态
STATES = {
    "created", "planning", "executing", "evaluating",
    "repairing", "completed", "learning", "failed"
}

# 合法状态转换
TRANSITIONS: dict[str, set[str]] = {
    "created":    {"planning", "failed"},
    "planning":   {"executing", "failed"},
    "executing":  {"evaluating", "failed"},
    "evaluating": {"repairing", "completed", "learning", "failed"},
    "repairing":  {"executing", "evaluating", "failed"},
    "completed":  {"learning"},
    "learning":   set(),   # 终态
    "failed":     set(),   # 终态
}


class TaskStateMachine:
    """
    任务状态机。

    管理任务生命周期，每次状态流转校验合法性并持久化。
    """

    def __init__(self, db: Database):
        self.db = db

    def create_task(self, goal: str, task_id: Optional[str] = None) -> dict[str, Any]:
        """创建新任务，初始状态 created"""
        if task_id is None:
            task_id = f"task_{uuid.uuid4().hex[:12]}"

        task = self.db.create_task(task_id, goal)
        logger.info(f"Task created: {task_id} (goal: {goal[:60]}...)")
        return task

    def transition(self, task_id: str, new_state: str, **extra) -> dict[str, Any]:
        """
        执行状态转换。

        Args:
            task_id: 任务ID
            new_state: 目标状态
            **extra: 附加更新字段（如 plan_json, current_step, result_json 等）

        Returns:
            更新后的任务 dict

        Raises:
            ValueError: 非法状态转换
        """
        task = self.db.get_task(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        current_state = task["state"]

        # 校验状态转换合法性
        if new_state not in STATES:
            raise ValueError(f"Invalid state: {new_state}")

        if new_state not in TRANSITIONS.get(current_state, set()):
            raise ValueError(
                f"Illegal transition: {current_state} → {new_state}. "
                f"Allowed: {TRANSITIONS.get(current_state, set())}"
            )

        self.db.update_task_state(task_id, new_state, **extra)
        logger.info(f"Task {task_id}: {current_state} → {new_state}")

        return self.db.get_task(task_id)

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        return self.db.get_task(task_id)

    def list_tasks(self, state: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.list_tasks(state, limit)

    def set_plan(self, task_id: str, plan: dict[str, Any]):
        """设置执行计划，状态从 created → planning"""
        total_steps = len(plan.get("steps", []))
        return self.transition(
            task_id, "planning",
            plan_json=json.dumps(plan, ensure_ascii=False),
            total_steps=total_steps
        )

    def start_execution(self, task_id: str):
        """状态从 planning → executing"""
        return self.transition(task_id, "executing")

    def advance_step(self, task_id: str, step_index: int):
        """推进当前执行步骤"""
        self.db.update_task_state(task_id, "executing", current_step=step_index)

    def start_evaluation(self, task_id: str):
        """状态从 executing → evaluating"""
        return self.transition(task_id, "evaluating")

    def start_repair(self, task_id: str):
        """状态从 evaluating → repairing"""
        return self.transition(task_id, "repairing")

    def complete(self, task_id: str, result: dict[str, Any]):
        """状态从 evaluating → completed"""
        return self.transition(
            task_id, "completed",
            result_json=json.dumps(result, ensure_ascii=False)
        )

    def learn(self, task_id: str):
        """状态从 completed → learning"""
        return self.transition(task_id, "learning")

    def fail(self, task_id: str, error: str):
        """状态从任意 → failed"""
        task = self.db.get_task(task_id)
        if task and task["state"] != "failed":
            self.db.update_task_state(
                task_id, "failed",
                result_json=json.dumps({"error": error}, ensure_ascii=False)
            )
            logger.error(f"Task {task_id} FAILED: {error}")

    def increment_retry(self, task_id: str):
        """增加重试计数"""
        task = self.db.get_task(task_id)
        if task:
            self.db.update_task_state(
                task_id, task["state"],
                retry_count=task["retry_count"] + 1
            )
