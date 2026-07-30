#!/usr/bin/env python3
"""
Phase 4 Integration Test: Evolution Module + Benchmark
"""

import sys, os, json
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.db import Database
from core.registry import CapabilityRegistry
from core.memory import MemorySubsystem
from core.evolution import EvolutionModule

def main():
    print("━━━ Phase 4 Integration Test: Evolution + Benchmark ━━━\n")

    db = Database("data/agent_os.db")
    registry = CapabilityRegistry(db, scan_root="capabilities")
    registry.sync()
    memory = MemorySubsystem(db)
    evolution = EvolutionModule(db, registry, memory, benchmark_dir="benchmark")

    # ── Test 1: 检测演进需求 ──
    print("--- Test 1: Detect Evolution Needs ---")
    # 先制造一些失败案例（模拟同一缺陷出现3次）
    for i in range(4):
        memory.save_failure(
            "script.create", f"test_evolution_{i}",
            ["文本过短（20字符）", "文本重复率高（60%）"],
            {"goal": "test"},
        )

    candidates = evolution.detect_evolution_needed()
    print(f"  Evolution candidates: {len(candidates)}")
    for c in candidates:
        print(f"    {c['skill_name']:25s} | defect: {c['defect_pattern']:30s} | count: {c['count']} | action: {c['suggested_action'][:50]}")

    assert len(candidates) > 0, "Should detect evolution needs"

    # ── Test 2: 生成演进方案 ──
    print("\n--- Test 2: Generate Evolution Proposal ---")
    if candidates:
        proposal = evolution.generate_evolution_proposal(
            candidates[0]["skill_name"],
            candidates[0]["defect_pattern"]
        )
        print(f"  Skill: {proposal['skill_name']}")
        print(f"  Version: {proposal['current_version']} → {proposal['proposed_version']}")
        print(f"  Changes:")
        for ch in proposal["changes"]:
            print(f"    - {ch}")
        print(f"  Benchmark tests: {len(proposal['benchmark_tests'])}")
        for bt in proposal["benchmark_tests"]:
            print(f"    - {bt['test_id']}: {bt['description']}")

    # ── Test 3: 运行 Benchmark ──
    print("\n--- Test 3: Run Benchmark ---")
    bench_result = evolution.run_benchmark(
        "script.create",
        proposal["benchmark_tests"]
    )
    print(f"  Skill: {bench_result['skill_name']}")
    print(f"  Total tests: {bench_result['total_tests']}")
    print(f"  Passed: {bench_result['passed']}")
    print(f"  Failed: {bench_result['failed']}")
    print(f"  Avg score: {bench_result['avg_score']}")
    for r in bench_result["results"]:
        status = "✅" if r["passed"] else "❌"
        print(f"    {status} {r['test_id']:30s} score={r['score']:5.1f} ({r['duration_ms']}ms)")

    # ── Test 4: 保存 Benchmark 结果 ──
    print("\n--- Test 4: Save Benchmark Result ---")
    saved_path = evolution.save_benchmark_result(bench_result)
    print(f"  Saved to: {saved_path}")
    assert os.path.exists(saved_path)

    # ── Test 5: 版本对比 ──
    print("\n--- Test 5: Version Comparison ---")
    # 模拟旧版本结果
    old_result = {
        "skill_name": "script.create",
        "avg_score": 45.0,
            "passed": 1,
            "total_tests": 3,
    }
    comparison = evolution.compare_versions("script.create", old_result, bench_result)
    print(f"  Old avg score: {comparison['old_avg_score']}")
    print(f"  New avg score: {comparison['new_avg_score']}")
    print(f"  Score delta: {comparison['score_delta']:+.1f}")
    print(f"  Improved: {comparison['improved']}")
    print(f"  Recommendation: {comparison['recommendation']}")

    print("\n━━━ Phase 4 Integration Test PASSED ━━━")
    print(f"  Evolution module: detect ✅, propose ✅, benchmark ✅, save ✅, compare ✅")
    db.close()

if __name__ == "__main__":
    main()
