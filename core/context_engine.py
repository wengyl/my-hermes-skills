"""
Context Engine — 动态上下文组装引擎 (P0)

核心理念：不是模型不聪明，而是给它的信息不对。

与 KnowledgeBridge 的区别：
  KnowledgeBridge 提供"有什么知识"（静态供给）
  Context Engine 解决"这次任务该带什么"（动态组装）

组装层次（由近到远）：
  L0: 当前任务描述 (goal + user_input)
  L1: 领域知识 (best_practices + workflow_patterns + known_failures)
  L2: 历史经验 (recent_cases + skill_stats + reflection_lessons)
  L3: 用户画像 (preferences + risk_profile + style_preferences)
  L4: 环境约束 (budget + time_limit + model_constraints + permissions)
  L5: 实时上下文 (market_state + active_goals + recent_journal)

输出格式：
  一个结构化的 context payload，可直接注入到 Hermes Agent 的 system prompt
  或作为 delegate_task 的 context 参数

关键特性：
  - 上下文窗口预算管理：按token估算裁剪，优先保留高信号信息
  - 动态权重：根据任务类型调整各层权重（投资任务加重market_state，视频任务加重style）
  - 去重：跨层去重相同信息
  - 时效性：标注信息新鲜度，过期信息降权
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

from .db import Database
from .registry import CapabilityRegistry
from .memory import MemorySubsystem
from .knowledge_bridge import KnowledgeBridge

logger = logging.getLogger(__name__)


class ContextEngine:
    """
    Context Engine — 动态上下文组装引擎

    每次任务执行前调用 build_context(goal, user_input) 获取最优上下文
    """

    # 上下文层定义
    LAYERS = {
        "L0_task": {"priority": 100, "max_tokens": 500, "always_include": True},
        "L1_domain": {"priority": 90, "max_tokens": 2000},
        "L2_history": {"priority": 80, "max_tokens": 1500},
        "L3_user": {"priority": 85, "max_tokens": 800},
        "L4_constraints": {"priority": 70, "max_tokens": 300},
        "L5_realtime": {"priority": 75, "max_tokens": 1000},
    }

    # 任务类型 → 层权重调整
    TASK_TYPE_WEIGHTS = {
        "investment": {"L1_domain": 1.3, "L3_user": 1.2, "L5_realtime": 1.5},
        "video": {"L1_domain": 1.4, "L3_user": 1.1, "L5_realtime": 0.5},
        "mlops": {"L1_domain": 1.2, "L4_constraints": 1.3},
        "general": {},
    }

    def __init__(
        self,
        db: Database,
        registry: CapabilityRegistry,
        memory: MemorySubsystem,
        bridge: KnowledgeBridge,
        knowledge_dir: str = "knowledge",
    ):
        self.db = db
        self.registry = registry
        self.memory = memory
        self.bridge = bridge
        self.knowledge_dir = Path(knowledge_dir)

    def build_context(
        self,
        goal: str,
        user_input: Optional[dict] = None,
        budget_cny: float = 5.0,
        time_limit_s: int = 300,
        model_constraint: Optional[str] = None,
        active_goals: Optional[list] = None,
    ) -> dict[str, Any]:
        """
        为一次任务执行组装最优上下文

        Args:
            goal: 用户目标描述
            user_input: 用户原始输入参数
            budget_cny: 预算上限
            time_limit_s: 时间限制（秒）
            model_constraint: 模型约束（如指定使用某模型）
            active_goals: 当前活跃的长期目标列表

        Returns:
            {
                "task_type": str,
                "domain": str,
                "layers": {
                    "L0_task": {...},
                    "L1_domain": {...},
                    "L2_history": {...},
                    "L3_user": {...},
                    "L4_constraints": {...},
                    "L5_realtime": {...},
                },
                "assembled_prompt": str,  # 可直接注入的上下文文本
                "token_estimate": int,
                "metadata": {
                    "budget_cny": float,
                    "time_limit_s": int,
                    "freshness": {...},
                }
            }
        """
        # 识别任务类型
        domain = self.bridge._identify_domain(goal)
        task_type = domain  # investment / video / mlops / general

        # 获取层权重
        weights = self.TASK_TYPE_WEIGHTS.get(task_type, {})

        # ── 逐层组装 ──
        layers: dict[str, Any] = {}

        # L0: 当前任务
        layers["L0_task"] = self._build_task_layer(goal, user_input)

        # L1: 领域知识
        layers["L1_domain"] = self._build_domain_layer(domain, weights.get("L1_domain", 1.0))

        # L2: 历史经验
        layers["L2_history"] = self._build_history_layer(domain, weights.get("L2_history", 1.0))

        # L3: 用户画像
        layers["L3_user"] = self._build_user_layer(domain, weights.get("L3_user", 1.0))

        # L4: 约束条件
        layers["L4_constraints"] = self._build_constraints_layer(
            budget_cny, time_limit_s, model_constraint,
            weights.get("L4_constraints", 1.0)
        )

        # L5: 实时上下文
        layers["L5_realtime"] = self._build_realtime_layer(
            domain, active_goals, weights.get("L5_realtime", 1.0)
        )

        # ── 去重 ──
        layers = self._deduplicate(layers)

        # ── 组装为prompt文本 ──
        assembled_prompt = self._assemble_prompt(layers, task_type)

        # ── Token估算 ──
        token_estimate = self._estimate_tokens(assembled_prompt)

        # ── 新鲜度标注 ──
        freshness = self._compute_freshness(layers)

        return {
            "task_type": task_type,
            "domain": domain,
            "layers": layers,
            "assembled_prompt": assembled_prompt,
            "token_estimate": token_estimate,
            "metadata": {
                "budget_cny": budget_cny,
                "time_limit_s": time_limit_s,
                "model_constraint": model_constraint,
                "freshness": freshness,
                "weights_applied": weights,
            },
        }

    def _build_task_layer(self, goal: str, user_input: Optional[dict]) -> dict:
        """L0: 当前任务描述"""
        return {
            "goal": goal,
            "user_input": user_input or {},
            "timestamp": datetime.now().isoformat(),
        }

    def _build_domain_layer(self, domain: str, weight: float) -> dict:
        """L1: 领域知识（best_practices + workflow + known_failures）"""
        skill_ctx = self.bridge.get_skill_context(domain)

        # 按权重裁剪
        practices = skill_ctx.get("best_practices", [])
        if weight < 1.0 and practices:
            # 只保留高置信度规则
            practices = [bp for bp in practices if bp.get("confidence", 0) >= 0.85]

        failures = skill_ctx.get("common_failures", [])
        if weight < 1.0 and failures:
            # 只保留未解决的失败（更紧急）
            failures = [f for f in failures if f.get("status") != "resolved"]

        return {
            "best_practices": practices,
            "known_failures": failures,
            "workflow_pattern": skill_ctx.get("workflow_pattern"),
        }

    def _build_history_layer(self, domain: str, weight: float) -> dict:
        """L2: 历史经验（recent_cases + skill_stats + reflection_lessons）"""
        layer: dict[str, Any] = {}

        # 最近成功案例
        cases = self.bridge._get_recent_cases(domain, limit=3)
        layer["recent_cases"] = cases[:2] if weight < 1.0 else cases

        # 技能运行统计
        caps = self.registry.query(domain=domain)
        skill_stats = {}
        for cap in caps[:5]:  # top 5 capabilities
            stats = self.memory.get_skill_summary(cap["name"])
            if stats["total_runs"] > 0:
                skill_stats[cap["name"]] = stats
        layer["skill_stats"] = skill_stats

        # 反思教训
        reflections = self.db.search_memory(mem_type="reflection", limit=5)
        lessons = []
        for r in reflections:
            value = r.get("value", {})
            if value.get("domain") == domain or domain == "general":
                lessons.extend(value.get("lessons_learned", []))
        layer["reflection_lessons"] = lessons[:5] if weight < 1.0 else lessons[:10]

        return layer

    def _build_user_layer(self, domain: str, weight: float) -> dict:
        """L3: 用户画像（preferences + risk_profile + style）"""
        prefs = self.memory.get_user_preferences()

        # 过滤与当前域相关的偏好
        domain_prefs = []
        general_prefs = []
        for p in prefs:
            value = p.get("value", {})
            if isinstance(value, dict):
                p_domain = value.get("domain", "general")
                if p_domain == domain:
                    domain_prefs.append(value)
                elif p_domain == "general":
                    general_prefs.append(value)
            else:
                general_prefs.append({"value": value})

        return {
            "domain_preferences": domain_prefs[:5],
            "general_preferences": general_prefs[:3],
        }

    def _build_constraints_layer(
        self, budget: float, time_limit: int,
        model: Optional[str], weight: float
    ) -> dict:
        """L4: 约束条件"""
        constraints: dict[str, Any] = {
            "budget_cny": budget,
            "time_limit_s": time_limit,
        }
        if model:
            constraints["model_constraint"] = model

        # 权限约束
        constraints["permissions"] = {
            "can_write_files": True,
            "can_execute_commands": True,
            "can_send_messages": False,  # 需要显式授权
            "can_modify_database": False,  # 需要显式授权
            "can_trade": False,  # 金融交易需要显式确认
        }

        return constraints

    def _build_realtime_layer(
        self, domain: str, active_goals: Optional[list],
        weight: float
    ) -> dict:
        """L5: 实时上下文（活跃目标 + 最近日志）"""
        layer: dict[str, Any] = {}

        # 活跃长期目标
        if active_goals:
            layer["active_goals"] = active_goals

        # 最近任务（从DB查最近5个任务）
        recent_tasks = self.db.list_tasks(limit=5)
        layer["recent_tasks"] = [
            {"task_id": t["task_id"], "goal": t["goal"], "state": t["state"]}
            for t in recent_tasks[:3]
        ]

        return layer

    def _deduplicate(self, layers: dict) -> dict:
        """跨层去重"""
        seen_texts: set[str] = set()

        for layer_name, layer_data in layers.items():
            if not isinstance(layer_data, dict):
                continue

            for key, value in list(layer_data.items()):
                if isinstance(value, list):
                    unique_list = []
                    for item in value:
                        if isinstance(item, dict):
                            text = json.dumps(item, sort_keys=True, ensure_ascii=False)
                        else:
                            text = str(item)
                        if text not in seen_texts:
                            seen_texts.add(text)
                            unique_list.append(item)
                    layer_data[key] = unique_list

        return layers

    def _assemble_prompt(self, layers: dict, task_type: str) -> str:
        """将多层上下文组装为可注入的prompt文本"""
        sections: list[str] = []

        # L0: 任务
        l0 = layers.get("L0_task", {})
        sections.append(f"## 当前任务\n目标: {l0.get('goal', '')}")
        if l0.get("user_input"):
            sections.append(f"用户输入: {json.dumps(l0['user_input'], ensure_ascii=False)}")

        # L1: 领域知识
        l1 = layers.get("L1_domain", {})
        if l1.get("best_practices"):
            sections.append("\n## 最佳实践")
            for bp in l1["best_practices"]:
                rules = bp.get("rules", [])
                for rule in rules:
                    marker = "必须" if rule.get("enforcement") == "hard" else "建议"
                    sections.append(f"- [{marker}] {rule.get('rule', '')}")

        if l1.get("known_failures"):
            sections.append("\n## 已知问题（需规避）")
            for fail in l1["known_failures"]:
                sections.append(f"- {fail.get('skill', '')}: {fail.get('pattern', '')}")
                if fail.get("solution"):
                    sections.append(f"  解决: {fail['solution']}")

        if l1.get("workflow_pattern"):
            wf = l1["workflow_pattern"]
            sections.append(f"\n## 参考流程: {wf.get('pattern_name', '')}")
            for phase in wf.get("phases", []):
                sections.append(f"- Phase {phase.get('phase', '?')}: {phase.get('name', '')}")

        # L2: 历史
        l2 = layers.get("L2_history", {})
        if l2.get("reflection_lessons"):
            sections.append("\n## 历史经验")
            for lesson in l2["reflection_lessons"]:
                sections.append(f"- {lesson}")

        # L3: 用户偏好
        l3 = layers.get("L3_user", {})
        if l3.get("domain_preferences"):
            sections.append("\n## 用户偏好")
            for pref in l3["domain_preferences"]:
                sections.append(f"- {json.dumps(pref, ensure_ascii=False)}")

        # L4: 约束
        l4 = layers.get("L4_constraints", {})
        sections.append(f"\n## 约束\n预算: ¥{l4.get('budget_cny', 5)}, 时限: {l4.get('time_limit_s', 300)}s")
        perms = l4.get("permissions", {})
        denied = [k for k, v in perms.items() if not v and k.startswith("can_")]
        if denied:
            sections.append(f"禁止: {', '.join(denied)}")

        # L5: 实时
        l5 = layers.get("L5_realtime", {})
        if l5.get("active_goals"):
            sections.append("\n## 活跃目标")
            for g in l5["active_goals"]:
                sections.append(f"- {g}")

        return "\n".join(sections)

    def _estimate_tokens(self, text: str) -> int:
        """粗略估算token数（中文≈1.5字/token, 英文≈4字符/token）"""
        cjk_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        ascii_chars = len(re.findall(r'[\x00-\x7f]', text))
        return int(cjk_chars * 1.5 + ascii_chars / 4)

    def _compute_freshness(self, layers: dict) -> dict[str, str]:
        """计算各层信息的新鲜度"""
        now = datetime.now()
        freshness: dict[str, str] = {}

        for name, layer in layers.items():
            if not isinstance(layer, dict):
                continue
            timestamps = []
            for key in ["timestamp", "created_at", "last_updated", "updated_at"]:
                val = layer.get(key)
                if val:
                    try:
                        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
                        timestamps.append(dt)
                    except (ValueError, TypeError):
                        pass

            if timestamps:
                latest = max(timestamps)
                age = now - latest
                if age < timedelta(hours=1):
                    freshness[name] = "fresh"
                elif age < timedelta(days=1):
                    freshness[name] = "recent"
                elif age < timedelta(days=7):
                    freshness[name] = "stale"
                else:
                    freshness[name] = "outdated"
            else:
                freshness[name] = "unknown"

        return freshness

    def get_context_for_delegate(
        self, goal: str, user_input: Optional[dict] = None, **kwargs
    ) -> str:
        """
        生成适合 delegate_task 的 context 字符串

        直接返回 assembled_prompt，可传给 delegate_task(context=...)
        """
        ctx = self.build_context(goal, user_input, **kwargs)
        return ctx["assembled_prompt"]
