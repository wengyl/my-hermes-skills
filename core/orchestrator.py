"""
HermesOrchestrator — Hermes 增强层总调度入口

架构定位：
  不是替代 Hermes 的推理/规划/执行，而是作为 Hermes 的 Enterprise Agent Layer
  提供：能力注册 → 规划增强 → 执行评估 → 反思沉淀 → 知识管理 闭环

完整闭环：
UserGoal → KnowledgeBridge(规划增强上下文) → Planner → ExecutionEngine
→ Evaluator → (RepairAgent if needed) → Memory
→ ReflectionEngine(反思+知识沉淀) → Knowledge Candidates

与 Hermes 原生能力的关系：
  - Hermes Skills: 增强层通过 export_to_skill_references() 为 Skill 提供 references/
  - Hermes Memory: 增强层的反思经验通过 KnowledgeBridge 路由到 Hermes Memory
  - Hermes Tools: 增强层不替代 Hermes Tools，而是评估它们的输出质量
  - Hermes Learning: 增强层的 Reflection 不直接改 Skill，走 Candidate 管道

调用方式：
    result = orchestrator.run(goal="把道氏理论PDF转成AI讲解视频", user_input={...})
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from .db import Database
from .registry import CapabilityRegistry
from .state_machine import TaskStateMachine
from .planner import PlannerAgent
from .executor import ExecutionEngine
from .evaluator import Evaluator
from .repair import RepairAgent
from .memory import MemorySubsystem
from .cost_manager import CostManager
from .reflection import ReflectionEngine
from .knowledge_curator import KnowledgeCurator
from .knowledge_bridge import KnowledgeBridge
from .context_engine import ContextEngine
from .capability_graph import CapabilityGraph
from .decision_engine import DecisionEngine
from .model_router import ModelRouter
from .feedback_loop import FeedbackLoop
from .journal import AgentJournal
from .goal_manager import GoalManager
from .multi_agent import MultiAgentCoordinator

logger = logging.getLogger(__name__)


class HermesOrchestrator:
    """
    Hermes 增强层总调度入口

    串联所有增强模块，提供端到端的：
    知识供给 → 规划增强 → 执行 → 评估 → 修复 → 记忆 → 反思 → 知识沉淀

    增强层组件：
      - KnowledgeBridge: 连接 Hermes 原生能力，提供规划上下文和知识供给
      - ReflectionEngine: 任务后反思，生成知识候选（不直接改Skill）
      - KnowledgeCurator: Memos → Knowledge 路由管道
      - Planner/Executor/Evaluator/Repair/Memory: 保留原核心引擎
    """

    def __init__(
        self,
        db_path: str = "data/agent_os.db",
        scan_root: str = "capabilities",
        knowledge_dir: str = "knowledge",
        config: Optional[dict] = None
    ):
        self.db = Database(db_path)
        self.registry = CapabilityRegistry(self.db, scan_root=scan_root)
        self.sm = TaskStateMachine(self.db)
        self.planner = PlannerAgent(self.registry, self.sm)
        self.executor = ExecutionEngine(self.registry, self.sm, self.db)
        self.evaluator = Evaluator(self.registry, self.sm, self.db)
        self.repair = RepairAgent(self.registry, self.sm, self.db, self.evaluator, self.executor)
        self.memory = MemorySubsystem(self.db)
        self.cost = CostManager(self.db, self.registry)

        # ── 增强层组件 ──
        self.reflection = ReflectionEngine(self.db, self.registry, self.memory, knowledge_dir)
        self.curator = KnowledgeCurator(knowledge_dir)
        self.bridge = KnowledgeBridge(
            self.db, self.registry, self.memory,
            self.reflection, self.curator, knowledge_dir
        )
        # ── Agent Engineering 组件 ──
        self.context_engine = ContextEngine(
            self.db, self.registry, self.memory, self.bridge, knowledge_dir
        )
        self.capability_graph = CapabilityGraph(self.registry, self.db)
        self.decision_engine = DecisionEngine(
            rules_dir=os.path.join(os.path.dirname(knowledge_dir), "decision-engine/rules")
        )
        self.model_router = ModelRouter(self.db)
        self.feedback = FeedbackLoop(
            feedback_dir=os.path.join(os.path.dirname(knowledge_dir), "feedback")
        )
        self.journal = AgentJournal(
            journal_dir=os.path.join(os.path.dirname(knowledge_dir), "journal")
        )
        self.goal_manager = GoalManager(
            goals_dir=os.path.join(os.path.dirname(knowledge_dir), "goals")
        )
        self.multi_agent = MultiAgentCoordinator(self.model_router)

        self.config = config or {}
        self.pass_threshold = self.config.get("evaluator", {}).get("thresholds", {}).get("pass", 70)
        self.learning_threshold = self.config.get("evaluator", {}).get("thresholds", {}).get("excellent", 85)
        self.max_retries = self.config.get("task", {}).get("max_retries", 3)
        self.repair.repair = None  # Will be set below
        self.repair.max_retries = self.max_retries

        # 同步能力注册表
        self.registry.sync()
        logger.info(f"Orchestrator initialized: {self.registry.summary()['total']} capabilities + Knowledge Bridge")

    def run(
        self, goal: str, user_input: Optional[dict] = None,
        budget_cny: float = 5.0
    ) -> dict[str, Any]:
        """
        端到端执行一个任务。

        Args:
            goal: 用户目标描述
            user_input: 用户原始输入参数（文件路径、选项等）
            budget_cny: 预算上限（CNY）

        Returns:
            {
                "task_id": str,
                "goal": str,
                "state": str,
                "plan": dict,
                "exec_result": dict,
                "eval_result": dict,
                "repair_result": Optional[dict],
                "cost_summary": dict,
                "memory_saved": bool,
                "success": bool,
            }
        """
        start_time = time.time()

        # ── Step 1: 创建任务 ──
        task = self.sm.create_task(goal)
        task_id = task["task_id"]
        logger.info(f"━━━ Task {task_id} started: {goal[:80]} ━━━")

        # ── Step 1.5: Context Engine 组装上下文 ──
        context = self.context_engine.build_context(
            goal, user_input,
            budget_cny=budget_cny,
        )
        logger.info(f"Context assembled: domain={context['domain']}, "
                     f"tokens≈{context['token_estimate']}, "
                     f"freshness={context['metadata']['freshness']}")

        # ── Step 1.6: Capability Graph 查询最优路径 ──
        graph_query = self.capability_graph.query_capabilities_for_goal(goal)
        logger.info(f"Capability graph: pattern={graph_query['matched_pattern']}, "
                     f"path={'→'.join(graph_query['optimal_path'][:5])}...")

        # ── Step 2: Planner 规划 ──
        logger.info("Phase: PLANNING")
        plan = self.planner.plan(task_id, goal)

        # 预算检查
        budget_check = self.cost.check_budget(task_id, plan, budget_cny)
        if not budget_check["within_budget"]:
            logger.warning(
                f"Budget warning: estimated ¥{budget_check['estimated_cost']}, "
                f"budget ¥{budget_check['budget']}. {budget_check['recommendation']}"
            )

        # ── Step 3: ExecutionEngine 执行 ──
        logger.info("Phase: EXECUTING")
        exec_result = self.executor.execute_plan(task_id, plan, user_input)

        # 记录每步成本
        for step_r in exec_result["step_results"]:
            cap = self.registry.get(step_r["skill"])
            if cap:
                step_cost = cap["cost"].get("price_cny", 0)
                self.cost.record_step_cost(
                    task_id, step_r["step"], step_r["skill"], step_cost,
                    tokens_used=cap["cost"].get("token_estimate", 0)
                )

        if not exec_result["success"]:
            # 执行失败
            self.sm.fail(task_id, "Execution failed")
            return self._finalize(task_id, goal, plan, exec_result, None, None, None, False, start_time)

        # ── Step 4: Evaluator 评估 ──
        logger.info("Phase: EVALUATING")
        eval_result = self.evaluator.evaluate_task(task_id, exec_result, plan)

        # ── Step 5: RepairAgent 修复（如果需要）──
        repair_result: Optional[dict] = None
        if eval_result["needs_repair"]:
            logger.info(f"Phase: REPAIRING (failed steps: {eval_result['failed_steps']})")
            repair_result = self.repair.repair_task(task_id, eval_result, plan, exec_result)

            # 修复后重新评估
            if repair_result.get("repaired"):
                # 更新评估结果
                for ns in repair_result.get("new_scores", []):
                    for ss in eval_result["step_scores"]:
                        if ss["step"] == ns["step"]:
                            ss["score"] = ns["new_score"]
                            ss["passed"] = ns["passed"]
                eval_result["failed_steps"] = [
                    s["step"] for s in eval_result["step_scores"] if not s["passed"]
                ]
                eval_result["needs_repair"] = len(eval_result["failed_steps"]) > 0
                if eval_result["step_scores"]:
                    eval_result["overall_score"] = sum(
                        s["score"] for s in eval_result["step_scores"]
                    ) / len(eval_result["step_scores"])
        else:
            # 评估通过
            logger.info(f"Evaluation passed: score {eval_result['overall_score']}")

        # ── Step 6: 状态完成 ──
        # 如果刚修复完，状态是 repairing → 需先转回 evaluating
        current_state = self.sm.get_task(task_id)
        if current_state and current_state["state"] == "repairing":
            self.sm.transition(task_id, "evaluating")

        overall_score = eval_result["overall_score"]
        self.sm.complete(task_id, {
            "overall_score": overall_score,
            "step_scores": eval_result["step_scores"],
            "repair_count": repair_result.get("repair_attempts", 0) if repair_result else 0,
        })

        # ── Step 7: Memory 记忆 ──
        logger.info("Phase: LEARNING")
        self._save_to_memory(task_id, goal, plan, exec_result, eval_result, repair_result)

        # ── Step 7.5: Reflection 反思（增强层）──
        logger.info("Phase: REFLECTION")
        reflection_result = self.reflection.reflect(
            task_id=task_id,
            goal=goal,
            plan=plan,
            exec_result=exec_result,
            eval_result=eval_result,
            repair_result=repair_result,
        )
        logger.info(
            f"Reflection: success_factors={len(reflection_result['success_factors'])}, "
            f"failure_factors={len(reflection_result['failure_factors'])}, "
            f"candidates={len(reflection_result['candidates_generated'])}"
        )

        # ── Step 7.6: Journal 工作日志 ──
        self.journal.write_entry(
            task_id=task_id,
            goal=goal,
            domain=plan.get("domain", "general"),
            decisions=[f"域={plan.get('domain')}, 步骤={len(plan.get('steps', []))}"],
            result={
                "success": overall_score >= self.pass_threshold,
                "eval_result": eval_result,
                "total_duration_s": time.time() - start_time,
                "cost_summary": self.cost.get_task_cost(task_id),
            },
            lessons=reflection_result.get("lessons_learned", []),
            next_actions=reflection_result.get("recommendations", []),
        )

        # ── Step 8: Cost 总结 ──
        cost_summary = self.cost.get_task_cost(task_id)

        success = overall_score >= self.pass_threshold
        self.sm.learn(task_id)

        return self._finalize(
            task_id, goal, plan, exec_result, eval_result, repair_result,
            cost_summary, success, start_time
        )

    def _save_to_memory(
        self, task_id: str, goal: str, plan: dict[str, Any],
        exec_result: dict[str, Any], eval_result: dict[str, Any],
        repair_result: Optional[dict]
    ):
        """保存执行经验到 Memory"""
        # 1. 技能运行统计
        for step_r in exec_result["step_results"]:
            skill = step_r["skill"]
            step_eval = next(
                (s for s in eval_result["step_scores"] if s["step"] == step_r["step"]), {}
            )
            self.memory.save_skill_stats(
                skill_name=skill,
                task_id=task_id,
                success=step_r["success"],
                score=step_eval.get("score", 0),
                duration_ms=step_r.get("duration_ms", 0),
            )

        # 2. 失败案例
        if eval_result["needs_repair"] or (repair_result and not repair_result.get("repaired")):
            for failed_step in eval_result["failed_steps"]:
                step_def = next(
                    (s for s in plan["steps"] if s["step"] == failed_step), {}
                )
                step_eval = next(
                    (s for s in eval_result["step_scores"] if s["step"] == failed_step), {}
                )
                self.memory.save_failure(
                    skill_name=step_def.get("skill", "unknown"),
                    task_id=task_id,
                    defects=step_eval.get("defects", []),
                    context={"goal": goal, "step": failed_step},
                )

        # 3. 高分成功样例
        if eval_result["overall_score"] >= self.learning_threshold:
            self.memory.save_best_case(
                task_id=task_id,
                goal=goal,
                plan=plan,
                result=exec_result,
                score=eval_result["overall_score"],
                domain=plan.get("domain", "general"),
            )

    def _finalize(
        self, task_id: str, goal: str, plan: dict, exec_result: dict,
        eval_result: Optional[dict], repair_result: Optional[dict],
        cost_summary: Optional[dict], success: bool, start_time: float
    ) -> dict[str, Any]:
        """生成最终报告"""
        duration = time.time() - start_time
        return {
            "task_id": task_id,
            "goal": goal,
            "state": self.sm.get_task(task_id)["state"] if self.sm.get_task(task_id) else "unknown",
            "plan": plan,
            "exec_result": exec_result,
            "eval_result": eval_result,
            "repair_result": repair_result,
            "cost_summary": cost_summary,
            "total_duration_s": round(duration, 2),
            "success": success,
        }