"""
Knowledge Bridge — Hermes 原生能力增强接口

这是增强层与 Hermes 原生能力的桥梁。

核心理念：
  不替代 Hermes 的 Skill / Memory / Planner / Learning
  而是为它们提供结构化的知识供给和评估反馈

提供的接口：
  1. get_planning_context(goal) → 为 Hermes Agent 提供规划增强上下文
  2. get_skill_context(domain) → 为 Hermes Skill 加载提供最佳实践参考
  3. get_failure_context(skill_name) → 为 Hermes 提供已知失败模式供规避
  4. reflect_on_task(...) → 任务后反思，沉淀经验知识
  5. ingest_knowledge(memo) → 知识inbox入口
  6. export_for_hermes() → 导出为 Hermes 可读格式（SKILL.md references）
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from .db import Database
from .registry import CapabilityRegistry
from .memory import MemorySubsystem
from .reflection import ReflectionEngine
from .knowledge_curator import KnowledgeCurator

logger = logging.getLogger(__name__)


class KnowledgeBridge:
    """
    Hermes 增强层桥接器

    连接增强层 (Knowledge + Reflection + Evaluation) 与 Hermes 原生能力 (Skills + Memory + Tools)
    """

    def __init__(
        self,
        db: Database,
        registry: CapabilityRegistry,
        memory: MemorySubsystem,
        reflection: ReflectionEngine,
        curator: KnowledgeCurator,
        knowledge_dir: str = "knowledge",
    ):
        self.db = db
        self.registry = registry
        self.memory = memory
        self.reflection = reflection
        self.curator = curator
        self.knowledge_dir = Path(knowledge_dir)

    def get_planning_context(self, goal: str, domain: Optional[str] = None) -> dict[str, Any]:
        """
        为 Hermes Agent 的规划阶段提供增强上下文

        返回 Hermes Agent 在规划任务时应参考的结构化知识：
          - domain: 识别的业务域
          - workflow_pattern: 标准工作流模板
          - best_practices: 该域的最佳实践规则
          - known_failures: 已知失败模式（供规划阶段规避）
          - user_preferences: 用户偏好
          - recent_best_cases: 最近的成功案例参考
          - available_capabilities: 可用原子能力清单
        """
        # 识别域
        if not domain:
            domain = self._identify_domain(goal)

        context: dict[str, Any] = {
            "domain": domain,
            "goal": goal,
            "workflow_pattern": self._load_workflow_pattern(domain),
            "best_practices": self._load_best_practices(domain),
            "known_failures": self._load_known_failures(domain),
            "user_preferences": self._get_user_preferences(),
            "recent_best_cases": self._get_recent_cases(domain),
            "available_capabilities": self._get_capabilities_summary(domain),
        }

        logger.info(f"Planning context generated for domain={domain}")
        return context

    def get_skill_context(self, domain: str) -> dict[str, Any]:
        """
        为 Hermes Skill 加载提供参考知识

        当 Hermes 加载一个领域 Skill 时，可以同时加载该域的：
          - best_practices (方法论约束)
          - common_failures (已知坑)
          - workflow_patterns (标准流程)
        """
        return {
            "best_practices": self._load_best_practices(domain),
            "common_failures": self._load_known_failures(domain),
            "workflow_pattern": self._load_workflow_pattern(domain),
        }

    def get_failure_context(self, skill_name: str) -> list[dict[str, Any]]:
        """
        为 Hermes Agent 提供特定技能的已知失败模式

        Hermes 在执行某技能前可以查询此接口，了解历史上该技能的常见失败
        """
        patterns = self.memory.get_failure_patterns(skill_name)
        return [
            {
                "defect_pattern": p["defect_pattern"],
                "occurrence_count": p["count"],
                "solution": p.get("solution"),
                "last_seen": p.get("last_seen", ""),
            }
            for p in patterns
        ]

    def reflect_on_task(
        self,
        task_id: str,
        goal: str,
        plan: dict[str, Any],
        exec_result: dict[str, Any],
        eval_result: dict[str, Any],
        repair_result: Optional[dict] = None,
        user_feedback: Optional[dict] = None,
    ) -> dict[str, Any]:
        """任务后反思接口 — 代理调用 ReflectionEngine"""
        return self.reflection.reflect(
            task_id, goal, plan, exec_result, eval_result,
            repair_result, user_feedback
        )

    def ingest_knowledge(self, memo: str, source: str = "user") -> dict[str, Any]:
        """知识inbox入口 — 代理调用 KnowledgeCurator"""
        return self.curator.ingest_memo(memo, source)

    def export_for_hermes(self, domain: str) -> dict[str, Any]:
        """
        导出领域知识为 Hermes 可读格式

        生成内容可直接被 Hermes Skill 的 references/ 目录引用：
          - best_practices.md (markdown格式最佳实践)
          - common_failures.md (markdown格式失败案例)
          - workflow.md (markdown格式工作流模板)
        """
        export: dict[str, Any] = {
            "domain": domain,
            "best_practices_md": self._export_best_practices_md(domain),
            "common_failures_md": self._export_common_failures_md(domain),
            "workflow_md": self._export_workflow_md(domain),
        }
        return export

    def export_to_skill_references(self, domain: str, output_dir: str = "skills"):
        """
        将知识导出为 Hermes Skill 的 references/ 文件

        这样 Hermes 原生 Skill 可以直接引用增强层积累的知识
        """
        out = Path(output_dir) / domain / "references"
        out.mkdir(parents=True, exist_ok=True)

        # best_practices.md
        bp_md = self._export_best_practices_md(domain)
        if bp_md:
            (out / "best_practices.md").write_text(bp_md, encoding="utf-8")

        # common_failures.md
        fail_md = self._export_common_failures_md(domain)
        if fail_md:
            (out / "common_failures.md").write_text(fail_md, encoding="utf-8")

        # workflow.md
        wf_md = self._export_workflow_md(domain)
        if wf_md:
            (out / "workflow.md").write_text(wf_md, encoding="utf-8")

        logger.info(f"Knowledge exported to {out}")
        return str(out)

    # ── 私有方法：知识文件加载 ──

    def _identify_domain(self, goal: str) -> str:
        """从目标识别业务域（复用Planner的逻辑）"""
        goal_lower = goal.lower()
        domain_keywords = {
            "video": ["视频", "讲解视频", "文档转视频", "AI视频", "配音", "字幕", "TTS", "视频工厂"],
            "mlops": ["模型", "训练", "微调", "fine-tune", "部署模型", "推理服务", "vllm", "llama.cpp", "huggingface", "量化"],
            "investment": ["基金", "投资", "组合", "持仓", "调仓", "净值", "估值", "诊断", "收益率", "回撤"],
        }
        scores = {}
        for d, kws in domain_keywords.items():
            scores[d] = sum(1 for kw in kws if kw.lower() in goal_lower)
        return max(scores, key=scores.get) if any(scores.values()) else "general"

    def _load_best_practices(self, domain: str) -> list[dict[str, Any]]:
        bp_dir = self.knowledge_dir / "best_practices" / domain
        if not bp_dir.exists():
            return []
        results = []
        for f in sorted(bp_dir.glob("*.yaml")):
            with open(f, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if data:
                    results.append(data)
        return results

    def _load_known_failures(self, domain: str) -> list[dict[str, Any]]:
        fail_file = self.knowledge_dir / "failures" / domain / "common_failures.yaml"
        if not fail_file.exists():
            return []
        with open(fail_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("failures", []) if data else []

    def _load_workflow_pattern(self, domain: str) -> Optional[dict[str, Any]]:
        pat_dir = self.knowledge_dir / "patterns" / domain
        if not pat_dir.exists():
            return None
        for f in sorted(pat_dir.glob("*.yaml")):
            with open(f, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh)
        return None

    def _get_user_preferences(self) -> list[dict[str, Any]]:
        return self.memory.get_user_preferences()

    def _get_recent_cases(self, domain: str, limit: int = 3) -> list[dict[str, Any]]:
        cases_file = self.knowledge_dir / "cases" / "index.yaml"
        if not cases_file.exists():
            return []
        # cases/index.yaml 使用 --- 分隔多文档
        content = cases_file.read_text(encoding="utf-8")
        docs = list(yaml.safe_load_all(content))
        domain_cases = [d for d in docs if d and d.get("domain") == domain]
        return domain_cases[:limit]

    def _get_capabilities_summary(self, domain: str) -> dict[str, Any]:
        caps = self.registry.query(domain=domain)
        return {
            "total": len(caps),
            "capabilities": [{"name": c["name"], "description": c["description"]} for c in caps],
        }

    # ── 私有方法：Markdown 导出 ──

    def _export_best_practices_md(self, domain: str) -> str:
        practices = self._load_best_practices(domain)
        if not practices:
            return ""
        lines = [f"# Best Practices: {domain}\n"]
        for bp in practices:
            lines.append(f"## {bp.get('id', 'unnamed')}")
            lines.append(f"- **When**: {bp.get('when', 'N/A')}")
            lines.append(f"- **Confidence**: {bp.get('confidence', 0)}\n")
            lines.append("**Rules:**\n")
            for rule in bp.get("rules", []):
                enforcement = rule.get("enforcement", "soft")
                marker = "🔴 HARD" if enforcement == "hard" else "🟡 SOFT"
                lines.append(f"- [{marker}] {rule.get('rule', '')}")
                if rule.get("reason"):
                    lines.append(f"  - Reason: {rule['reason']}")
            lines.append("")
        return "\n".join(lines)

    def _export_common_failures_md(self, domain: str) -> str:
        failures = self._load_known_failures(domain)
        if not failures:
            return ""
        lines = [f"# Common Failures: {domain}\n"]
        for fail in failures:
            status = "✅" if fail.get("status") == "resolved" else "⚠️"
            lines.append(f"## {status} {fail.get('id', 'N/A')}: {fail.get('pattern', '')}")
            lines.append(f"- **Skill**: {fail.get('skill', '')}")
            lines.append(f"- **Root Cause**: {fail.get('root_cause', 'unknown')}")
            lines.append(f"- **Solution**: {fail.get('solution', 'pending')}")
            lines.append(f"- **Occurrences**: {fail.get('occurrence_count', 0)}\n")
        return "\n".join(lines)

    def _export_workflow_md(self, domain: str) -> str:
        pattern = self._load_workflow_pattern(domain)
        if not pattern:
            return ""
        lines = [f"# Workflow Pattern: {pattern.get('pattern_name', domain)}\n"]
        lines.append(f"**Description**: {pattern.get('description', '')}\n")
        for phase in pattern.get("phases", []):
            lines.append(f"## Phase {phase.get('phase', '?')}: {phase.get('name', '')}")
            if "steps" in phase:
                for step in phase["steps"]:
                    lines.append(f"1. {step}")
            if "parallel" in phase:
                for branch in phase["parallel"]:
                    lines.append(f"\n### Branch: {branch.get('branch', '')}")
                    for step in branch.get("steps", []):
                        lines.append(f"1. {step}")
            if phase.get("best_practice_ref"):
                lines.append(f"\n> 📋 Best Practice: {phase['best_practice_ref']}")
            lines.append("")
        return "\n".join(lines)
