"""
Model Router — 任务感知的智能模型路由 (P1)

核心理念：不要固定模型，根据任务自动选择

路由策略：
  按任务复杂度分级：
    low: 简单总结、格式转换、简单问答 → 便宜模型
    medium: 一般分析、脚本生成、数据处理 → 中等模型
    high: 复杂推理、投资分析、架构设计 → 强模型

  按数据类型：
    批量图片生成 → 低成本图片模型
    核心封面图 → 高质量图片模型

  按成本优化：
    90%的图片只是背景 → 自动切换低成本
    最终质检 → 用强模型

  按历史效果：
    同类任务历史上模型A成功率85%，模型B成功率60% → 选A
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from .db import Database

logger = logging.getLogger(__name__)


class ModelRouter:
    """
    Model Router — 智能模型路由

    根据任务类型、复杂度、成本约束、历史效果选择最优模型
    """

    # 模型分级
    MODEL_TIERS = {
        "low_cost": {
            "glm-4-flash": {"provider": "zai", "cost_per_1k_tokens": 0.01, "quality": 60},
            "edge-tts": {"provider": "local", "cost_per_1k_tokens": 0, "quality": 50},
        },
        "mid_cost": {
            "glm-5.2": {"provider": "zai", "cost_per_1k_tokens": 0.05, "quality": 80},
            "deepseek-chat": {"provider": "deepseek", "cost_per_1k_tokens": 0.07, "quality": 82},
        },
        "high_cost": {
            "claude-sonnet-4": {"provider": "anthropic", "cost_per_1k_tokens": 0.30, "quality": 95},
            "gpt-4o": {"provider": "openai", "cost_per_1k_tokens": 0.25, "quality": 93},
        },
    }

    # 任务复杂度判断
    COMPLEXITY_INDICATORS = {
        "low": ["总结", "格式转换", "翻译", "提取", "列表", "格式化", "summarize", "format"],
        "high": ["分析", "诊断", "推理", "架构", "设计", "优化", "策略", "analyze", "design", "strategy"],
    }

    # 任务类型 → 推荐模型
    TASK_TYPE_ROUTING = {
        "investment": {
            "analysis": "mid_cost",
            "diagnosis": "high_cost",
            "report": "mid_cost",
            "data_fetch": "low_cost",
        },
        "video": {
            "script_creation": "high_cost",
            "image_generation": "mid_cost",
            "tts": "low_cost",
            "quality_check": "mid_cost",
        },
        "mlops": {
            "model_search": "low_cost",
            "deployment": "mid_cost",
            "evaluation": "high_cost",
        },
    }

    def __init__(self, db: Database, config: Optional[dict] = None):
        self.db = db
        self.config = config or {}
        self.routing_history: list[dict] = []

    def route(
        self,
        task_description: str,
        task_type: str = "general",
        subtask: Optional[str] = None,
        budget_cny: float = 5.0,
        quality_requirement: str = "medium",
    ) -> dict[str, Any]:
        """
        为任务选择最优模型

        Args:
            task_description: 任务描述
            task_type: 任务域 (investment/video/mlops/general)
            subtask: 子任务类型 (analysis/diagnosis/report/...)
            budget_cny: 预算约束
            quality_requirement: 质量要求 (low/medium/high)

        Returns:
            {
                "recommended_model": str,
                "tier": str,
                "provider": str,
                "estimated_cost": float,
                "reasoning": str,
                "alternatives": [str],
            }
        """
        # 1. 判断复杂度
        complexity = self._assess_complexity(task_description, quality_requirement)

        # 2. 确定模型层级
        tier = self._select_tier(task_type, subtask, complexity, budget_cny)

        # 3. 从层级中选择具体模型
        model_name, model_info = self._select_model_in_tier(tier, task_type)

        # 4. 估算成本
        estimated_cost = self._estimate_cost(model_info, task_description)

        # 5. 获取备选
        alternatives = list(self.MODEL_TIERS.get(tier, {}).keys())

        # 6. 历史效果参考
        perf = self._get_historical_performance(task_type, subtask)

        result = {
            "recommended_model": model_name,
            "tier": tier,
            "provider": model_info.get("provider", ""),
            "estimated_cost": estimated_cost,
            "complexity": complexity,
            "reasoning": self._build_reasoning(complexity, tier, task_type, subtask, perf),
            "alternatives": alternatives,
            "historical_performance": perf,
        }

        self.routing_history.append({
            **result,
            "task_description": task_description,
            "timestamp": datetime.now().isoformat(),
        })

        return result

    def _assess_complexity(self, task_desc: str, quality_req: str) -> str:
        """评估任务复杂度"""
        if quality_req == "high":
            return "high"
        if quality_req == "low":
            return "low"

        task_lower = task_desc.lower()
        high_score = sum(1 for kw in self.COMPLEXITY_INDICATORS["high"] if kw.lower() in task_lower)
        low_score = sum(1 for kw in self.COMPLEXITY_INDICATORS["low"] if kw.lower() in task_lower)

        if high_score > low_score:
            return "high"
        elif low_score > high_score:
            return "low"
        return "medium"

    def _select_tier(
        self, task_type: str, subtask: Optional[str],
        complexity: str, budget: float
    ) -> str:
        """选择模型层级"""
        # 先看任务类型路由
        if task_type in self.TASK_TYPE_ROUTING and subtask:
            routing = self.TASK_TYPE_ROUTING[task_type]
            if subtask in routing:
                tier = routing[subtask]
                # 预算检查
                if tier == "high_cost" and budget < 2.0:
                    return "mid_cost"
                return tier

        # 按复杂度路由
        complexity_to_tier = {
            "low": "low_cost",
            "medium": "mid_cost",
            "high": "high_cost",
        }
        tier = complexity_to_tier.get(complexity, "mid_cost")

        # 预算约束
        if tier == "high_cost" and budget < 2.0:
            return "mid_cost"
        if tier == "mid_cost" and budget < 0.5:
            return "low_cost"

        return tier

    def _select_model_in_tier(self, tier: str, task_type: str) -> tuple[str, dict]:
        """从层级中选择最优模型"""
        models = self.MODEL_TIERS.get(tier, {})
        if not models:
            # fallback
            return "glm-5.2", {"provider": "zai", "cost_per_1k_tokens": 0.05, "quality": 80}

        # 按历史效果选择
        best_model = None
        best_score = -1
        for name, info in models.items():
            perf = self._get_historical_performance(task_type, model_name=name)
            score = info.get("quality", 50)
            if perf and perf.get("success_rate", 0) > 0:
                score = perf["success_rate"] * 0.7 + score * 0.3
            if score > best_score:
                best_score = score
                best_model = name

        return best_model, models[best_model]

    def _estimate_cost(self, model_info: dict, task_desc: str) -> float:
        """估算成本"""
        cost_per_1k = model_info.get("cost_per_1k_tokens", 0.05)
        # 粗估token数
        estimated_tokens = max(len(task_desc) * 2, 500)
        return round(cost_per_1k * estimated_tokens / 1000, 4)

    def _get_historical_performance(
        self, task_type: str, subtask: Optional[str] = None, model_name: Optional[str] = None
    ) -> Optional[dict]:
        """查询历史路由效果"""
        matches = [
            r for r in self.routing_history
            if r.get("task_description", "").lower().find(task_type) >= 0
        ]
        if model_name:
            matches = [r for r in matches if r.get("recommended_model") == model_name]
        if not matches:
            return None
        return {
            "total_routes": len(matches),
            "success_rate": sum(1 for m in matches if m.get("estimated_cost", 0) < 5.0) / len(matches),
        }

    def _build_reasoning(
        self, complexity: str, tier: str, task_type: str,
        subtask: Optional[str], perf: Optional[dict]
    ) -> str:
        """构建路由决策理由"""
        reasons = [f"复杂度={complexity}→层级={tier}"]
        if task_type in self.TASK_TYPE_ROUTING and subtask:
            reasons.append(f"任务路由: {task_type}/{subtask}→{tier}")
        if perf:
            reasons.append(f"历史效果: {perf.get('success_rate', 0):.0%}成功率")
        return "; ".join(reasons)
