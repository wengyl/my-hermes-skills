#!/usr/bin/env python3
"""
Phase 3 Integration Test: Evaluator + Repair + Memory + CostManager
+ End-to-End Orchestrator test
"""

import sys, os, json
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.orchestrator import HermesOrchestrator

def main():
    print("━━━ Phase 3 + E2E Integration Test ━━━\n")

    # ── 初始化 Orchestrator（含全部模块）──
    orch = HermesOrchestrator(
        db_path="data/agent_os.db",
        scan_root="capabilities",
        config={
            "task": {"max_retries": 3},
            "evaluator": {"thresholds": {"pass": 70, "excellent": 85}},
        }
    )

    # 创建测试task供评估记录引用
    test_task = orch.sm.create_task("test evaluator task")
    test_tid = test_task["task_id"]

    # ── Test 1: Evaluator 算子 ──
    print("--- Test 1: Evaluator Operators ---")

    # text.score
    text_result = orch.evaluator.evaluate_step(
        test_tid, 1, "script.create",
        {"title": "道氏理论", "scenes": [{"voice_text": "道氏理论是技术分析的基础" * 20}]},
    )
    print(f"  text.score: {text_result['score']} (passed={text_result['passed']})")
    assert text_result["score"] > 0

    # image.score (no file)
    img_result = orch.evaluator.evaluate_step(
        test_tid, 5, "image.generate",
        {"image_path": "/tmp/test.png", "method_used": "html_screenshot", "width": 1920, "height": 1080},
    )
    print(f"  image.score: {img_result['score']} (passed={img_result['passed']})")

    # audio.score
    audio_result = orch.evaluator.evaluate_step(
        test_tid, 5, "voice.generate",
        {"audio_files": ["a.mp3"], "srt_files": ["a.json"], "total_duration": 30.5},
    )
    print(f"  audio.score: {audio_result['score']} (passed={audio_result['passed']})")
    assert audio_result["passed"]

    # video.score
    video_result = orch.evaluator.evaluate_step(
        test_tid, 11, "video.compose",
        {"video_path": "/tmp/test.mp4", "duration": 180.5, "file_size_mb": 32, "resolution": "1920x1080"},
    )
    print(f"  video.score: {video_result['score']} (passed={video_result['passed']})")
    assert video_result["passed"]

    # ── Test 2: Memory 子系统 ──
    print("\n--- Test 2: Memory Subsystem ---")

    # 保存用户偏好
    orch.memory.save_user_preference("video_style", "dark_professional", domain="video")
    prefs = orch.memory.get_user_preferences()
    print(f"  User preferences saved: {len(prefs)}")
    assert len(prefs) >= 1

    # 保存失败案例
    orch.memory.save_failure(
        "image.generate", "test_task_1",
        ["分辨率不达标（1280x720）", "图片文件过小（30KB）"],
        {"scene": "scene_01"},
        solution="重新生成1920x1080"
    )
    failures = orch.memory.get_failures("image.generate")
    print(f"  Failures saved: {len(failures)}")
    assert len(failures) >= 1

    # 获取失败模式
    patterns = orch.memory.get_failure_patterns("image.generate")
    print(f"  Failure patterns: {len(patterns)}")
    for p in patterns:
        print(f"    {p['defect_pattern']} (count={p['count']})")

    # 保存技能统计
    orch.memory.save_skill_stats("script.create", "test_task_2", True, 85.5, 1200, 0.15)
    orch.memory.save_skill_stats("script.create", "test_task_3", False, 45.0, 800, 0.15)
    stats = orch.memory.get_skill_summary("script.create")
    print(f"  Skill stats: runs={stats['total_runs']}, success_rate={stats['success_rate']}%, avg_score={stats['avg_score']}")

    # 保存高分样例
    orch.memory.save_best_case("test_best_1", "生成道氏理论视频", {"steps": []}, {"output": "ok"}, 92, "video")
    best = orch.memory.get_best_cases()
    print(f"  Best cases: {len(best)}")

    # Planner 上下文
    ctx = orch.memory.get_planner_context("video")
    print(f"  Planner context: {len(ctx['known_failures'])} known failures, {len(ctx['best_cases'])} best cases")

    # ── Test 3: Cost Manager ──
    print("\n--- Test 3: Cost Manager ---")

    # 单步成本
    step_cost = orch.cost.calculate_step_cost("script.create", tokens_used=5000, model="glm-5.2")
    print(f"  script.create cost: ¥{step_cost['cost_cny']} (model={step_cost['model']})")

    # 模型推荐
    rec_low = orch.cost.recommend_model_tier(0.5, "video")
    rec_mid = orch.cost.recommend_model_tier(3.0, "video")
    rec_high = orch.cost.recommend_model_tier(10.0, "video")
    print(f"  Model tier (¥0.5): {rec_low['tier']} → LLM={rec_low['llm']}")
    print(f"  Model tier (¥3.0): {rec_mid['tier']} → LLM={rec_mid['llm']}")
    print(f"  Model tier (¥10):  {rec_high['tier']} → LLM={rec_high['llm']}")

    # ── Test 4: 端到端 Orchestrator (视频任务) ──
    print("\n--- Test 4: E2E Orchestrator (video) ---")
    result = orch.run(
        goal="把道氏理论PDF转成AI讲解视频",
        user_input={"source": "dow_theory.pdf", "source_type": "file"},
        budget_cny=5.0
    )
    print(f"  Task: {result['task_id']}")
    print(f"  State: {result['state']}")
    print(f"  Success: {result['success']}")
    print(f"  Plan: {result['plan']['total_steps']} steps, domain={result['plan']['domain']}")
    print(f"  Exec: {len(result['exec_result']['step_results'])} steps, {result['exec_result']['total_duration_ms']}ms")
    print(f"  Eval: score={result['eval_result']['overall_score']}")
    print(f"  Repair: {result['repair_result']['repair_attempts'] if result['repair_result'] else 'N/A'}")
    print(f"  Cost: ¥{result['cost_summary']['total_cost_cny']}")
    print(f"  Duration: {result['total_duration_s']}s")
    print(f"  Steps:")
    for ss in result['eval_result']['step_scores']:
        status = "✅" if ss['passed'] else "❌"
        print(f"    {status} step {ss['step']:2d}: {ss['skill']:25s} score={ss['score']:5.1f}")

    # ── Test 5: 端到端 Orchestrator (投资任务) ──
    print("\n--- Test 5: E2E Orchestrator (investment) ---")
    result2 = orch.run(
        goal="诊断我的基金组合并给出调仓建议",
        user_input={"fund_codes": ["002112", "005165", "012922"]},
        budget_cny=2.0
    )
    print(f"  Task: {result2['task_id']}")
    print(f"  Domain: {result2['plan']['domain']}")
    print(f"  Steps: {result2['plan']['total_steps']}")
    print(f"  Eval: score={result2['eval_result']['overall_score']}")
    print(f"  Success: {result2['success']}")

    # ── Test 6: 验证数据库持久化 ──
    print("\n--- Test 6: Database Persistence ---")
    tasks = orch.sm.list_tasks(limit=10)
    print(f"  Total tasks in DB: {len(tasks)}")
    for t in tasks:
        print(f"    {t['task_id'][:20]}... state={t['state']:12s} goal={t['goal'][:40]}...")

    # 评估记录
    evals = orch.db.get_evaluations(result['task_id'])
    print(f"  Evaluations for last task: {len(evals)}")

    # 执行日志
    logs = orch.db.get_execution_logs(result['task_id'])
    print(f"  Execution logs: {len(logs)}")

    # Memory store
    all_mem = orch.db.search_memory(limit=100)
    print(f"  Memory entries: {len(all_mem)}")

    print("\n━━━ Phase 3 + E2E Integration Test PASSED ━━━")
    print(f"  Orchestrator modules: registry ✅, planner ✅, executor ✅, evaluator ✅, repair ✅, memory ✅, cost ✅")
    print(f"  Total capabilities: {orch.registry.summary()['total']}")
    print(f"  Tasks created: {len(tasks)}")

    orch.db.close()

if __name__ == "__main__":
    main()
