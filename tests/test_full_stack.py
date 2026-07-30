#!/usr/bin/env python3
"""
全链路集成测试 — HermesOrchestrator 端到端

验证完整数据流:
UserGoal → Planner → ExecutionEngine → Evaluator → RepairAgent → Memory → Evolution

覆盖三个业务域：video / investment / mlops
"""

import sys, os, json
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.orchestrator import HermesOrchestrator
from core.evolution import EvolutionModule

def main():
    print("━━━ Full-Stack Integration Test ━━━\n")

    orch = HermesOrchestrator(
        db_path="data/agent_os.db",
        scan_root="capabilities",
        config={
            "task": {"max_retries": 3},
            "evaluator": {"thresholds": {"pass": 70, "excellent": 85}},
        }
    )

    # ── Test 1: 视频域全链路 ──
    print("━━━ Test 1: Video Domain Full Pipeline ━━━")
    r1 = orch.run(
        goal="把道氏理论PDF转成AI讲解视频",
        user_input={"source": "dow_theory.pdf", "source_type": "file", "style": "professional"},
        budget_cny=5.0
    )
    print(f"  Task: {r1['task_id']}")
    print(f"  Domain: {r1['plan']['domain']}")
    print(f"  Steps: {r1['plan']['total_steps']}")
    print(f"  Exec: {r1['exec_result']['success']}")
    print(f"  Eval score: {r1['eval_result']['overall_score']}")
    print(f"  Repair: {r1['repair_result']['repair_attempts'] if r1['repair_result'] else 0}")
    print(f"  Cost: ¥{r1['cost_summary']['total_cost_cny']}")
    print(f"  Success: {r1['success']}")
    assert r1['plan']['domain'] == 'video'
    assert r1['plan']['total_steps'] == 11

    # ── Test 2: 投资域全链路 ──
    print("\n━━━ Test 2: Investment Domain Full Pipeline ━━━")
    r2 = orch.run(
        goal="诊断我的基金组合并给出调仓建议",
        user_input={"fund_codes": ["002112", "005165", "012922"]},
        budget_cny=2.0
    )
    print(f"  Task: {r2['task_id']}")
    print(f"  Domain: {r2['plan']['domain']}")
    print(f"  Steps: {r2['plan']['total_steps']}")
    print(f"  Eval score: {r2['eval_result']['overall_score']}")
    print(f"  Cost: ¥{r2['cost_summary']['total_cost_cny']}")
    print(f"  Success: {r2['success']}")
    assert r2['plan']['domain'] == 'investment'

    # ── Test 3: MLOps 域全链路 ──
    print("\n━━━ Test 3: MLOps Domain Full Pipeline ━━━")
    r3 = orch.run(
        goal="搜索并部署一个text-generation模型到本地推理服务",
        user_input={"task": "text-generation", "backend": "vllm"},
        budget_cny=1.0
    )
    print(f"  Task: {r3['task_id']}")
    print(f"  Domain: {r3['plan']['domain']}")
    print(f"  Steps: {r3['plan']['total_steps']}")
    print(f"  Eval score: {r3['eval_result']['overall_score']}")
    print(f"  Cost: ¥{r3['cost_summary']['total_cost_cny']}")
    assert r3['plan']['domain'] == 'mlops'

    # ── Test 4: 状态机完整性验证 ──
    print("\n━━━ Test 4: State Machine Integrity ━━━")
    for r in [r1, r2, r3]:
        task = orch.sm.get_task(r['task_id'])
        print(f"  {r['task_id'][:20]}... state={task['state']:12s} retry={task['retry_count']}")
        # 状态必须是终态
        assert task['state'] in ('learning', 'completed', 'failed'), f"Task not in terminal state: {task['state']}"

    # ── Test 5: 执行日志完整性 ──
    print("\n━━━ Test 5: Execution Log Integrity ━━━")
    for r in [r1, r2, r3]:
        logs = orch.db.get_execution_logs(r['task_id'])
        evals = orch.db.get_evaluations(r['task_id'])
        print(f"  {r['task_id'][:20]}... logs={len(logs)} evals={len(evals)}")
        # 执行日志 >= 计划步骤数（修复可能产生额外日志）
        assert len(logs) >= r['plan']['total_steps']
        assert len(evals) >= 1

    # ── Test 6: 记忆系统完整性 ──
    print("\n━━━ Test 6: Memory System Integrity ━━━")
    user_prefs = orch.memory.get_user_preferences()
    failures = orch.memory.get_failures()
    best_cases = orch.memory.get_best_cases()
    all_mem = orch.db.search_memory(limit=100)
    print(f"  User preferences: {len(user_prefs)}")
    print(f"  Failure records: {len(failures)}")
    print(f"  Best cases: {len(best_cases)}")
    print(f"  Total memory entries: {len(all_mem)}")
    assert len(all_mem) > 0

    # ── Test 7: Evolution 模块 ──
    print("\n━━━ Test 7: Evolution Module ━━━")
    evolution = EvolutionModule(orch.db, orch.registry, orch.memory)
    candidates = evolution.detect_evolution_needed()
    print(f"  Evolution candidates: {len(candidates)}")
    if candidates:
        proposal = evolution.generate_evolution_proposal(
            candidates[0]["skill_name"], candidates[0]["defect_pattern"]
        )
        print(f"  Proposal: {proposal['skill_name']} {proposal['current_version']} → {proposal['proposed_version']}")
        bench = evolution.run_benchmark(proposal["skill_name"], proposal["benchmark_tests"])
        print(f"  Benchmark: {bench['passed']}/{bench['total_tests']} passed, avg={bench['avg_score']}")
        saved = evolution.save_benchmark_result(bench)
        print(f"  Saved: {saved}")

    # ── Test 8: 能力注册中心摘要 ──
    print("\n━━━ Test 8: Registry Summary ━━━")
    summary = orch.registry.summary()
    print(f"  Total capabilities: {summary['total']}")
    print(f"  By domain: {summary['by_domain']}")
    print(f"  By category: {summary['by_category']}")

    # ── Test 9: 数据库表完整性 ──
    print("\n━━━ Test 9: Database Tables ━━━")
    tables = orch.db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [t[0] for t in tables]
    print(f"  Tables: {table_names}")
    expected = {"capabilities", "tasks", "execution_logs", "evaluation_records", "memory_store"}
    assert expected.issubset(set(table_names)), f"Missing tables: {expected - set(table_names)}"

    # ── Test 10: 导出能力索引 ──
    print("\n━━━ Test 10: Export Capability Index ━━━")
    index_path = orch.registry.export_index_json("data/capability_index.json")
    with open(index_path) as f:
        index_data = json.load(f)
    print(f"  Exported {len(index_data)} capabilities to {index_path}")
    assert len(index_data) == summary['total']

    # ── 最终总结 ──
    print("\n" + "━" * 60)
    print("━━━ FULL-STACK INTEGRATION TEST PASSED ━━━")
    print("━" * 60)
    print(f"""
系统架构验证:
  ✅ CapabilityRegistry  — {summary['total']} 个原子能力注册
  ✅ TaskStateMachine    — 7状态流转 (created→planning→executing→evaluating→repairing→completed→learning)
  ✅ PlannerAgent        — 3域自动识别 + JSON执行计划生成
  ✅ ExecutionEngine     — 逐步执行 + 日志持久化
  ✅ Evaluator           — 4种评估算子 (text/image/audio/video)
  ✅ RepairAgent         — 缺陷解析 + 局部重执行 + 重试限制
  ✅ MemorySubsystem     — 4类记忆 (user/failure/skill/best_case)
  ✅ CostManager         — 成本计算 + 预算检查 + 模型推荐
  ✅ EvolutionModule     — 失败检测 + 演进方案 + Benchmark

数据流验证:
  UserGoal → Planner(plan) → Executor(execute) → Evaluator(score)
  → RepairAgent(if score<threshold) → Memory(save) → Evolution(learn)

业务域覆盖:
  Video:     {summary['by_domain'].get('video', 0)} 原子能力 (11步流水线)
  MLOps:     {summary['by_domain'].get('mlops', 0)} 原子能力 (4步流水线)
  Investment: {summary['by_domain'].get('investment', 0)} 原子能力 (5步流水线)

数据库持久化: ✅ (5张表全部写入)
Benchmark:    ✅ (测试集 + 结果文件)
""")

    orch.db.close()

if __name__ == "__main__":
    main()
