"""
Evolution 演进模块 — 自进化 Agent

收集持续失败案例 → 自动分析缺陷 → 生成技能迭代方案 → 灰度测试新版本

配套 Benchmark 测试集，版本迭代自动跑基准测试，量化得分变化。
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .db import Database
from .registry import CapabilityRegistry
from .memory import MemorySubsystem

logger = logging.getLogger(__name__)


class EvolutionModule:
    """
    Evolution 演进模块

    职责:
    1. 收集持续失败案例（同一技能反复失败 > 阈值）
    2. 分析失败模式，生成技能迭代方案
    3. 灰度测试新版本（与旧版本对比 Benchmark）
    4. 量化得分变化，决定是否推广
    5. 更新 CapabilityRegistry 中的版本号
    """

    def __init__(
        self,
        db: Database,
        registry: CapabilityRegistry,
        memory: MemorySubsystem,
        benchmark_dir: str = "benchmark",
    ):
        self.db = db
        self.registry = registry
        self.memory = memory
        self.benchmark_dir = Path(benchmark_dir)

        # 持续失败阈值：同一技能同一缺陷出现 N 次触发演进
        self.failure_threshold = 3

    def detect_evolution_needed(self) -> list[dict[str, Any]]:
        """
        扫描所有技能的失败模式，找出需要演进的技能。

        返回: [{ skill_name, defect_pattern, count, suggested_action }]
        """
        evolution_candidates: list[dict[str, Any]] = []
        caps = self.db.list_capabilities()

        for cap in caps:
            patterns = self.memory.get_failure_patterns(cap["name"])
            for p in patterns:
                if p["count"] >= self.failure_threshold:
                    # 同一缺陷出现 >= threshold 次 → 需要演进
                    suggested = self._suggest_evolution_action(cap["name"], p)
                    evolution_candidates.append({
                        "skill_name": cap["name"],
                        "defect_pattern": p["defect_pattern"],
                        "count": p["count"],
                        "last_seen": p.get("last_seen", ""),
                        "suggested_action": suggested,
                    })

        return evolution_candidates

    def _suggest_evolution_action(
        self, skill_name: str, pattern: dict[str, Any]
    ) -> str:
        """根据失败模式建议演进方向"""
        defect = pattern["defect_pattern"]

        if "分辨率" in defect or "图片" in defect:
            return f"优化 {skill_name} 的输出分辨率参数，确保 1920x1080"
        elif "时间戳" in defect or "音频" in defect:
            return f"优化 {skill_name} 的 TTS 引擎和 SentenceBoundary 捕获逻辑"
        elif "文本过短" in defect or "重复" in defect:
            return f"优化 {skill_name} 的 prompt 模板，增加最小长度约束和去重"
        elif "视频" in defect:
            return f"优化 {skill_name} 的 FFmpeg 编码参数和转场逻辑"
        elif "字段" in defect:
            return f"修复 {skill_name} 的输出 schema 约束"
        else:
            return f"分析 {skill_name} 的 runner.py 逻辑，针对 '{defect}' 改进"

    def generate_evolution_proposal(
        self, skill_name: str, defect_pattern: str
    ) -> dict[str, Any]:
        """
        生成技能迭代方案。

        Returns:
            {
                "skill_name": str,
                "current_version": str,
                "proposed_version": str,
                "defect_pattern": str,
                "changes": [str],
                "benchmark_tests": [str],
                "rollback_plan": str
            }
        """
        cap = self.registry.get(skill_name)
        if not cap:
            return {"error": f"Capability not found: {skill_name}"}

        current_version = cap["version"]
        # 版本号递增：patch +1
        parts = current_version.split(".")
        new_version = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"

        # 生成变更清单
        changes: list[str] = [
            f"针对缺陷 '{defect_pattern}' 优化 runner.py 执行逻辑",
            f"更新 SKILL.yaml 版本号 {current_version} → {new_version}",
            f"根据失败案例调整 input_schema / output_schema 约束",
        ]

        # 生成 Benchmark 测试用例
        benchmark_tests = self._generate_benchmark_tests(skill_name, defect_pattern)

        return {
            "skill_name": skill_name,
            "current_version": current_version,
            "proposed_version": new_version,
            "defect_pattern": defect_pattern,
            "changes": changes,
            "benchmark_tests": benchmark_tests,
            "rollback_plan": f"回退到 {current_version}，恢复 runner.py 和 SKILL.yaml",
            "timestamp": datetime.now().isoformat(),
        }

    def _generate_benchmark_tests(
        self, skill_name: str, defect_pattern: str
    ) -> list[dict[str, Any]]:
        """生成针对缺陷的 Benchmark 测试用例"""
        tests: list[dict[str, Any]] = []

        # 基础测试：确保原有功能不回归
        tests.append({
            "test_id": f"{skill_name}.regression",
            "description": "回归测试：确保原有功能正常",
            "input": {"test": True, "regression": True},
            "expected_pass_score": 70,
        })

        # 针对缺陷的专项测试
        tests.append({
            "test_id": f"{skill_name}.fix_{defect_pattern[:20]}",
            "description": f"专项测试：验证 '{defect_pattern}' 已修复",
            "input": {"test": True, "defect": defect_pattern},
            "expected_pass_score": 80,
        })

        return tests

    def run_benchmark(
        self, skill_name: str, test_cases: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        运行 Benchmark 测试。

        Returns:
            {
                "skill_name": str,
                "total_tests": int,
                "passed": int,
                "failed": int,
                "avg_score": float,
                "results": [ {test_id, passed, score, duration_ms} ]
            }
        """
        results: list[dict[str, Any]] = []
        passed = 0
        total_score = 0

        for tc in test_cases:
            test_id = tc["test_id"]
            expected_score = tc.get("expected_pass_score", 70)

            start = time.time()
            try:
                module = self.registry.load_runner(skill_name)
                output = module.execute(tc.get("input", {}))

                # 评估输出
                from .evaluator import Evaluator
                evaluator = Evaluator(self.registry, None, self.db)  # sm=None for benchmark
                eval_result = evaluator.evaluate_step(
                    "benchmark", 0, skill_name, output
                )

                score = eval_result["score"]
                is_pass = score >= expected_score
                if is_pass:
                    passed += 1
                total_score += score

                results.append({
                    "test_id": test_id,
                    "passed": is_pass,
                    "score": score,
                    "duration_ms": int((time.time() - start) * 1000),
                })

            except Exception as e:
                results.append({
                    "test_id": test_id,
                    "passed": False,
                    "score": 0,
                    "error": str(e),
                    "duration_ms": int((time.time() - start) * 1000),
                })

        return {
            "skill_name": skill_name,
            "total_tests": len(test_cases),
            "passed": passed,
            "failed": len(test_cases) - passed,
            "avg_score": round(total_score / len(test_cases), 1) if test_cases else 0,
            "results": results,
        }

    def save_benchmark_result(self, result: dict[str, Any]):
        """保存 Benchmark 结果到文件"""
        bench_dir = self.benchmark_dir
        bench_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        skill = result.get("skill_name", "unknown")
        filename = f"{timestamp}_{skill}_benchmark.json"
        filepath = bench_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"Benchmark result saved: {filepath}")
        return str(filepath)

    def compare_versions(
        self, skill_name: str, old_result: dict[str, Any], new_result: dict[str, Any]
    ) -> dict[str, Any]:
        """对比新旧版本 Benchmark 结果"""
        score_delta = new_result["avg_score"] - old_result["avg_score"]
        pass_delta = new_result["passed"] - old_result["passed"]

        return {
            "skill_name": skill_name,
            "old_avg_score": old_result["avg_score"],
            "new_avg_score": new_result["avg_score"],
            "score_delta": round(score_delta, 1),
            "pass_delta": pass_delta,
            "improved": score_delta > 0,
            "recommendation": (
                "推广新版本" if score_delta > 0
                else "保持原版本" if score_delta == 0
                else "回退到原版本"
            ),
        }
