"""
ExecutionEngine — 任务调度 + 原子技能调用

从 Planner 输出的执行计划逐步执行：
1. 加载能力的 runner.py
2. 构建输入数据（根据 input_mapping 合并前序输出）
3. 调用 runner.execute(input)
4. 记录执行日志到 SQLite
5. 返回每步输出供 Evaluator 评估
"""

import json
import logging
import time
from typing import Any, Optional

from .db import Database
from .registry import CapabilityRegistry
from .state_machine import TaskStateMachine

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    ExecutionEngine — 按计划逐步执行原子能力。

    职责:
    1. 加载能力 runner
    2. 构建步骤输入（合并前序输出 + 用户原始输入）
    3. 调用 runner.execute()
    4. 记录执行日志
    5. 收集每步输出
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        sm: TaskStateMachine,
        db: Database,
    ):
        self.registry = registry
        self.sm = sm
        self.db = db
        self._step_outputs: dict[int, dict[str, Any]] = {}  # step → output

    def execute_plan(
        self, task_id: str, plan: dict[str, Any], user_input: Optional[dict] = None
    ) -> dict[str, Any]:
        """
        执行完整计划。

        Args:
            task_id: 任务ID
            plan: Planner 输出的执行计划
            user_input: 用户原始输入参数

        Returns:
            {
                "task_id": str,
                "success": bool,
                "step_results": [ {step, skill, success, output, duration_ms} ],
                "final_output": dict,
                "total_duration_ms": int
            }
        """
        self.sm.start_execution(task_id)
        self._step_outputs = {}

        steps = plan.get("steps", [])
        results: list[dict[str, Any]] = []
        start_time = time.time()

        for step_def in steps:
            step_num = step_def["step"]
            skill_name = step_def["skill"]

            logger.info(f"Task {task_id}: executing step {step_num}/{len(steps)} → {skill_name}")
            self.sm.advance_step(task_id, step_num)

            # 构建输入
            input_data = self._build_step_input(step_def, plan, user_input)

            # 执行
            result = self._execute_step(task_id, step_num, skill_name, input_data)

            results.append(result)
            self._step_outputs[step_num] = result

            if not result["success"]:
                # 执行失败 → 交给 Evaluator/Repair 处理
                logger.warning(
                    f"Task {task_id}: step {step_num} ({skill_name}) failed: "
                    f"{result.get('error', 'unknown')}"
                )
                break

        total_duration = int((time.time() - start_time) * 1000)
        success = all(r["success"] for r in results)

        return {
            "task_id": task_id,
            "success": success,
            "step_results": results,
            "final_output": self._step_outputs.get(len(results), {}),
            "total_duration_ms": total_duration,
        }

    def _build_step_input(
        self, step_def: dict[str, Any], plan: dict[str, Any],
        user_input: Optional[dict]
    ) -> dict[str, Any]:
        """根据 input_mapping 构建步骤输入"""
        mapping = step_def.get("input_mapping", {})
        source = mapping.get("_source", "previous_steps")
        input_data: dict[str, Any] = {}

        if source == "user_goal":
            # 第一步：从用户输入获取
            if user_input:
                input_data.update(user_input)
            input_data["goal"] = mapping.get("goal", plan.get("goal", ""))
        else:
            # 后续步骤：从前序输出获取
            deps = mapping.get("_depends_on", [])
            for dep in deps:
                # 找到依赖步骤的输出
                for step_num, output in self._step_outputs.items():
                    prev_step = None
                    for s in plan["steps"]:
                        if s["skill"] == dep:
                            prev_step = s
                            break
                    if prev_step and prev_step["step"] == step_num:
                        input_data.update(output.get("output", {}))

        return input_data

    def _execute_step(
        self, task_id: str, step_num: int, skill_name: str,
        input_data: dict[str, Any]
    ) -> dict[str, Any]:
        """执行单个步骤"""
        start = time.time()
        result: dict[str, Any] = {
            "step": step_num,
            "skill": skill_name,
            "success": False,
            "output": {},
            "duration_ms": 0,
        }

        try:
            # 加载 runner
            module = self.registry.load_runner(skill_name)
            if not hasattr(module, "execute"):
                raise AttributeError(f"Runner for {skill_name} has no execute() function")

            # 调用 execute
            output = module.execute(input_data)

            result["output"] = output
            result["success"] = True
            result["duration_ms"] = int((time.time() - start) * 1000)

            # 记录日志
            self.db.log_execution({
                "task_id": task_id,
                "step_index": step_num,
                "skill_name": skill_name,
                "input": input_data,
                "output": output,
                "success": True,
                "duration_ms": result["duration_ms"],
            })

            logger.info(
                f"  ✅ {skill_name} completed in {result['duration_ms']}ms"
            )

        except Exception as e:
            result["error"] = str(e)
            result["duration_ms"] = int((time.time() - start) * 1000)

            self.db.log_execution({
                "task_id": task_id,
                "step_index": step_num,
                "skill_name": skill_name,
                "input": input_data,
                "output": {},
                "success": False,
                "duration_ms": result["duration_ms"],
                "error_message": str(e),
            })

            logger.error(f"  ❌ {skill_name} failed: {e}")

        return result

    def execute_single_step(
        self, task_id: str, step_num: int, skill_name: str,
        input_data: dict[str, Any]
    ) -> dict[str, Any]:
        """执行单个步骤（用于 Repair Agent 的局部重执行）"""
        return self._execute_step(task_id, step_num, skill_name, input_data)
