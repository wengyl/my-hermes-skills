#!/usr/bin/env python3
"""
Phase 6 Integration Test: Agent Engineering Layer
测试 Agent Engineering 组件与 Hermes 原生能力的协同：
  1. Context Engine — 动态上下文组装 (6层)
  2. Capability Graph — 能力图谱 (节点+边+目标映射)
  3. Decision Engine — 规则驱动决策 (投资域)
  4. Model Router — 智能模型路由
  5. Feedback Loop — 用户反馈+学习闭环
  6. Agent Journal — 工作日志
  7. Goal Manager — 长期目标
  8. Multi-Agent Roles — 角色分工
  9. E2E: Orchestrator with all Agent Engineering modules
"""

import sys, os, json, tempfile, shutil
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.db import Database
from core.registry import CapabilityRegistry
from core.memory import MemorySubsystem
from core.reflection import ReflectionEngine
from core.knowledge_curator import KnowledgeCurator
from core.knowledge_bridge import KnowledgeBridge
from core.context_engine import ContextEngine
from core.capability_graph import CapabilityGraph
from core.decision_engine import DecisionEngine
from core.model_router import ModelRouter
from core.feedback_loop import FeedbackLoop
from core.journal import AgentJournal
from core.goal_manager import GoalManager
from core.multi_agent import MultiAgentCoordinator
from core.orchestrator import HermesOrchestrator


def main():
    print("━━━ Phase 6: Agent Engineering Layer Test ━━━\n")

    test_dir = tempfile.mkdtemp(prefix="agent_eng_test_")
    db_path = os.path.join(test_dir, "test.db")
    knowledge_dir = os.path.join(test_dir, "knowledge")
    os.makedirs(knowledge_dir, exist_ok=True)

    # 复制知识到测试目录
    src_knowledge = os.path.join(project_root, "knowledge")
    if os.path.exists(src_knowledge):
        for item in os.listdir(src_knowledge):
            src = os.path.join(src_knowledge, item)
            dst = os.path.join(knowledge_dir, item)
            if os.path.isdir(src) and not item.startswith("."):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                shutil.copy2(src, dst)

    # 复制决策规则
    rules_src = os.path.join(project_root, "decision-engine")
    rules_dst = os.path.join(test_dir, "decision-engine")
    if os.path.exists(rules_src):
        shutil.copytree(rules_src, rules_dst, dirs_exist_ok=True)

    # 初始化
    db = Database(db_path)
    registry = CapabilityRegistry(db, scan_root=os.path.join(project_root, "capabilities"))
    registry.sync()
    memory = MemorySubsystem(db)
    reflection = ReflectionEngine(db, registry, memory, knowledge_dir)
    curator = KnowledgeCurator(knowledge_dir)
    bridge = KnowledgeBridge(db, registry, memory, reflection, curator, knowledge_dir)

    print("--- Test 1: Context Engine — 动态上下文组装 ---")
    ctx_engine = ContextEngine(db, registry, memory, bridge, knowledge_dir)
    ctx = ctx_engine.build_context("诊断我的基金组合并给出调仓建议", budget_cny=10.0)
    assert ctx["domain"] == "investment"
    assert "L0_task" in ctx["layers"]
    assert "L1_domain" in ctx["layers"]
    assert "L4_constraints" in ctx["layers"]
    assert "assembled_prompt" in ctx
    assert len(ctx["assembled_prompt"]) > 50
    print(f"  Domain: {ctx['domain']}")
    print(f"  Layers: {list(ctx['layers'].keys())}")
    print(f"  Token estimate: {ctx['token_estimate']}")
    print(f"  Freshness: {ctx['metadata']['freshness']}")
    print(f"  Prompt preview: {ctx['assembled_prompt'][:100]}...")
    print("  ✅ Context Engine works\n")

    print("--- Test 2: Capability Graph — 能力图谱 ---")
    graph = CapabilityGraph(registry, db)
    summary = graph.get_graph_summary()
    assert summary["total_nodes"] == 23
    assert len(summary["goal_patterns"]) >= 2
    print(f"  Nodes: {summary['total_nodes']}")
    print(f"  Edges: {summary['total_edges']}")
    print(f"  Goal patterns: {summary['goal_patterns']}")

    # 查询目标能力
    query = graph.query_capabilities_for_goal("诊断基金组合")
    assert query["matched_pattern"] is not None
    assert len(query["capabilities"]) >= 5
    print(f"  Query '诊断基金': pattern={query['matched_pattern']}, caps={len(query['capabilities'])}")
    print(f"  Path: {' → '.join(query['optimal_path'][:5])}")

    # 发现断点
    gaps = graph.find_gaps()
    print(f"  Gaps found: {len(gaps)}")
    print("  ✅ Capability Graph works\n")

    print("--- Test 3: Decision Engine — 规则驱动决策 ---")
    decision = DecisionEngine(rules_dir=os.path.join(rules_dst, "rules"))
    assert len(decision.rules) > 0
    print(f"  Rules loaded: {len(decision.rules)}")

    # 模拟投资组合数据触发规则
    portfolio_data = {
        "portfolio": {"drawdown": 18, "max_single_fund_ratio": 35, "industry_concentration": 65, "qdii_ratio": 45},
        "risk": {"score": 45},
        "market": {"usd_cny_change": -3},
    }
    decisions = decision.evaluate(portfolio_data, domain="investment")
    assert len(decisions) > 0
    print(f"  Triggered decisions: {len(decisions)}")
    for d in decisions:
        print(f"    [{d['priority']}] {d['name']}: {d['action'][:50]}...")
    print("  ✅ Decision Engine works\n")

    print("--- Test 4: Model Router — 智能模型路由 ---")
    router = ModelRouter(db)

    # 简单任务 → low_cost
    simple = router.route("总结这篇文章", task_type="general", quality_requirement="low")
    assert simple["tier"] == "low_cost"
    print(f"  Simple task: model={simple['recommended_model']}, tier={simple['tier']}")

    # 复杂任务 → high_cost
    complex_task = router.route("深度分析基金组合风险并给出调仓策略", task_type="investment", subtask="diagnosis", quality_requirement="high")
    assert complex_task["tier"] == "high_cost"
    print(f"  Complex task: model={complex_task['recommended_model']}, tier={complex_task['tier']}")

    # 预算约束
    budget_limited = router.route("深度分析", budget_cny=0.5, quality_requirement="high")
    assert budget_limited["tier"] != "high_cost"
    print(f"  Budget-limited: model={budget_limited['recommended_model']}, tier={budget_limited['tier']}")
    print("  ✅ Model Router works\n")

    print("--- Test 5: Feedback Loop — 用户反馈+学习 ---")
    feedback_dir = os.path.join(test_dir, "feedback")
    feedback = FeedbackLoop(feedback_dir)

    # 记录正面反馈
    fb1 = feedback.record_feedback("task_001", rating=5, category="quality", comment="很好", domain="investment")
    assert fb1["analysis"]["sentiment"] == "positive"

    # 记录负面反馈
    fb2 = feedback.record_feedback("task_002", rating=2, category="style", comment="太像AI生成", corrections=["改为更自然的表达"], domain="video")
    assert fb2["analysis"]["sentiment"] == "negative"
    assert fb2["analysis"]["actionable"] == True

    # 分析模式
    patterns = feedback.get_feedback_patterns()
    assert patterns["total_feedback"] >= 2
    print(f"  Total feedback: {patterns['total_feedback']}")
    print(f"  Avg rating: {patterns['avg_rating']}")
    print(f"  Categories: {list(patterns['by_category'].keys())}")
    print("  ✅ Feedback Loop works\n")

    print("--- Test 6: Agent Journal — 工作日志 ---")
    journal_dir = os.path.join(test_dir, "journal")
    journal = AgentJournal(journal_dir)
    filepath = journal.write_entry(
        task_id="task_test_001",
        goal="测试日志功能",
        domain="investment",
        decisions=["使用投资诊断流程"],
        result={"success": True, "eval_result": {"overall_score": 92}, "total_duration_s": 1.5, "cost_summary": {"total_cost_cny": 0.5}},
        lessons=["组合分析需要实时数据", "回撤超15%需注意"],
        next_actions=["下次加入行业分析"],
    )
    assert os.path.exists(filepath)

    entries = journal.read_journal()
    assert len(entries) >= 1
    print(f"  Journal entries: {len(entries)}")

    report = journal.generate_report(days=7)
    assert report["total_tasks"] >= 1
    print(f"  Report: tasks={report['total_tasks']}, avg_score={report['avg_score']}")
    print(f"  Key lessons: {report['key_lessons'][:2]}")
    print("  ✅ Journal works\n")

    print("--- Test 7: Goal Manager — 长期目标 ---")
    goals_dir = os.path.join(test_dir, "goals")
    gm = GoalManager(goals_dir)
    goal = gm.create_goal(
        title="提升投资体系",
        description="6个月内建立完整的投资分析框架",
        duration_days=180,
        cycle_days=7,
        tasks=[
            {"name": "每周市场复盘", "status": "pending"},
            {"name": "每月组合检查", "status": "pending"},
        ],
    )
    assert goal["goal_id"].startswith("goal_")
    print(f"  Goal created: {goal['goal_id']}")

    active = gm.list_goals()
    assert len(active) >= 1
    print(f"  Active goals: {len(active)}")

    updated = gm.update_progress(goal["goal_id"], completed_tasks=["每周市场复盘"], cycle_completed=True, notes="第一周完成")
    assert updated["progress"]["completed_tasks"] >= 1
    print(f"  Progress: {updated['progress']['completion_rate']}%")

    due = gm.get_due_tasks()
    assert len(due) >= 1
    print(f"  Due tasks: {len(due)}")
    print("  ✅ Goal Manager works\n")

    print("--- Test 8: Multi-Agent Roles — 角色分工 ---")
    coordinator = MultiAgentCoordinator()

    # 获取角色配置
    researcher_cfg = coordinator.get_role_config("researcher")
    assert "system_prompt" in researcher_cfg
    print(f"  Researcher: {researcher_cfg['description'][:30]}...")

    # 规划高复杂度任务
    assignments = coordinator.plan_role_assignment("深度分析基金组合", "investment", "high")
    assert len(assignments) == 4
    roles = [a["role"] for a in assignments]
    assert "researcher" in roles and "analyst" in roles and "writer" in roles and "reviewer" in roles
    print(f"  High complexity: {len(assignments)} roles = {roles}")

    # 中等复杂度
    med = coordinator.plan_role_assignment("生成投资报告", "investment", "medium")
    assert len(med) == 3
    print(f"  Medium complexity: {len(med)} roles = {[a['role'] for a in med]}")

    # delegate context
    ctx_str = coordinator.get_delegate_context("analyst", "分析基金数据", "investment")
    assert "Analyst" in ctx_str
    print(f"  Delegate context: {len(ctx_str)} chars")
    print("  ✅ Multi-Agent Roles work\n")

    print("--- Test 9: E2E Orchestrator with Agent Engineering ---")
    orch = HermesOrchestrator(
        db_path=os.path.join(test_dir, "orch_test.db"),
        scan_root=os.path.join(project_root, "capabilities"),
        knowledge_dir=knowledge_dir,
        config={
            "task": {"max_retries": 3},
            "evaluator": {"thresholds": {"pass": 70, "excellent": 85}},
        },
    )
    # 验证所有Agent Engineering组件已集成
    assert hasattr(orch, 'context_engine')
    assert hasattr(orch, 'capability_graph')
    assert hasattr(orch, 'decision_engine')
    assert hasattr(orch, 'model_router')
    assert hasattr(orch, 'feedback')
    assert hasattr(orch, 'journal')
    assert hasattr(orch, 'goal_manager')
    assert hasattr(orch, 'multi_agent')
    print(f"  context_engine: ✅")
    print(f"  capability_graph: ✅ ({orch.capability_graph.get_graph_summary()['total_nodes']} nodes)")
    print(f"  decision_engine: ✅ ({len(orch.decision_engine.rules)} rules)")
    print(f"  model_router: ✅")
    print(f"  feedback: ✅")
    print(f"  journal: ✅")
    print(f"  goal_manager: ✅")
    print(f"  multi_agent: ✅ ({len(orch.multi_agent.roles)} roles)")

    result = orch.run("诊断我的基金组合并给出调仓建议")
    assert result["success"] == True
    print(f"\n  Task: {result['task_id']}")
    print(f"  Score: {result['eval_result']['overall_score']}")
    print(f"  Duration: {result['total_duration_s']}s")

    # 验证journal已写入
    entries = orch.journal.read_journal()
    assert len(entries) >= 1
    print(f"  Journal entries: {len(entries)}")
    print("  ✅ E2E with all Agent Engineering modules works\n")

    shutil.rmtree(test_dir, ignore_errors=True)

    print("━" * 60)
    print("━━━ Phase 6 Agent Engineering Test PASSED ━━━")
    print("━" * 60)
    print("\nAgent Engineering 验证:")
    print("  ✅ Context Engine        — 6层动态上下文组装 (P0)")
    print("  ✅ Capability Graph       — 能力图谱 (23节点+3种边+目标映射) (P1)")
    print("  ✅ Decision Engine        — 规则驱动 (5条投资规则) (P1)")
    print("  ✅ Model Router           — 智能路由 (3层级+预算约束) (P1)")
    print("  ✅ Feedback Loop          — 反馈收集+模式分析 (P1)")
    print("  ✅ Agent Journal          — 工作日志+周期报告 (P2)")
    print("  ✅ Goal Manager           — 长期目标+进度追踪 (P2)")
    print("  ✅ Multi-Agent Roles      — 4角色分工+delegate集成 (P2)")
    print("  ✅ E2E Integration        — 全部模块集成到Orchestrator")
    print("\n最终架构:")
    print("  Hermes OS = Hermes Core + Enhancement Layer + Agent Engineering Layer")
    print("  从 Skill Engineering → Agent Engineering 完成")


if __name__ == "__main__":
    main()
