"""
Reflection Engine — 任务后反思钩子 + 知识沉淀管道

核心理念：不直接修改生产Skill，而是走 Candidate → Validate → Approve → Merge 管道

触发时机：每次任务完成后自动触发
输出去向：
  - 成功经验 → knowledge/cases/ (案例库)
  - 失败分析 → knowledge/failures/ (失败案例)
  - 新规则候选 → knowledge/.candidates/ (待验证)
  - 统计数据 → Memory (跨会话持久)
  - Skill更新建议 → knowledge/.candidates/skill_updates/ (待人工审批)

管道流程：
  Task Completed
    → Reflection Trigger
    → 分析: 成功因素 / 失败因素 / 用户反馈
    → 生成: Lesson Learned (candidate)
    → 保存到 .candidates/
    → [等待验证/审批]
    → 合并到 production knowledge/
    → 或 合并到 Hermes Skill (通过 skill_manage)
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from .db import Database
from .registry import CapabilityRegistry
from .memory import MemorySubsystem

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """
    Reflection Engine — 增强层核心组件

    与Hermes的关系：
    - 不替代Hermes的推理/学习循环
    - 在任务完成后提供结构化反思 → 沉淀为知识
    - 所有知识修改走候选管道，不直接改生产Skill
    """

    def __init__(
        self,
        db: Database,
        registry: CapabilityRegistry,
        memory: MemorySubsystem,
        knowledge_dir: str = "knowledge",
    ):
        self.db = db
        self.registry = registry
        self.memory = memory
        self.knowledge_dir = Path(knowledge_dir)
        self.candidates_dir = self.knowledge_dir / ".candidates"
        self.candidates_dir.mkdir(parents=True, exist_ok=True)

    def reflect(
        self,
        task_id: str,
        goal: str,
        plan: dict[str, Any],
        exec_result: dict[str, Any],
        eval_result: dict[str, Any],
        repair_result: Optional[dict[str, Any]] = None,
        user_feedback: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        任务完成后触发反思。

        Args:
            task_id: 任务ID
            goal: 用户目标
            plan: 执行计划
            exec_result: 执行结果
            eval_result: 评估结果
            repair_result: 修复结果（如有）
            user_feedback: 用户反馈（如有）

        Returns:
            反思报告 {
                task_id, success_factors, failure_factors,
                lessons_learned, candidates_generated, recommendations
            }
        """
        reflection = {
            "task_id": task_id,
            "goal": goal,
            "domain": plan.get("domain", "general"),
            "timestamp": datetime.now().isoformat(),
            "overall_score": eval_result.get("overall_score", 0),
            "success_factors": [],
            "failure_factors": [],
            "lessons_learned": [],
            "candidates_generated": [],
            "recommendations": [],
        }

        # ── 1. 分析成功因素 ──
        for step_score in eval_result.get("step_scores", []):
            if step_score.get("passed") and step_score.get("score", 0) >= 85:
                reflection["success_factors"].append({
                    "step": step_score["step"],
                    "skill": step_score["skill"],
                    "score": step_score["score"],
                    "factor": f"{step_score['skill']} 表现优秀",
                })

        # ── 2. 分析失败因素 ──
        for step_score in eval_result.get("step_scores", []):
            if not step_score.get("passed"):
                defects = step_score.get("defects", [])
                reflection["failure_factors"].append({
                    "step": step_score["step"],
                    "skill": step_score["skill"],
                    "score": step_score["score"],
                    "defects": defects,
                    "repaired": bool(
                        repair_result and repair_result.get("repaired")
                    ),
                })

        # ── 3. 分析修复效果 ──
        if repair_result:
            if repair_result.get("repaired"):
                reflection["success_factors"].append({
                    "step": -1,
                    "skill": "repair_agent",
                    "score": 100,
                    "factor": f"自动修复成功（{len(repair_result.get('new_scores', []))}步恢复）",
                })
            else:
                reflection["failure_factors"].append({
                    "step": -1,
                    "skill": "repair_agent",
                    "score": 0,
                    "defects": ["自动修复未能完全恢复所有失败步骤"],
                    "repaired": False,
                })

        # ── 4. 分析用户反馈 ──
        if user_feedback:
            rating = user_feedback.get("rating", 0)
            if rating >= 4:
                reflection["success_factors"].append({
                    "step": 0,
                    "skill": "user_satisfaction",
                    "score": rating * 20,
                    "factor": user_feedback.get("comment", "用户满意"),
                })
            elif rating <= 2 and rating > 0:
                reflection["failure_factors"].append({
                    "step": 0,
                    "skill": "user_satisfaction",
                    "score": rating * 20,
                    "defects": [user_feedback.get("comment", "用户不满意")],
                    "repaired": False,
                })

        # ── 5. 生成 Lessons Learned ──
        reflection["lessons_learned"] = self._extract_lessons(reflection)

        # ── 6. 生成知识候选 ──
        reflection["candidates_generated"] = self._generate_candidates(reflection)

        # ── 7. 生成改进建议 ──
        reflection["recommendations"] = self._generate_recommendations(reflection)

        # ── 8. 持久化反思记录 ──
        self._save_reflection(reflection)

        return reflection

    def _extract_lessons(self, reflection: dict) -> list[str]:
        """从反思中提取经验教训"""
        lessons = []
        domain = reflection["domain"]

        for failure in reflection["failure_factors"]:
            skill = failure["skill"]
            defects = failure.get("defects", [])
            for defect in defects:
                lessons.append(
                    f"[{domain}] {skill}: {defect} → "
                    f"{'已自动修复' if failure.get('repaired') else '需关注'}"
                )

        for success in reflection["success_factors"]:
            if success["skill"] != "user_satisfaction":
                lessons.append(
                    f"[{domain}] {success['skill']}: {success['factor']} (score={success['score']})"
                )

        return lessons

    def _generate_candidates(self, reflection: dict) -> list[dict[str, Any]]:
        """
        生成知识候选 — 写入 .candidates/ 目录，等待验证

        候选类型：
          - best_practice_candidate: 新最佳实践规则
          - failure_pattern_candidate: 新失败模式
          - skill_update_candidate: Skill更新建议
        """
        candidates = []
        domain = reflection["domain"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for failure in reflection["failure_factors"]:
            skill = failure["skill"]
            for defect in failure.get("defects", []):
                candidate_id = f"{timestamp}_{domain}_{skill}_{hash(defect) % 10000}"

                candidate = {
                    "candidate_id": candidate_id,
                    "type": "failure_pattern_candidate",
                    "domain": domain,
                    "skill": skill,
                    "defect_pattern": defect,
                    "task_id": reflection["task_id"],
                    "score": failure["score"],
                    "repaired": failure.get("repaired", False),
                    "status": "pending_validation",
                    "created_at": datetime.now().isoformat(),
                }

                # 写入候选文件
                candidate_path = self.candidates_dir / f"{candidate_id}.yaml"
                with open(candidate_path, "w", encoding="utf-8") as f:
                    yaml.dump(candidate, f, allow_unicode=True, sort_keys=False)

                candidates.append({
                    "candidate_id": candidate_id,
                    "type": candidate["type"],
                    "path": str(candidate_path),
                    "status": "pending_validation",
                })

        # 高分成功 → 最佳实践候选
        if reflection["overall_score"] >= 85 and reflection["success_factors"]:
            candidate_id = f"{timestamp}_{domain}_best_practice"
            candidate = {
                "candidate_id": candidate_id,
                "type": "best_practice_candidate",
                "domain": domain,
                "score": reflection["overall_score"],
                "success_factors": [
                    f["factor"] for f in reflection["success_factors"]
                ],
                "task_id": reflection["task_id"],
                "goal": reflection["goal"],
                "status": "pending_validation",
                "created_at": datetime.now().isoformat(),
            }

            candidate_path = self.candidates_dir / f"{candidate_id}.yaml"
            with open(candidate_path, "w", encoding="utf-8") as f:
                yaml.dump(candidate, f, allow_unicode=True, sort_keys=False)

            candidates.append({
                "candidate_id": candidate_id,
                "type": candidate["type"],
                "path": str(candidate_path),
                "status": "pending_validation",
            })

        return candidates

    def _generate_recommendations(self, reflection: dict) -> list[str]:
        """生成改进建议（供Hermes Agent读取参考）"""
        recs = []

        for failure in reflection["failure_factors"]:
            if not failure.get("repaired"):
                recs.append(
                    f"建议检查 {failure['skill']} 的 runner.py，"
                    f"针对缺陷 {failure.get('defects', [])} 优化执行逻辑"
                )

        if reflection["overall_score"] >= 90:
            recs.append(
                f"任务表现优秀(score={reflection['overall_score']})，"
                "考虑将成功经验提炼为新的 best_practice 规则"
            )

        return recs

    def _save_reflection(self, reflection: dict):
        """持久化反思记录到数据库 Memory"""
        self.memory.db.store_memory(
            "reflection",
            f"reflection:{reflection['task_id']}",
            reflection,
            task_id=reflection["task_id"],
        )
        logger.info(
            f"Reflection saved: task={reflection['task_id']}, "
            f"score={reflection['overall_score']}, "
            f"candidates={len(reflection['candidates_generated'])}"
        )

    # ── 候选管道管理 ──

    def list_candidates(self, status: str = "pending_validation") -> list[dict]:
        """列出所有待处理的知识候选"""
        candidates = []
        for f in sorted(self.candidates_dir.glob("*.yaml")):
            with open(f, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if data.get("status") == status:
                    candidates.append(data)
        return candidates

    def approve_candidate(self, candidate_id: str) -> dict[str, Any]:
        """
        审批通过一个候选 → 合并到生产知识

        根据候选类型路由：
          - failure_pattern_candidate → knowledge/failures/{domain}/common_failures.yaml
          - best_practice_candidate → knowledge/best_practices/{domain}/
          - skill_update_candidate → 通过 skill_manage 更新 Hermes Skill
        """
        candidate_path = self.candidates_dir / f"{candidate_id}.yaml"
        if not candidate_path.exists():
            return {"error": f"Candidate not found: {candidate_id}"}

        with open(candidate_path, "r", encoding="utf-8") as f:
            candidate = yaml.safe_load(f)

        result: dict[str, Any] = {"candidate_id": candidate_id, "merged": False}

        ctype = candidate["type"]
        domain = candidate.get("domain", "general")

        if ctype == "failure_pattern_candidate":
            self._merge_failure_pattern(candidate, domain)
            result["merged"] = True
            result["target"] = f"knowledge/failures/{domain}/common_failures.yaml"

        elif ctype == "best_practice_candidate":
            self._merge_best_practice(candidate, domain)
            result["merged"] = True
            result["target"] = f"knowledge/best_practices/{domain}/"

        elif ctype == "skill_update_candidate":
            result["merged"] = False
            result["target"] = "hermes_skill (requires manual skill_manage call)"
            result["note"] = "Skill updates require explicit skill_manage action"

        # 标记候选为已合并
        candidate["status"] = "approved_merged"
        candidate["merged_at"] = datetime.now().isoformat()
        with open(candidate_path, "w", encoding="utf-8") as f:
            yaml.dump(candidate, f, allow_unicode=True, sort_keys=False)

        logger.info(f"Candidate {candidate_id} approved and merged: {result}")
        return result

    def reject_candidate(self, candidate_id: str, reason: str = "") -> dict:
        """拒绝一个候选"""
        candidate_path = self.candidates_dir / f"{candidate_id}.yaml"
        if not candidate_path.exists():
            return {"error": f"Candidate not found: {candidate_id}"}

        with open(candidate_path, "r", encoding="utf-8") as f:
            candidate = yaml.safe_load(f)

        candidate["status"] = "rejected"
        candidate["rejected_reason"] = reason
        candidate["rejected_at"] = datetime.now().isoformat()

        with open(candidate_path, "w", encoding="utf-8") as f:
            yaml.dump(candidate, f, allow_unicode=True, sort_keys=False)

        return {"candidate_id": candidate_id, "status": "rejected"}

    def _merge_failure_pattern(self, candidate: dict, domain: str):
        """合并失败模式到生产知识"""
        failures_file = self.knowledge_dir / "failures" / domain / "common_failures.yaml"
        failures_file.parent.mkdir(parents=True, exist_ok=True)

        if failures_file.exists():
            with open(failures_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {"domain": domain, "failures": []}
        else:
            data = {"domain": domain, "failures": []}

        # 查找是否已有相同pattern
        existing = None
        for fail in data.get("failures", []):
            if fail.get("pattern") == candidate["defect_pattern"]:
                existing = fail
                break

        if existing:
            existing["occurrence_count"] = existing.get("occurrence_count", 0) + 1
            existing["status"] = "resolved" if candidate.get("repaired") else "unresolved"
        else:
            data["failures"].append({
                "id": f"FAIL-{candidate['candidate_id'][-4:]}",
                "skill": candidate["skill"],
                "pattern": candidate["defect_pattern"],
                "root_cause": "pending analysis",
                "solution": "pending" if not candidate.get("repaired") else "auto-repaired",
                "occurrence_count": 1,
                "status": "resolved" if candidate.get("repaired") else "unresolved",
            })

        data["last_updated"] = datetime.now().strftime("%Y-%m-%d")

        with open(failures_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    def _merge_best_practice(self, candidate: dict, domain: str):
        """合并最佳实践到生产知识"""
        bp_dir = self.knowledge_dir / "best_practices" / domain
        bp_dir.mkdir(parents=True, exist_ok=True)

        bp_file = bp_dir / f"{candidate['candidate_id']}.yaml"
        bp_data = {
            "id": candidate["candidate_id"],
            "domain": domain,
            "when": candidate.get("goal", "general task"),
            "confidence": min(0.5 + candidate.get("score", 0) / 200, 0.95),
            "source": "reflection_engine",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "rules": [
                {"id": f"rule_{i}", "rule": factor, "enforcement": "soft"}
                for i, factor in enumerate(candidate.get("success_factors", []))
            ],
        }

        with open(bp_file, "w", encoding="utf-8") as f:
            yaml.dump(bp_data, f, allow_unicode=True, sort_keys=False)

    def auto_validate_candidates(self) -> dict[str, Any]:
        """
        自动验证候选：同一缺陷出现 >=3 次自动批准合并到失败案例库
        （best_practice候选始终需要人工审批）
        """
        pending = self.list_candidates("pending_validation")
        auto_approved = []

        for candidate in pending:
            if candidate["type"] != "failure_pattern_candidate":
                continue

            # 检查同一skill+defect的历史出现次数
            skill = candidate["skill"]
            defect = candidate["defect_pattern"]
            patterns = self.memory.get_failure_patterns(skill)

            for p in patterns:
                if p["defect_pattern"] == defect and p["count"] >= 3:
                    result = self.approve_candidate(candidate["candidate_id"])
                    auto_approved.append(result)
                    break

        return {
            "auto_approved": auto_approved,
            "total_pending": len(pending),
            "total_auto_approved": len(auto_approved),
        }
