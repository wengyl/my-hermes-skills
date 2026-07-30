"""
Repair Agent — 自动修复

判定规则：评估最终分数低于阈值
执行逻辑：解析评估缺陷 → 匹配对应修复原子技能 → 发起局部重执行
"""

import json
import logging
from typing import Any, Optional

from .db import Database
from .registry import CapabilityRegistry
from .state_machine import TaskStateMachine
from .evaluator import Evaluator
from .executor import ExecutionEngine

logger = logging.getLogger(__name__)

# ── 缺陷类型 → 修复策略 ──
DEFECT_REPAIR_STRATEGIES: dict[str, list[str]] = {
    "文本过短":           ["script.create"],          # 重新生成脚本
    "文本重复率高":       ["script.create"],          # 重新生成
    "关键词覆盖率低":     ["script.create"],
    "分辨率不达标":       ["image.generate"],         # 重新生成图片
    "图片文件过小":       ["image.generate"],
    "缺少时间戳":         ["voice.generate"],         # 重新生成音频
    "音频文件数不匹配":   ["voice.generate"],
    "视频时长为0":        ["video.compose"],          # 重新合成
    "视频文件过小":       ["video.compose"],
    "缺少必填字段":       ["_self_retry"],            # 原步骤重试
    "空值字段":           ["_self_retry"],
}


class RepairAgent:
    """
    Repair Agent — 缺陷解析 + 局部重执行

    职责:
    1. 接收 Evaluator 的评估结果和失败步骤
    2. 解析缺陷类型，匹配修复策略
    3. 调用对应原子能力重新执行
    4. 重新评估修复结果
    5. 超过最大重试次数则报告失败
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        sm: TaskStateMachine,
        db: Database,
        evaluator: Evaluator,
        executor: ExecutionEngine,
        max_retries: int = 3,
    ):
        self.registry = registry
        self.sm = sm
        self.db = db
        self.evaluator = evaluator
        self.executor = executor
        self.max_retries = max_retries

    def repair_task(
        self, task_id: str, eval_result: dict[str, Any],
        plan: dict[str, Any], exec_result: dict[str, Any]
    ) -> dict[str, Any]:
        """
        对失败步骤执行修复。

        Args:
            task_id: 任务ID
            eval_result: Evaluator.evaluate_task() 输出
            plan: 原始执行计划
            exec_result: 原始执行结果

        Returns:
            {
                "repaired": bool,
                "repair_attempts": int,
                "new_scores": [ {step, skill, old_score, new_score} ],
                "final_eval": dict
            }
        """
        self.sm.start_repair(task_id)

        failed_steps = eval_result["failed_steps"]
        step_scores = eval_result["step_scores"]
        defects_map = {s["step"]: s.get("defects", []) for s in step_scores}

        repair_attempts = 0
        new_scores: list[dict[str, Any]] = []
        all_repaired = True

        for step_num in failed_steps:
            if repair_attempts >= self.max_retries:
                logger.warning(
                    f"Task {task_id}: max retries ({self.max_retries}) reached, "
                    f"step {step_num} still failing"
                )
                all_repaired = False
                break

            # 找到失败步骤信息
            step_def = None
            for s in plan["steps"]:
                if s["step"] == step_num:
                    step_def = s
                    break

            if not step_def:
                logger.error(f"Step {step_num} not found in plan")
                continue

            skill_name = step_def["skill"]
            defects = defects_map.get(step_num, [])

            # 匹配修复策略
            repair_skill = self._match_repair_strategy(defects, skill_name)

            old_score = next(
                (s["score"] for s in step_scores if s["step"] == step_num), 0
            )

            logger.info(
                f"Task {task_id}: repairing step {step_num} ({skill_name}) "
                f"→ using {repair_skill}, defects: {defects}"
            )

            # 执行修复
            if repair_skill == "_self_retry":
                # 原步骤重试
                repair_output = self.executor.execute_single_step(
                    task_id, step_num, skill_name,
                    {"repair": True, "defects": defects, "retry": repair_attempts + 1}
                )
            else:
                # 调用修复能力
                repair_output = self.executor.execute_single_step(
                    task_id, step_num, repair_skill,
                    {"repair": True, "defects": defects, "target_skill": skill_name}
                )

            repair_attempts += 1
            self.sm.increment_retry(task_id)

            # 重新评估修复结果
            new_eval = self.evaluator.evaluate_step(
                task_id, step_num, repair_skill,
                repair_output.get("output", {}),
                context={"defects": defects}
            )

            new_scores.append({
                "step": step_num,
                "skill": repair_skill,
                "old_score": old_score,
                "new_score": new_eval["score"],
                "passed": new_eval["passed"],
            })

            if not new_eval["passed"]:
                all_repaired = False

        result = {
            "repaired": all_repaired,
            "repair_attempts": repair_attempts,
            "new_scores": new_scores,
            "all_passed": all_repaired,
        }

        # 状态转换
        if all_repaired:
            self.sm.transition(task_id, "evaluating")  # 修复后重新评估
        else:
            logger.warning(f"Task {task_id}: repair failed after {repair_attempts} attempts")

        return result

    def _match_repair_strategy(
        self, defects: list[str], original_skill: str
    ) -> str:
        """根据缺陷类型匹配修复策略"""
        for defect in defects:
            for pattern, repair_skill in DEFECT_REPAIR_STRATEGIES.items():
                if pattern in defect:
                    if repair_skill == "_self_retry":
                        return original_skill
                    # 检查修复能力是否在注册表中
                    if self.registry.get(repair_skill):
                        return repair_skill

        # 默认：原步骤重试
        return original_skill
