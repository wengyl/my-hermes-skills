#!/usr/bin/env python3
"""
Phase 2 Integration Test: State Machine + Planner + Executor
"""

import sys, os, json
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.db import Database
from core.registry import CapabilityRegistry
from core.state_machine import TaskStateMachine
from core.planner import PlannerAgent
from core.executor import ExecutionEngine

def main():
    print("━━━ Phase 2 Integration Test ━━━\n")

    # ── 初始化 ──
    db = Database("data/agent_os.db")
    registry = CapabilityRegistry(db, scan_root="capabilities")
    registry.sync()
    sm = TaskStateMachine(db)
    planner = PlannerAgent(registry, sm)
    executor = ExecutionEngine(registry, sm, db)

    # ── Test 1: 状态机基本流转 ──
    print("--- Test 1: State Machine ---")
    task = sm.create_task("生成道氏理论讲解视频")
    tid = task["task_id"]
    print(f"  Created task: {tid}")
    assert task["state"] == "created"

    # Illegal transition test
    try:
        sm.transition(tid, "completed")
        print("  ❌ Should have rejected created → completed")
        assert False
    except ValueError as e:
        print(f"  ✅ Rejected illegal transition: {e}")

    # Legal transition
    sm.transition(tid, "planning")
    assert sm.get_task(tid)["state"] == "planning"
    sm.transition(tid, "executing")
    sm.transition(tid, "evaluating")
    sm.transition(tid, "completed")
    print(f"  ✅ Legal transitions: created→planning→executing→evaluating→completed")

    # ── Test 2: Planner 生成视频计划 ──
    print("\n--- Test 2: Planner (video domain) ---")
    task2 = sm.create_task("把道氏理论PDF转成AI讲解视频")
    plan = planner.plan(task2["task_id"], "把道氏理论PDF转成AI讲解视频")
    print(f"  Domain: {plan['domain']}")
    print(f"  Total steps: {plan['total_steps']}")
    print(f"  Est. cost: ¥{plan['estimated_cost_cny']}")
    print(f"  Est. tokens: {plan['estimated_tokens']}")
    print(f"  Steps:")
    for s in plan["steps"]:
        parallel = f" (parallel with step {s['parallel_with']})" if s["parallel_with"] else ""
        eval_req = " [eval]" if s["evaluation_required"] else ""
        print(f"    {s['step']:2d}. {s['skill']:25s}{eval_req}{parallel}")
    assert plan["domain"] == "video"
    assert plan["total_steps"] == 11

    # ── Test 3: Planner 生成投资计划 ──
    print("\n--- Test 3: Planner (investment domain) ---")
    task3 = sm.create_task("诊断我的基金组合并给出调仓建议")
    plan3 = planner.plan(task3["task_id"], "诊断我的基金组合并给出调仓建议")
    print(f"  Domain: {plan3['domain']}")
    print(f"  Steps: {plan3['total_steps']}")
    for s in plan3["steps"]:
        print(f"    {s['step']:2d}. {s['skill']}")
    assert plan3["domain"] == "investment"

    # ── Test 4: Planner 生成 MLOps 计划 ──
    print("\n--- Test 4: Planner (mlops domain) ---")
    task4 = sm.create_task("搜索并部署一个text-generation模型到本地")
    plan4 = planner.plan(task4["task_id"], "搜索并部署一个text-generation模型到本地")
    print(f"  Domain: {plan4['domain']}")
    for s in plan4["steps"]:
        print(f"    {s['step']:2d}. {s['skill']}")

    # ── Test 5: Executor 执行计划 (placeholder runners) ──
    print("\n--- Test 5: Executor ---")
    exec_result = executor.execute_plan(task2["task_id"], plan, {"source": "dow_theory.pdf", "source_type": "file"})
    print(f"  Success: {exec_result['success']}")
    print(f"  Steps executed: {len(exec_result['step_results'])}")
    print(f"  Total duration: {exec_result['total_duration_ms']}ms")
    for r in exec_result["step_results"]:
        status = "✅" if r["success"] else "❌"
        print(f"    {status} step {r['step']}: {r['skill']} ({r['duration_ms']}ms)")

    assert exec_result["success"] == True

    # ── Test 6: 执行日志持久化 ──
    print("\n--- Test 6: Execution Logs ---")
    logs = db.get_execution_logs(task2["task_id"])
    print(f"  Logs for {task2['task_id']}: {len(logs)} entries")
    assert len(logs) == 11

    print("\n━━━ Phase 2 Integration Test PASSED ━━━")
    db.close()

if __name__ == "__main__":
    main()
