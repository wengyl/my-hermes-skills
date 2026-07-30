"""
Planner Agent — 目标解析 + 能力匹配 + 执行计划生成

接收用户最终目标 → 解析所需能力集合 → 匹配 CapabilityRegistry →
生成标准化 JSON 执行计划（目标描述 + 有序 step 列表）

执行计划格式:
{
    "goal": "用户目标描述",
    "domain": "video|mlops|investment|general",
    "steps": [
        {
            "step": 1,
            "skill": "script.create",
            "input_mapping": { ... },   # 上一步输出到本步输入的映射
            "parallel_with": null,      # 可并行执行的step编号
            "evaluation_required": true # 是否需要评估
        }
    ],
    "estimated_cost_cny": 0.50,
    "estimated_tokens": 8000
}
"""

import json
import logging
import re
from typing import Any, Optional

from .registry import CapabilityRegistry
from .state_machine import TaskStateMachine

logger = logging.getLogger(__name__)

# ── 领域识别关键词 ──
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "video": [
        "视频", "讲解视频", "文档转视频", "文章转视频", "AI视频",
        "分镜", "配音", "字幕", "TTS", "FFmpeg", "视频工厂",
        "explainer", "video factory"
    ],
    "mlops": [
        "模型", "训练", "微调", "fine-tune", "部署模型", "推理服务",
        "vllm", "llama.cpp", "ollama", "benchmark", "huggingface",
        "数据集", "gguf", "量化"
    ],
    "investment": [
        "基金", "投资", "组合", "持仓", "调仓", "净值", "估值",
        "诊断", "收益率", "回撤", "行情", "市场", "半导体", "GPU"
    ],
    "general": []  # 兜底
}

# ── 领域 → 标准能力链 ──
DOMAIN_PIPELINES: dict[str, list[str]] = {
    "video": [
        "script.create",
        "script.review",
        "storyboard.create",
        "scene.plan",
        "image.generate",       # 依赖 scene.plan + storyboard.create
        "image.evaluate",
        "voice.generate",       # 可与 image.generate 并行
        "voice.align",
        "subtitle.generate",
        "video.compose",
        "video.evaluate",
    ],
    "mlops": [
        "model.search",
        "model.load",
        "model.evaluate",
        "model.serve",
    ],
    "investment": [
        "data.fetch",
        "portfolio.analyze",
        "fund.diagnose",
        "strategy.generate",
        "report.generate",
    ],
}


class PlannerAgent:
    """
    Planner Agent — 接收用户目标，生成标准化执行计划。

    职责:
    1. 识别任务领域（video/mlops/investment/general）
    2. 匹配所需原子能力集合
    3. 构建有序执行计划（含并行标记和输入映射）
    4. 预估成本和Token消耗
    """

    def __init__(self, registry: CapabilityRegistry, sm: TaskStateMachine):
        self.registry = registry
        self.sm = sm

    def identify_domain(self, goal: str) -> str:
        """从用户目标识别业务域"""
        goal_lower = goal.lower()
        scores: dict[str, int] = {}

        for domain, keywords in DOMAIN_KEYWORDS.items():
            if domain == "general":
                continue
            score = sum(1 for kw in keywords if kw.lower() in goal_lower)
            scores[domain] = score

        best_domain = max(scores, key=scores.get) if scores else "general"
        if scores.get(best_domain, 0) == 0:
            return "general"
        return best_domain

    def match_capabilities(self, goal: str, domain: str) -> list[str]:
        """
        匹配所需原子能力。
        先用领域标准流水线，再用关键词从注册表补充。
        """
        # 1. 获取领域标准流水线
        pipeline = DOMAIN_PIPELINES.get(domain, [])

        # 2. 从注册表验证所有能力存在
        matched: list[str] = []
        for name in pipeline:
            cap = self.registry.get(name)
            if cap:
                matched.append(name)
            else:
                logger.warning(f"Pipeline capability not in registry: {name}")

        # 3. 关键词匹配补充（如果标准流水线不完整）
        if not matched:
            # 兜底：查询该域全部能力
            caps = self.registry.query(domain=domain)
            matched = [c["name"] for c in caps]

        return matched

    def build_input_mappings(
        self, skill_names: list[str], goal: str
    ) -> list[dict[str, Any]]:
        """
        为每个step构建输入映射。

        规则:
        - 第一个step的输入来自用户原始目标
        - 后续step的输入来自前序step的输出
        - 依赖感知：如果一个能力依赖另一个能力的输出，正确映射
        """
        steps: list[dict[str, Any]] = []

        for i, name in enumerate(skill_names):
            cap = self.registry.get(name)
            if not cap:
                continue

            step: dict[str, Any] = {
                "step": i + 1,
                "skill": name,
                "description": cap["description"],
                "evaluation_required": cap["evaluation"]["type"] != "none",
                "parallel_with": None,
                "input_mapping": {}
            }

            # 第一个step：输入来自用户目标
            if i == 0:
                step["input_mapping"]["_source"] = "user_goal"
                step["input_mapping"]["goal"] = goal
            else:
                # 后续step：从前序输出映射
                step["input_mapping"]["_source"] = "previous_steps"

                # 根据依赖关系确定输入来源
                deps = cap.get("dependencies", [])
                if deps:
                    # 使用直接依赖的输出
                    step["input_mapping"]["_depends_on"] = deps
                else:
                    # 无显式依赖，使用前一个step
                    step["input_mapping"]["_depends_on"] = [skill_names[i - 1]]

            steps.append(step)

        # 标记可并行步骤
        # 简化规则：同一step中如果有多个无依赖关系的能力，标记并行
        # 视频域：image.generate 和 voice.generate 可并行
        for i, step in enumerate(steps):
            skill = step["skill"]
            if skill == "voice.generate":
                # voice.generate 和 image.generate 可并行
                for j, s in enumerate(steps):
                    if s["skill"] == "image.generate":
                        step["parallel_with"] = s["step"]
                        break

        return steps

    def estimate_cost(self, skill_names: list[str]) -> tuple[float, int]:
        """预估总成本（CNY）和Token消耗"""
        total_cost = 0.0
        total_tokens = 0
        for name in skill_names:
            cap = self.registry.get(name)
            if cap:
                total_cost += cap["cost"].get("price_cny", 0)
                total_tokens += cap["cost"].get("token_estimate", 0)
        return round(total_cost, 2), total_tokens

    def plan(self, task_id: str, goal: str) -> dict[str, Any]:
        """
        生成完整执行计划。

        Args:
            task_id: 任务ID
            goal: 用户目标描述

        Returns:
            标准化执行计划 JSON
        """
        # 1. 识别领域
        domain = self.identify_domain(goal)
        logger.info(f"Task {task_id}: domain={domain}, goal={goal[:60]}...")

        # 2. 匹配能力
        skill_names = self.match_capabilities(goal, domain)

        # 3. 拓扑排序
        ordered = self.registry.get_execution_order(skill_names)

        # 4. 构建步骤
        steps = self.build_input_mappings(ordered, goal)

        # 5. 预估成本
        est_cost, est_tokens = self.estimate_cost(ordered)

        plan: dict[str, Any] = {
            "task_id": task_id,
            "goal": goal,
            "domain": domain,
            "steps": steps,
            "estimated_cost_cny": est_cost,
            "estimated_tokens": est_tokens,
            "total_steps": len(steps),
            "version": "1.0"
        }

        # 6. 持久化计划
        self.sm.set_plan(task_id, plan)

        return plan

    def replan(
        self, task_id: str, goal: str, failed_step: int, defects: list[str],
        original_plan: dict[str, Any]
    ) -> dict[str, Any]:
        """
        重新规划（Repair Agent 调用）。

        在失败步骤处插入修复步骤，保留前后计划不变。
        """
        steps = original_plan["steps"].copy()

        # 找到失败步骤
        failed_skill = steps[failed_step - 1]["skill"]

        # 查找修复能力（同域 evaluation 类别的能力）
        repair_caps = self.registry.query(
            domain=original_plan["domain"],
            category="repair"
        )

        # 如果没有显式修复能力，直接重试该步骤
        if not repair_caps:
            # 标记重试
            steps[failed_step - 1]["retry"] = True
            steps[failed_step - 1]["defects"] = defects
        else:
            # 插入修复步骤
            repair_step: dict[str, Any] = {
                "step": failed_step + 0.5,  # 插入在失败步骤之后
                "skill": repair_caps[0]["name"],
                "description": f"修复 {failed_skill} 的缺陷",
                "evaluation_required": False,
                "parallel_with": None,
                "input_mapping": {
                    "_source": "previous_step",
                    "_depends_on": [failed_skill],
                    "defects": defects
                }
            }
            steps.insert(failed_step, repair_step)

        # 重新编号
        for i, s in enumerate(steps):
            s["step"] = i + 1

        new_plan = original_plan.copy()
        new_plan["steps"] = steps
        new_plan["repair_count"] = new_plan.get("repair_count", 0) + 1

        # 持久化
        self.sm.transition(task_id, "planning",
                           plan_json=json.dumps(new_plan, ensure_ascii=False),
                           total_steps=len(steps))

        return new_plan
