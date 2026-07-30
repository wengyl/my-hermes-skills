"""
Multi-Agent Roles — 角色分工协作 (P2)

角色定义：
  Researcher: 查资料、找数据、找历史案例
  Analyst:    分析、建模、推理
  Writer:     输出、格式化
  Reviewer:   找漏洞、质检

每个角色：
  - 专属 system prompt（角色定位+行为约束）
  - 专属 toolset（限制可用工具）
  - 专属 knowledge（加载的参考知识）
  - 专属 model_tier（模型层级偏好）

与 Hermes delegate_task 集成：
  角色定义可直接作为 delegate_task 的参数
  goal + context + role → delegate_task
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── 角色定义 ──

AGENT_ROLES: dict[str, dict[str, Any]] = {
    "researcher": {
        "name": "Researcher",
        "description": "负责信息收集、数据获取、历史案例查找",
        "system_prompt": (
            "你是一个研究型Agent。你的职责是收集信息、查找数据、寻找历史案例。"
            "不要做分析或下结论——把原材料准备好交给Analyst。"
            "输出格式：结构化的数据+来源引用。"
        ),
        "preferred_tools": ["web", "search", "file", "terminal"],
        "knowledge_focus": ["best_practices", "known_failures"],
        "model_tier": "low_cost",
        "quality_focus": "completeness",
    },
    "analyst": {
        "name": "Analyst",
        "description": "负责分析、建模、推理、决策建议",
        "system_prompt": (
            "你是一个分析型Agent。你的职责是对Researcher收集的数据进行分析、建模、推理。"
            "给出有数据支撑的结论和建议，不要做文字输出格式化——交给Writer。"
            "输出格式：分析结论+数据支撑+置信度标注。"
        ),
        "preferred_tools": ["file", "code_execution", "terminal"],
        "knowledge_focus": ["best_practices", "workflow_patterns"],
        "model_tier": "high_cost",
        "quality_focus": "accuracy",
    },
    "writer": {
        "name": "Writer",
        "description": "负责输出格式化、报告撰写、文档生成",
        "system_prompt": (
            "你是一个写作型Agent。你的职责是将Analyst的分析结论格式化为用户可读的报告。"
            "关注表达清晰、结构合理、语言自然。不要添加新的分析内容。"
            "输出格式：结构化报告/文档。"
        ),
        "preferred_tools": ["file"],
        "knowledge_focus": ["best_practices"],
        "model_tier": "mid_cost",
        "quality_focus": "readability",
    },
    "reviewer": {
        "name": "Reviewer",
        "description": "负责找漏洞、质检、对抗性审查",
        "system_prompt": (
            "你是一个审查型Agent。你的职责是审查Analyst和Writer的输出，找出漏洞、错误、遗漏。"
            "以批判性视角审查：数据准确吗？推理逻辑通吗？结论可靠吗？格式规范吗？"
            "输出格式：问题清单+严重程度+修复建议。"
        ),
        "preferred_tools": ["file", "web", "search"],
        "knowledge_focus": ["known_failures", "best_practices"],
        "model_tier": "high_cost",
        "quality_focus": "critique_quality",
    },
}


class MultiAgentCoordinator:
    """
    多角色协调器

    管理角色分工、任务分配、结果汇总
    """

    def __init__(self, model_router=None):
        self.model_router = model_router
        self.roles = AGENT_ROLES

    def get_role_config(self, role: str) -> dict[str, Any]:
        """获取角色配置"""
        return self.roles.get(role, self.roles["researcher"])

    def plan_role_assignment(
        self, goal: str, domain: str, complexity: str = "medium"
    ) -> list[dict[str, Any]]:
        """
        根据目标自动分配角色任务

        Returns:
            [{role, task_goal, context_hint, model_tier, tools}]
        """
        assignments: list[dict[str, Any]] = []

        # 复杂任务 → 4角色全上
        if complexity == "high":
            assignments = [
                {
                    "role": "researcher",
                    "task_goal": f"收集以下任务所需的资料和数据: {goal}",
                    "context_hint": f"领域: {domain}",
                    "model_tier": self.roles["researcher"]["model_tier"],
                },
                {
                    "role": "analyst",
                    "task_goal": f"基于研究结果进行分析: {goal}",
                    "context_hint": f"领域: {domain}, 参考researcher输出",
                    "model_tier": self.roles["analyst"]["model_tier"],
                },
                {
                    "role": "writer",
                    "task_goal": f"将分析结论格式化为最终报告: {goal}",
                    "context_hint": f"领域: {domain}, 参考analyst输出",
                    "model_tier": self.roles["writer"]["model_tier"],
                },
                {
                    "role": "reviewer",
                    "task_goal": f"审查最终报告的质量: {goal}",
                    "context_hint": f"领域: {domain}, 审查writer输出",
                    "model_tier": self.roles["reviewer"]["model_tier"],
                },
            ]
        elif complexity == "medium":
            # 中等 → Researcher + Analyst(兼Writer) + Reviewer
            assignments = [
                {
                    "role": "researcher",
                    "task_goal": f"收集资料: {goal}",
                    "context_hint": f"领域: {domain}",
                    "model_tier": self.roles["researcher"]["model_tier"],
                },
                {
                    "role": "analyst",
                    "task_goal": f"分析并输出结论: {goal}",
                    "context_hint": f"领域: {domain}, 参考researcher输出, 同时负责格式化输出",
                    "model_tier": self.roles["analyst"]["model_tier"],
                },
                {
                    "role": "reviewer",
                    "task_goal": f"审查输出质量: {goal}",
                    "context_hint": f"领域: {domain}",
                    "model_tier": self.roles["reviewer"]["model_tier"],
                },
            ]
        else:
            # 简单 → 单角色
            assignments = [
                {
                    "role": "analyst",
                    "task_goal": goal,
                    "context_hint": f"领域: {domain}",
                    "model_tier": self.roles["analyst"]["model_tier"],
                }
            ]

        return assignments

    def get_delegate_context(
        self, role: str, task_goal: str, domain: str,
        prior_results: Optional[list[dict]] = None
    ) -> str:
        """
        为 delegate_task 生成角色化的 context

        将角色定义 + 任务 + 前序结果组合为 context 字符串
        """
        role_config = self.get_role_config(role)

        context_parts = [
            f"角色: {role_config['name']}",
            f"职责: {role_config['description']}",
            f"行为约束: {role_config['system_prompt']}",
            f"质量关注: {role_config['quality_focus']}",
        ]

        if prior_results:
            context_parts.append("\n前序角色输出:")
            for pr in prior_results:
                context_parts.append(
                    f"  [{pr['role']}]: {json.dumps(pr.get('summary', ''), ensure_ascii=False)[:200]}"
                )

        context_parts.append(f"\n任务: {task_goal}")

        return "\n".join(context_parts)
