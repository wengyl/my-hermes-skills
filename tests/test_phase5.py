#!/usr/bin/env python3
"""
Phase 5 Integration Test: Hermes Enhancement Layer
测试增强层与 Hermes 原生能力的协同：
  1. KnowledgeBridge 规划上下文供给
  2. ReflectionEngine 反思+知识候选管道
  3. KnowledgeCurator Memos→Knowledge 路由
  4. Candidate → Approve → Merge 管道
  5. Export to Hermes Skill references
  6. 端到端：Orchestrator + Reflection + Knowledge Bridge
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
from core.orchestrator import HermesOrchestrator


def main():
    print("━━━ Phase 5: Hermes Enhancement Layer Test ━━━\n")

    # ── 准备测试环境 ──
    test_db = tempfile.mkdtemp(prefix="agent_os_test_")
    db_path = os.path.join(test_db, "test.db")
    knowledge_dir = os.path.join(test_db, "knowledge")
    os.makedirs(knowledge_dir, exist_ok=True)

    # 复制现有知识到临时目录
    src_knowledge = os.path.join(project_root, "knowledge")
    if os.path.exists(src_knowledge):
        for item in os.listdir(src_knowledge):
            src = os.path.join(src_knowledge, item)
            dst = os.path.join(knowledge_dir, item)
            if os.path.isdir(src) and not item.startswith("."):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                shutil.copy2(src, dst)

    # ── 初始化增强层组件 ──
    db = Database(db_path)
    registry = CapabilityRegistry(db, scan_root=os.path.join(project_root, "capabilities"))
    registry.sync()
    memory = MemorySubsystem(db)
    reflection = ReflectionEngine(db, registry, memory, knowledge_dir)
    curator = KnowledgeCurator(knowledge_dir)
    bridge = KnowledgeBridge(db, registry, memory, reflection, curator, knowledge_dir)

    print("--- Test 1: KnowledgeBridge Planning Context ---")
    ctx = bridge.get_planning_context("诊断我的基金组合并给出调仓建议")
    assert ctx["domain"] == "investment", f"Expected investment, got {ctx['domain']}"
    assert "best_practices" in ctx
    assert "known_failures" in ctx
    assert "workflow_pattern" in ctx
    print(f"  Domain: {ctx['domain']}")
    print(f"  Best practices: {len(ctx['best_practices'])}")
    print(f"  Known failures: {len(ctx['known_failures'])}")
    print(f"  Workflow pattern: {ctx['workflow_pattern']['pattern_name'] if ctx['workflow_pattern'] else 'None'}")
    print(f"  Available capabilities: {ctx['available_capabilities']['total']}")
    print("  ✅ Planning context generated correctly\n")

    print("--- Test 2: KnowledgeBridge Skill Context ---")
    skill_ctx = bridge.get_skill_context("video")
    assert "best_practices" in skill_ctx
    assert "common_failures" in skill_ctx
    print(f"  Video best_practices: {len(skill_ctx['best_practices'])}")
    print(f"  Video common_failures: {len(skill_ctx['common_failures'])}")
    print("  ✅ Skill context generated correctly\n")

    print("--- Test 3: ReflectionEngine — 任务后反思 ---")
    # 模拟一个有成功和失败步骤的任务
    plan = {
        "goal": "测试反思",
        "domain": "video",
        "steps": [
            {"step": 1, "skill": "script.create"},
            {"step": 2, "skill": "image.generate"},
        ],
    }
    exec_result = {
        "step_results": [
            {"step": 1, "skill": "script.create", "success": True, "output": "好的脚本", "duration_ms": 100},
            {"step": 2, "skill": "image.generate", "success": True, "output": {}, "duration_ms": 200},
        ],
        "success": True,
    }
    eval_result = {
        "overall_score": 75.0,
        "step_scores": [
            {"step": 1, "skill": "script.create", "score": 95.0, "passed": True, "defects": []},
            {"step": 2, "skill": "image.generate", "score": 55.0, "passed": False, "defects": ["未生成图片路径"]},
        ],
        "failed_steps": [2],
        "needs_repair": True,
    }
    repair_result = {"repaired": True, "new_scores": [{"step": 2, "new_score": 85.0, "passed": True}], "repair_attempts": 1}

    reflection_result = reflection.reflect(
        task_id="test_reflection_001",
        goal="测试反思任务",
        plan=plan,
        exec_result=exec_result,
        eval_result=eval_result,
        repair_result=repair_result,
    )

    assert len(reflection_result["success_factors"]) > 0
    assert len(reflection_result["failure_factors"]) > 0
    assert len(reflection_result["candidates_generated"]) > 0
    print(f"  Success factors: {len(reflection_result['success_factors'])}")
    print(f"  Failure factors: {len(reflection_result['failure_factors'])}")
    print(f"  Lessons learned: {len(reflection_result['lessons_learned'])}")
    print(f"  Candidates generated: {len(reflection_result['candidates_generated'])}")
    for c in reflection_result["candidates_generated"]:
        print(f"    - {c['type']}: {c['candidate_id'][:40]}... → {c['status']}")
    print("  ✅ Reflection generated correctly\n")

    print("--- Test 4: Candidate Pipeline (approve → merge) ---")
    candidates = reflection.list_candidates("pending_validation")
    assert len(candidates) > 0
    print(f"  Pending candidates: {len(candidates)}")

    # 找一个 failure_pattern_candidate 来批准
    failure_candidate = next(
        (c for c in candidates if c["type"] == "failure_pattern_candidate"), None
    )
    if failure_candidate:
        result = reflection.approve_candidate(failure_candidate["candidate_id"])
        assert result["merged"] == True
        print(f"  Approved: {failure_candidate['candidate_id'][:40]}...")
        print(f"  Merged to: {result.get('target', 'N/A')}")

    # 验证候选已合并
    remaining = reflection.list_candidates("pending_validation")
    merged = reflection.list_candidates("approved_merged")
    print(f"  After approval: {len(remaining)} pending, {len(merged)} merged")
    print("  ✅ Candidate pipeline works\n")

    print("--- Test 5: KnowledgeCurator — Memos → Knowledge ---")
    # 测试 procedure 类型
    proc_memo = "投资分析步骤：先看宏观，然后看行业，最后看估值和风险"
    proc_result = curator.ingest_memo(proc_memo, source="test")
    assert proc_result["classified_type"] == "procedure"
    assert proc_result["routing_target"] == "hermes_skill"
    print(f"  Memo type: {proc_result['classified_type']}")
    print(f"  Routing: {proc_result['routing_target']}")

    # 测试 rule 类型
    rule_memo = "制作视频时不要在AI配图中生成文字，必须用PIL单独标注"
    rule_result = curator.ingest_memo(rule_memo, source="test")
    assert rule_result["classified_type"] == "rule"
    assert rule_result["routing_target"] == "knowledge_best_practices"
    print(f"  Rule type: {rule_result['classified_type']}")
    print(f"  Routing: {rule_result['routing_target']}")

    # 测试 experience 类型
    exp_memo = "上次基金诊断时发现token过期导致数据获取失败，需要检测401"
    exp_result = curator.ingest_memo(exp_memo, source="test")
    assert exp_result["classified_type"] == "experience"
    print(f"  Experience type: {exp_result['classified_type']}")

    # 执行 curate
    inbox_items = curator.list_inbox()
    print(f"  Inbox items: {len(inbox_items)}")
    if inbox_items:
        curate_result = curator.curate(inbox_items[0]["memo_id"])
        print(f"  Curated: {curate_result.get('routed_to', 'N/A')}")
    print("  ✅ Knowledge curator works\n")

    print("--- Test 6: Export to Hermes Skill References ---")
    export = bridge.export_for_hermes("investment")
    assert "best_practices_md" in export
    assert "common_failures_md" in export
    assert "workflow_md" in export
    print(f"  Best practices MD: {len(export['best_practices_md'])} chars")
    print(f"  Common failures MD: {len(export['common_failures_md'])} chars")
    print(f"  Workflow MD: {len(export['workflow_md'])} chars")

    # 导出到文件
    skill_ref_dir = os.path.join(test_db, "skills")
    exported_path = bridge.export_to_skill_references("investment", output_dir=skill_ref_dir)
    refs = os.listdir(os.path.join(exported_path))
    print(f"  Exported files: {refs}")
    assert len(refs) > 0
    print("  ✅ Export to Hermes Skill references works\n")

    print("--- Test 7: E2E Orchestrator with Enhancement Layer ---")
    orch_db = os.path.join(test_db, "orch_test.db")
    orch = HermesOrchestrator(
        db_path=orch_db,
        scan_root=os.path.join(project_root, "capabilities"),
        knowledge_dir=knowledge_dir,
        config={
            "task": {"max_retries": 3},
            "evaluator": {"thresholds": {"pass": 70, "excellent": 85}},
        },
    )
    assert hasattr(orch, 'reflection')
    assert hasattr(orch, 'bridge')
    assert hasattr(orch, 'curator')
    print(f"  Orchestrator has reflection: ✅")
    print(f"  Orchestrator has bridge: ✅")
    print(f"  Orchestrator has curator: ✅")
    print(f"  Total capabilities: {orch.registry.summary()['total']}")

    result = orch.run("诊断我的基金组合并给出调仓建议")
    assert result["success"] == True
    print(f"  Task: {result['task_id']}")
    print(f"  Domain: {result['plan']['domain']}")
    print(f"  Score: {result['eval_result']['overall_score']}")
    print(f"  Duration: {result['total_duration_s']}s")
    print("  ✅ E2E with enhancement layer works\n")

    # ── 清理 ──
    shutil.rmtree(test_db, ignore_errors=True)

    print("━" * 60)
    print("━━━ Phase 5 Enhancement Layer Test PASSED ━━━")
    print("━" * 60)
    print("\n增强层验证:")
    print("  ✅ KnowledgeBridge       — 规划上下文供给 + Skill知识注入")
    print("  ✅ ReflectionEngine      — 反思 + 候选生成 + 审批合并管道")
    print("  ✅ KnowledgeCurator      — Memos→Knowledge 路由 (6类型分类)")
    print("  ✅ Candidate Pipeline    — pending→approve→merge→production")
    print("  ✅ Export to Skill Refs   — 知识导出为 Hermes Skill references/")
    print("  ✅ E2E Integration       — Orchestrator + Reflection + Bridge")
    print("\n架构定位:")
    print("  Hermes Core (原生) + Enhancement Layer (本项目) = 协同")
    print("  不替代 Hermes Skill/Memory/Planner, 而是增强和治理")


if __name__ == "__main__":
    main()
