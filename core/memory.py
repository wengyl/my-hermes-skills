"""
Memory 记忆子系统 — 四类分类存储

分类:
  user_memory    — 用户固定风格、偏好配置
  failure_memory — 技能失败场景 + 解决方案（规划阶段自动规避）
  skill_memory   — 技能历史运行统计
  best_case      — 高分成功任务样例

存储: SQLite memory_store 表 + 文件备份到 memory/ 目录
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .db import Database

logger = logging.getLogger(__name__)

MEM_TYPES = {"user", "failure", "skill", "best_case"}


class MemorySubsystem:
    """
    Memory 记忆子系统

    四类记忆的读写接口 + Planner 集成（规划阶段查询 failure_memory 规避已知问题）
    """

    def __init__(self, db: Database, memory_dir: str = "memory"):
        self.db = db
        self.memory_dir = Path(memory_dir)

    # ── user_memory: 用户偏好 ──

    def save_user_preference(self, key: str, value: Any, domain: Optional[str] = None):
        """存储用户偏好（如视频风格、投资偏好）"""
        self.db.store_memory("user", key, value, domain=domain)
        logger.info(f"User preference saved: {key}")

    def get_user_preferences(self, domain: Optional[str] = None) -> list[dict[str, Any]]:
        """读取用户偏好"""
        return self.db.search_memory(mem_type="user", limit=50)

    # ── failure_memory: 失败案例 ──

    def save_failure(
        self, skill_name: str, task_id: str, defects: list[str],
        context: dict[str, Any], solution: Optional[str] = None
    ):
        """
        记录失败案例，供 Planner 规划阶段自动规避。

        Args:
            skill_name: 失败的技能名
            task_id: 任务ID
            defects: 缺陷清单
            context: 失败时的上下文
            solution: 解决方案（如果有）
        """
        value = {
            "skill_name": skill_name,
            "task_id": task_id,
            "defects": defects,
            "context": context,
            "solution": solution,
            "timestamp": datetime.now().isoformat(),
        }
        key = f"failure:{skill_name}:{task_id}"
        self.db.store_memory(
            "failure", key, value,
            skill_name=skill_name, task_id=task_id
        )
        logger.info(f"Failure saved: {skill_name} (task {task_id})")

    def get_failures(
        self, skill_name: Optional[str] = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """查询失败案例"""
        if skill_name:
            return self.db.search_memory(
                mem_type="failure", key=f"failure:{skill_name}", limit=limit
            )
        return self.db.search_memory(mem_type="failure", limit=limit)

    def get_failure_patterns(self, skill_name: str) -> list[dict[str, Any]]:
        """
        获取某技能的失败模式汇总（供 Planner 规避）。

        Returns:
            [{ "defect_pattern": str, "count": int, "solution": str, "last_seen": str }]
        """
        failures = self.get_failures(skill_name)
        patterns: dict[str, dict[str, Any]] = {}

        for f in failures:
            value = f.get("value", {})
            for defect in value.get("defects", []):
                if defect not in patterns:
                    patterns[defect] = {
                        "defect_pattern": defect,
                        "count": 0,
                        "solution": value.get("solution"),
                        "last_seen": value.get("timestamp", ""),
                    }
                patterns[defect]["count"] += 1
                if value.get("solution"):
                    patterns[defect]["solution"] = value["solution"]

        return sorted(patterns.values(), key=lambda x: x["count"], reverse=True)

    # ── skill_memory: 技能运行统计 ──

    def save_skill_stats(
        self, skill_name: str, task_id: str,
        success: bool, score: float, duration_ms: int, cost_cny: float = 0
    ):
        """记录技能运行统计"""
        value = {
            "skill_name": skill_name,
            "task_id": task_id,
            "success": success,
            "score": score,
            "duration_ms": duration_ms,
            "cost_cny": cost_cny,
            "timestamp": datetime.now().isoformat(),
        }
        key = f"stat:{skill_name}:{task_id}"
        self.db.store_memory(
            "skill", key, value,
            skill_name=skill_name, task_id=task_id, score=score
        )

    def get_skill_stats(self, skill_name: str, limit: int = 50) -> list[dict[str, Any]]:
        """查询技能历史运行统计"""
        return self.db.search_memory(
            mem_type="skill", key=f"stat:{skill_name}", limit=limit
        )

    def get_skill_summary(self, skill_name: str) -> dict[str, Any]:
        """汇总某技能的运行统计"""
        stats = self.get_skill_stats(skill_name)
        if not stats:
            return {"total_runs": 0, "avg_score": 0, "success_rate": 0}

        total = len(stats)
        successes = sum(1 for s in stats if s.get("value", {}).get("success"))
        scores = [s.get("value", {}).get("score", 0) for s in stats]
        durations = [s.get("value", {}).get("duration_ms", 0) for s in stats]
        costs = [s.get("value", {}).get("cost_cny", 0) for s in stats]

        return {
            "total_runs": total,
            "success_rate": round(successes / total * 100, 1),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "avg_duration_ms": round(sum(durations) / len(durations)) if durations else 0,
            "total_cost_cny": round(sum(costs), 2),
        }

    # ── best_case: 高分成功样例 ──

    def save_best_case(
        self, task_id: str, goal: str, plan: dict[str, Any],
        result: dict[str, Any], score: float, domain: str
    ):
        """保存高分成功任务作为参考样例"""
        value = {
            "task_id": task_id,
            "goal": goal,
            "plan": plan,
            "result": result,
            "score": score,
            "domain": domain,
            "timestamp": datetime.now().isoformat(),
        }
        key = f"best:{task_id}"
        self.db.store_memory(
            "best_case", key, value,
            domain=domain, task_id=task_id, score=score
        )
        logger.info(f"Best case saved: task {task_id} (score {score})")

    def get_best_cases(
        self, domain: Optional[str] = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """查询高分成功样例"""
        if domain:
            # 搜索包含域名的key
            return self.db.search_memory(mem_type="best_case", limit=limit)
        return self.db.search_memory(mem_type="best_case", limit=limit)

    # ── Planner 集成 ──

    def get_planner_context(self, domain: str) -> dict[str, Any]:
        """
        为 Planner 提供记忆上下文。

        返回:
            {
                "known_failures": [ {skill, defect_pattern, solution} ],
                "user_preferences": [ {key, value} ],
                "best_cases": [ {task_id, goal, score} ],
                "skill_stats": { skill_name: {success_rate, avg_score} }
            }
        """
        # 已知失败模式（按域过滤）
        caps = self.db.list_capabilities(domain=domain)
        known_failures: list[dict[str, Any]] = []
        for cap in caps:
            patterns = self.get_failure_patterns(cap["name"])
            for p in patterns:
                known_failures.append({
                    "skill": cap["name"],
                    "defect_pattern": p["defect_pattern"],
                    "solution": p.get("solution"),
                    "count": p["count"],
                })

        return {
            "known_failures": known_failures,
            "user_preferences": self.get_user_preferences(),
            "best_cases": self.get_best_cases(domain),
            "domain": domain,
        }

    # ── 维护 ──

    def evict_old(self, max_age_days: int = 90):
        """清理过期记忆"""
        # 简化实现：实际需要按 created_at 清理
        logger.info(f"Evicting memories older than {max_age_days} days")
        # TODO: implement SQL DELETE for old records
