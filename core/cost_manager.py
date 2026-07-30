"""
Cost Manager — 成本控制器

统计每任务各模块 LLM/图像/TTS 消耗总费用。
Planner 依据预算约束，动态选择高/低成本模型方案。
"""

import json
import logging
from typing import Any, Optional

from .db import Database
from .registry import CapabilityRegistry

logger = logging.getLogger(__name__)

# ── 模型成本表（CNY per 1K tokens / per call）──
MODEL_COSTS: dict[str, dict[str, float]] = {
    # LLM（per 1K tokens: input + output）
    "glm-4-flash":      {"type": "llm", "input": 0.001, "output": 0.002, "unit": "1k_tokens"},
    "glm-5.2":          {"type": "llm", "input": 0.01, "output": 0.02, "unit": "1k_tokens"},
    "deepseek-chat":    {"type": "llm", "input": 0.001, "output": 0.002, "unit": "1k_tokens"},
    "claude-sonnet-4":  {"type": "llm", "input": 0.022, "output": 0.11, "unit": "1k_tokens"},
    "gpt-4o":           {"type": "llm", "input": 0.018, "output": 0.072, "unit": "1k_tokens"},
    # TTS（per 1K chars）
    "edge-tts":         {"type": "tts", "price": 0.0, "unit": "1k_chars"},
    "siliconflow-tts":  {"type": "tts", "price": 0.05, "unit": "1k_chars"},
    "volcano-tts":      {"type": "tts", "price": 0.10, "unit": "1k_chars"},
    # 图像（per call）
    "agnes-image":      {"type": "image", "price": 0.15, "unit": "call"},
    "dalle-3":          {"type": "image", "price": 0.30, "unit": "call"},
    "sd-xl":            {"type": "image", "price": 0.02, "unit": "call"},
}


class CostManager:
    """
    成本控制器

    职责:
    1. 计算单次能力调用的成本
    2. 累计任务总成本
    3. 预算检查（Planner 规划时）
    4. 模型选择建议（高/低成本方案）
    """

    def __init__(self, db: Database, registry: CapabilityRegistry):
        self.db = db
        self.registry = registry
        self._task_costs: dict[str, list[dict[str, Any]]] = {}  # task_id → [cost_entry]

    def calculate_step_cost(
        self, skill_name: str, tokens_used: int = 0, model: str = "",
        char_count: int = 0, call_count: int = 0
    ) -> dict[str, Any]:
        """计算单步成本"""
        cap = self.registry.get(skill_name)
        if not cap:
            return {"cost_cny": 0, "model": model, "breakdown": {}}

        # 优先用 SKILL.yaml 中的预估成本
        base_cost = cap["cost"].get("price_cny", 0)

        # 如果有实际token/调用数据，精确计算
        if model and model in MODEL_COSTS:
            model_info = MODEL_COSTS[model]
            if model_info["type"] == "llm" and tokens_used > 0:
                # 简化：input:output = 3:1
                input_tokens = int(tokens_used * 0.75)
                output_tokens = tokens_used - input_tokens
                actual_cost = (
                    input_tokens / 1000 * model_info["input"] +
                    output_tokens / 1000 * model_info["output"]
                )
                return {
                    "cost_cny": round(actual_cost, 4),
                    "model": model,
                    "breakdown": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "input_cost": round(input_tokens / 1000 * model_info["input"], 4),
                        "output_cost": round(output_tokens / 1000 * model_info["output"], 4),
                    }
                }
            elif model_info["type"] == "tts" and char_count > 0:
                actual_cost = char_count / 1000 * model_info["price"]
                return {
                    "cost_cny": round(actual_cost, 4),
                    "model": model,
                    "breakdown": {"char_count": char_count, "per_1k": model_info["price"]}
                }
            elif model_info["type"] == "image" and call_count > 0:
                actual_cost = call_count * model_info["price"]
                return {
                    "cost_cny": round(actual_cost, 4),
                    "model": model,
                    "breakdown": {"call_count": call_count, "per_call": model_info["price"]}
                }

        # 回退到 SKILL.yaml 预估值
        return {
            "cost_cny": base_cost,
            "model": model or "estimated",
            "breakdown": {"source": "skill_yaml_estimate"}
        }

    def record_step_cost(
        self, task_id: str, step_num: int, skill_name: str, cost_cny: float,
        tokens_used: int = 0, model: str = ""
    ):
        """记录单步成本"""
        entry = {
            "task_id": task_id,
            "step": step_num,
            "skill": skill_name,
            "cost_cny": cost_cny,
            "tokens_used": tokens_used,
            "model": model,
        }
        if task_id not in self._task_costs:
            self._task_costs[task_id] = []
        self._task_costs[task_id].append(entry)

    def get_task_cost(self, task_id: str) -> dict[str, Any]:
        """获取任务总成本"""
        entries = self._task_costs.get(task_id, [])
        total = sum(e["cost_cny"] for e in entries)
        by_skill: dict[str, float] = {}
        by_model: dict[str, float] = {}
        total_tokens = 0

        for e in entries:
            by_skill[e["skill"]] = by_skill.get(e["skill"], 0) + e["cost_cny"]
            by_model[e["model"]] = by_model.get(e["model"], 0) + e["cost_cny"]
            total_tokens += e["tokens_used"]

        return {
            "task_id": task_id,
            "total_cost_cny": round(total, 4),
            "total_tokens": total_tokens,
            "by_skill": {k: round(v, 4) for k, v in by_skill.items()},
            "by_model": {k: round(v, 4) for k, v in by_model.items()},
            "step_count": len(entries),
        }

    def check_budget(self, task_id: str, plan: dict[str, Any],
                     budget_cny: float = 5.0) -> dict[str, Any]:
        """
        检查计划是否在预算内。

        Returns:
            {
                "within_budget": bool,
                "estimated_cost": float,
                "budget": float,
                "recommendation": str
            }
        """
        est_cost = plan.get("estimated_cost_cny", 0)
        within = est_cost <= budget_cny

        recommendation = ""
        if not within:
            # 建议降级模型
            recommendation = self._suggest_cost_reduction(plan, est_cost, budget_cny)

        return {
            "within_budget": within,
            "estimated_cost": est_cost,
            "budget": budget_cny,
            "recommendation": recommendation,
        }

    def _suggest_cost_reduction(
        self, plan: dict[str, Any], est_cost: float, budget: float
    ) -> str:
        """生成成本优化建议"""
        over_ratio = est_cost / budget if budget > 0 else 1
        suggestions: list[str] = []

        if over_ratio > 2:
            suggestions.append("建议全部使用低成本模型（edge-tts + glm-4-flash）")
        elif over_ratio > 1.5:
            suggestions.append("建议混合方案：TTS用edge-tts，LLM用glm-4-flash")
        else:
            suggestions.append("建议部分步骤降级到低成本模型")

        suggestions.append(f"当前预估 ¥{est_cost:.2f}，预算 ¥{budget:.2f}")
        return " | ".join(suggestions)

    def recommend_model_tier(self, budget_cny: float, task_domain: str) -> dict[str, Any]:
        """
        根据预算推荐模型方案。

        Returns:
            { "tier": "low|mid|high", "llm": str, "tts": str, "image": str }
        """
        if budget_cny < 1.0:
            return {"tier": "low", "llm": "glm-4-flash", "tts": "edge-tts", "image": "sd-xl"}
        elif budget_cny < 5.0:
            return {"tier": "mid", "llm": "glm-5.2", "tts": "siliconflow-tts", "image": "agnes-image"}
        else:
            return {"tier": "high", "llm": "claude-sonnet-4", "tts": "volcano-tts", "image": "dalle-3"}
