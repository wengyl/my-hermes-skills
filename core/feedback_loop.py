"""
Feedback Loop — 结构化用户反馈收集+学习闭环 (P1)

核心理念：用户反馈是提升质量最快的信号

反馈结构：
  rating: 1-5 (或 👍/👎)
  category: quality / accuracy / speed / style / cost
  comment: 文本反馈
  task_id: 关联任务
  corrections: 用户修改了什么

学习闭环：
  1. 收集反馈 → feedback/ 目录
  2. 模式分析：发现反复出现的负面反馈模式
  3. 生成知识候选 → 走 ReflectionEngine 候选管道
  4. 合并后影响后续任务
"""

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


class FeedbackLoop:
    """
    Feedback Loop — 用户反馈收集与学习

    存储：feedback/{date}_{task_id}.yaml
    分析：按 category + rating 统计模式
    """

    def __init__(self, feedback_dir: str = "feedback"):
        self.feedback_dir = Path(feedback_dir)
        self.feedback_dir.mkdir(parents=True, exist_ok=True)
        self._records: list[dict] = []
        self._load_history()

    def _load_history(self):
        """加载历史反馈"""
        for f in sorted(self.feedback_dir.glob("*.yaml")):
            with open(f, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if data:
                    self._records.append(data)

    def record_feedback(
        self,
        task_id: str,
        rating: int,
        category: str = "quality",
        comment: str = "",
        corrections: Optional[list[str]] = None,
        domain: str = "general",
    ) -> dict[str, Any]:
        """
        记录一条用户反馈

        Args:
            task_id: 关联任务ID
            rating: 1-5 评分 (5=最好)
            category: quality/accuracy/speed/style/cost
            comment: 文本反馈
            corrections: 用户做了哪些修改
            domain: 业务域

        Returns:
            反馈记录 + 学习分析
        """
        record = {
            "feedback_id": f"fb_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id[-6:]}",
            "task_id": task_id,
            "rating": rating,
            "category": category,
            "comment": comment,
            "corrections": corrections or [],
            "domain": domain,
            "timestamp": datetime.now().isoformat(),
        }

        # 持久化
        filename = f"{datetime.now().strftime('%Y%m%d')}_{task_id}.yaml"
        filepath = self.feedback_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(record, f, allow_unicode=True, sort_keys=False)

        self._records.append(record)

        # 分析反馈
        analysis = self._analyze_feedback(record)

        logger.info(f"Feedback recorded: task={task_id}, rating={rating}, category={category}")
        return {"record": record, "analysis": analysis}

    def _analyze_feedback(self, record: dict) -> dict[str, Any]:
        """分析单条反馈"""
        analysis: dict[str, Any] = {
            "sentiment": "positive" if record["rating"] >= 4 else "negative" if record["rating"] <= 2 else "neutral",
            "actionable": False,
            "learning_signal": None,
        }

        if record["rating"] <= 2:
            analysis["actionable"] = True
            if record.get("corrections"):
                analysis["learning_signal"] = (
                    f"用户修改了: {', '.join(record['corrections'])}"
                )
            elif record.get("comment"):
                analysis["learning_signal"] = record["comment"]

        # 检查是否为反复出现的负面模式
        if analysis["sentiment"] == "negative":
            pattern_count = self._count_similar_negative(
                record["domain"], record["category"]
            )
            if pattern_count >= 3:
                analysis["recurring_pattern"] = True
                analysis["pattern_count"] = pattern_count
                analysis["recommendation"] = (
                    f"域{record['domain']}在{record['category']}方面有{pattern_count}次负面反馈，"
                    f"建议生成知识候选改进"
                )

        return analysis

    def _count_similar_negative(self, domain: str, category: str) -> int:
        """统计同域同类的负面反馈次数"""
        return sum(
            1 for r in self._records
            if r.get("domain") == domain
            and r.get("category") == category
            and r.get("rating", 5) <= 2
        )

    def get_feedback_patterns(self) -> dict[str, Any]:
        """
        分析所有历史反馈，发现模式

        Returns:
            {
                "total_feedback": int,
                "avg_rating": float,
                "by_category": {category: {avg_rating, count, negative_rate}},
                "by_domain": {domain: {avg_rating, count}},
                "recurring_negatives": [{domain, category, count, examples}],
                "improvement_candidates": [str],
            }
        """
        if not self._records:
            return {"total_feedback": 0, "avg_rating": 0}

        total = len(self._records)
        avg = sum(r["rating"] for r in self._records) / total

        # 按类别统计
        by_category: dict[str, dict] = defaultdict(lambda: {"ratings": [], "count": 0, "negatives": 0})
        by_domain: dict[str, dict] = defaultdict(lambda: {"ratings": [], "count": 0})

        for r in self._records:
            cat = r.get("category", "unknown")
            dom = r.get("domain", "general")
            by_category[cat]["ratings"].append(r["rating"])
            by_category[cat]["count"] += 1
            if r["rating"] <= 2:
                by_category[cat]["negatives"] += 1
            by_domain[dom]["ratings"].append(r["rating"])
            by_domain[dom]["count"] += 1

        category_summary = {}
        for cat, d in by_category.items():
            category_summary[cat] = {
                "avg_rating": round(sum(d["ratings"]) / len(d["ratings"]), 1),
                "count": d["count"],
                "negative_rate": round(d["negatives"] / d["count"], 2),
            }

        domain_summary = {}
        for dom, d in by_domain.items():
            domain_summary[dom] = {
                "avg_rating": round(sum(d["ratings"]) / len(d["ratings"]), 1),
                "count": d["count"],
            }

        # 发现反复出现的负面模式
        recurring = []
        for cat, d in by_category.items():
            if d["negatives"] >= 3:
                examples = [
                    r.get("comment", "") for r in self._records
                    if r.get("category") == cat and r["rating"] <= 2
                ][:3]
                recurring.append({
                    "category": cat,
                    "negative_count": d["negatives"],
                    "examples": [e for e in examples if e],
                })

        # 生成改进候选
        improvement_candidates = []
        for r in recurring:
            improvement_candidates.append(
                f"在{r['category']}方面有{r['negative_count']}次负面反馈，"
                f"示例: {'; '.join(r['examples'][:2])}"
            )

        return {
            "total_feedback": total,
            "avg_rating": round(avg, 2),
            "by_category": category_summary,
            "by_domain": domain_summary,
            "recurring_negatives": recurring,
            "improvement_candidates": improvement_candidates,
        }

    def get_feedback_for_domain(self, domain: str) -> list[dict]:
        """获取某域的所有反馈"""
        return [r for r in self._records if r.get("domain") == domain]
