"""
Agent Journal — 智能工作日志

每次任务记录结构化的工作日志：
  - Task: 完成了什么
  - Decision: 做了什么关键决策
  - Result: 结果如何
  - Lesson: 学到了什么
  - Next: 下一次应该注意什么

长期价值：
  - 周报/月报自动生成
  - 经验积累
  - 工作模式分析
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


class AgentJournal:
    """智能工作日志"""

    def __init__(self, journal_dir: str = "journal"):
        self.journal_dir = Path(journal_dir)
        self.journal_dir.mkdir(parents=True, exist_ok=True)

    def write_entry(
        self,
        task_id: str,
        goal: str,
        domain: str,
        decisions: list[str],
        result: dict[str, Any],
        lessons: list[str],
        next_actions: Optional[list[str]] = None,
    ) -> str:
        """
        写入一条工作日志

        Returns:
            日志文件路径
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        entry = {
            "date": date_str,
            "time": datetime.now().strftime("%H:%M:%S"),
            "task_id": task_id,
            "domain": domain,
            "task": goal,
            "decisions": decisions,
            "result": {
                "success": result.get("success", False),
                "score": result.get("eval_result", {}).get("overall_score", 0),
                "duration_s": result.get("total_duration_s", 0),
                "cost_cny": result.get("cost_summary", {}).get("total_cost_cny", 0),
            },
            "lessons": lessons,
            "next_actions": next_actions or [],
        }

        # 追加到当日日志文件
        filename = f"{date_str}.yaml"
        filepath = self.journal_dir / filename

        entries = []
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                # 简单的YAML多文档处理
                if content.strip():
                    for doc in yaml.safe_load_all(content):
                        if doc:
                            entries.append(doc)

        entries.append(entry)

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump_all(entries, f, allow_unicode=True, sort_keys=False)

        logger.info(f"Journal entry written: {filepath}")
        return str(filepath)

    def read_journal(self, date: Optional[str] = None) -> list[dict]:
        """读取日志（指定日期或全部）"""
        if date:
            filepath = self.journal_dir / f"{date}.yaml"
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    return [d for d in yaml.safe_load_all(f) if d]
            return []
        # 全部
        all_entries = []
        for f in sorted(self.journal_dir.glob("*.yaml")):
            with open(f, "r", encoding="utf-8") as fh:
                for doc in yaml.safe_load_all(fh):
                    if doc:
                        all_entries.append(doc)
        return all_entries

    def generate_report(self, days: int = 7) -> dict[str, Any]:
        """生成周期报告"""
        entries = self.read_journal()
        recent = [
            e for e in entries
            if (datetime.now() - datetime.fromisoformat(e.get("date", "2000-01-01"))).days <= days
        ]

        if not recent:
            return {"period_days": days, "total_tasks": 0}

        domains = {}
        all_lessons = []
        all_next_actions = []
        total_cost = 0
        total_score = 0
        success_count = 0

        for e in recent:
            dom = e.get("domain", "general")
            domains[dom] = domains.get(dom, 0) + 1
            all_lessons.extend(e.get("lessons", []))
            all_next_actions.extend(e.get("next_actions", []))
            total_cost += e.get("result", {}).get("cost_cny", 0)
            score = e.get("result", {}).get("score", 0)
            total_score += score
            if e.get("result", {}).get("success"):
                success_count += 1

        return {
            "period_days": days,
            "total_tasks": len(recent),
            "success_rate": round(success_count / len(recent) * 100, 1),
            "avg_score": round(total_score / len(recent), 1),
            "total_cost_cny": round(total_cost, 2),
            "by_domain": domains,
            "key_lessons": all_lessons[:10],
            "pending_actions": all_next_actions[:5],
        }
