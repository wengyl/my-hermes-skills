"""
Goal Management — 长期目标管理+进度追踪

普通Agent：一次任务。
高级Agent：长期目标。

支持：
  - 创建长期目标（6个月投资体系提升）
  - 分解为周期任务（每周市场复盘/组合检查/知识学习）
  - 追踪进度
  - 定期提醒
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


class GoalManager:
    """长期目标管理"""

    def __init__(self, goals_dir: str = "goals"):
        self.goals_dir = Path(goals_dir)
        self.goals_dir.mkdir(parents=True, exist_ok=True)

    def create_goal(
        self,
        title: str,
        description: str,
        duration_days: int = 180,
        cycle_days: int = 7,
        tasks: Optional[list[dict]] = None,
    ) -> dict[str, Any]:
        """
        创建一个长期目标

        Args:
            title: 目标标题
            description: 目标描述
            duration_days: 总周期（天）
            cycle_days: 检查周期（天）
            tasks: 周期任务列表

        Returns:
            goal 记录
        """
        goal_id = f"goal_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        start = datetime.now()
        end = start + timedelta(days=duration_days)

        goal = {
            "goal_id": goal_id,
            "title": title,
            "description": description,
            "created_at": start.isoformat(),
            "end_date": end.isoformat(),
            "duration_days": duration_days,
            "cycle_days": cycle_days,
            "status": "active",
            "tasks": tasks or [],
            "progress": {
                "total_cycles": duration_days // cycle_days,
                "completed_cycles": 0,
                "completed_tasks": 0,
                "total_tasks": len(tasks or []),
            },
            "history": [],
        }

        filepath = self.goals_dir / f"{goal_id}.yaml"
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(goal, f, allow_unicode=True, sort_keys=False)

        logger.info(f"Goal created: {goal_id} — {title}")
        return goal

    def list_goals(self, status: str = "active") -> list[dict]:
        """列出目标"""
        goals = []
        for f in sorted(self.goals_dir.glob("*.yaml")):
            with open(f, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if data and data.get("status") == status:
                    goals.append(data)
        return goals

    def update_progress(
        self,
        goal_id: str,
        completed_tasks: Optional[list[str]] = None,
        cycle_completed: bool = False,
        notes: str = "",
    ) -> dict[str, Any]:
        """更新目标进度"""
        filepath = self.goals_dir / f"{goal_id}.yaml"
        if not filepath.exists():
            return {"error": f"Goal not found: {goal_id}"}

        with open(filepath, "r", encoding="utf-8") as f:
            goal = yaml.safe_load(f)

        if completed_tasks:
            goal["progress"]["completed_tasks"] += len(completed_tasks)
        if cycle_completed:
            goal["progress"]["completed_cycles"] += 1

        # 计算完成率
        total = goal["progress"]["total_tasks"]
        completed = goal["progress"]["completed_tasks"]
        goal["progress"]["completion_rate"] = round(completed / total * 100, 1) if total > 0 else 0

        # 记录历史
        goal["history"].append({
            "timestamp": datetime.now().isoformat(),
            "completed_tasks": completed_tasks or [],
            "cycle_completed": cycle_completed,
            "notes": notes,
        })

        # 检查是否完成
        if goal["progress"]["completion_rate"] >= 100:
            goal["status"] = "completed"
            goal["completed_at"] = datetime.now().isoformat()

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(goal, f, allow_unicode=True, sort_keys=False)

        return goal

    def get_due_tasks(self, goal_id: Optional[str] = None) -> list[dict]:
        """获取到期任务"""
        goals = [self.list_goals("active")] if not goal_id else [
            g for g in self.list_goals("active") if g["goal_id"] == goal_id
        ]
        due = []
        for goal in goals[0] if isinstance(goals[0], list) else goals:
            for task in goal.get("tasks", []):
                if task.get("status") != "completed":
                    due.append({
                        "goal_id": goal["goal_id"],
                        "goal_title": goal["title"],
                        "task": task,
                    })
        return due
