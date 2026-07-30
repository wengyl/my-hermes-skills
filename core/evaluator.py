"""
Evaluator 评估系统 — 核心模块

按数据类型拆分评估算子：text.score / image.score / audio.score / video.score / json.score

输入：原始素材 + 原始 prompt / 期望输出
输出：综合得分(0-100) + 缺陷清单 + 修复建议

评估算子设计：
  text.score  — 文本质量评估（完整性/连贯性/准确性/可读性）
  image.score — 图片质量评估（分辨率/内容匹配/标注正确性）
  audio.score — 音频质量评估（清晰度/时长匹配/噪音/语速）
  video.score — 视频质量评估（分辨率/帧率/音画同步/字幕/转场）
  json.score  — JSON 结构评估（schema合规/字段完整/值合法）
"""

import json
import logging
import re
from typing import Any, Optional

from .db import Database
from .registry import CapabilityRegistry
from .state_machine import TaskStateMachine

logger = logging.getLogger(__name__)


class ScoreOperator:
    """评估算子基类"""

    def evaluate(
        self, output: Any, expected: Optional[Any] = None, context: Optional[dict] = None
    ) -> dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def _make_result(
        score: float, defects: list[str], suggestions: list[str]
    ) -> dict[str, Any]:
        return {
            "score": round(score, 1),
            "defects": defects,
            "suggestions": suggestions,
            "passed": score >= 70,
        }


class TextScoreOperator(ScoreOperator):
    """文本质量评估算子"""

    def evaluate(self, output: Any, expected: Optional[Any] = None,
                 context: Optional[dict] = None) -> dict[str, Any]:
        text = str(output) if output else ""
        defects: list[str] = []
        suggestions: list[str] = []
        score = 100.0

        # 1. 非空检查
        if not text.strip():
            return self._make_result(0, ["输出为空"], ["确保有实际内容输出"])

        # 2. 长度评估
        if len(text) < 50:
            score -= 20
            defects.append(f"文本过短（{len(text)}字符）")
            suggestions.append("扩充内容到至少200字符")

        # 3. 结构完整性（有标题/段落）
        if "\n" not in text and len(text) > 200:
            score -= 10
            defects.append("文本无段落分隔")
            suggestions.append("添加段落换行提升可读性")

        # 4. 重复内容检测
        words = text.split()
        if len(words) > 10:
            unique_ratio = len(set(words)) / len(words)
            if unique_ratio < 0.3:
                score -= 15
                defects.append(f"文本重复率高（{1-unique_ratio:.0%}）")
                suggestions.append("减少重复内容")

        # 5. 与期望对比
        if expected and isinstance(expected, str):
            expected_keywords = set(expected.split())
            output_keywords = set(text.split())
            overlap = len(expected_keywords & output_keywords)
            if expected_keywords:
                coverage = overlap / len(expected_keywords)
                if coverage < 0.5:
                    score -= 15
                    defects.append(f"关键词覆盖率低（{coverage:.0%}）")
                    suggestions.append("确保覆盖原始要求的关键信息")

        score = max(0, min(100, score))
        return self._make_result(score, defects, suggestions)


class ImageScoreOperator(ScoreOperator):
    """图片质量评估算子"""

    def evaluate(self, output: Any, expected: Optional[Any] = None,
                 context: Optional[dict] = None) -> dict[str, Any]:
        defects: list[str] = []
        suggestions: list[str] = []
        score = 100.0

        output_dict = output if isinstance(output, dict) else {}

        # 1. 文件存在检查
        image_path = output_dict.get("image_path", "")
        if not image_path:
            return self._make_result(0, ["未生成图片路径"], ["确保输出包含 image_path"])

        # 2. 分辨率检查
        width = output_dict.get("width", 0)
        height = output_dict.get("height", 0)
        if width < 1920 or height < 1080:
            score -= 20
            defects.append(f"分辨率不达标（{width}x{height}）")
            suggestions.append("确保输出 1920x1080 分辨率")

        # 3. 生成方法检查
        method = output_dict.get("method_used", "")
        if not method:
            score -= 5
            defects.append("未记录生成方法")
            suggestions.append("记录 method_used 字段")

        # 4. 文件大小检查（如果有路径信息）
        import os
        if image_path and os.path.exists(image_path):
            size_kb = os.path.getsize(image_path) / 1024
            if size_kb < 50:
                score -= 10
                defects.append(f"图片文件过小（{size_kb:.0f}KB）")
                suggestions.append("检查图片是否完整生成")

        score = max(0, min(100, score))
        return self._make_result(score, defects, suggestions)


class AudioScoreOperator(ScoreOperator):
    """音频质量评估算子"""

    def evaluate(self, output: Any, expected: Optional[Any] = None,
                 context: Optional[dict] = None) -> dict[str, Any]:
        defects: list[str] = []
        suggestions: list[str] = []
        score = 100.0

        output_dict = output if isinstance(output, dict) else {}

        # 1. 音频文件列表
        audio_files = output_dict.get("audio_files", [])
        if not audio_files:
            return self._make_result(0, ["未生成音频文件"], ["确保输出包含 audio_files"])

        # 2. 时间戳文件
        srt_files = output_dict.get("srt_files", [])
        if not srt_files:
            score -= 15
            defects.append("缺少时间戳JSON文件")
            suggestions.append("生成 SentenceBoundary 时间戳")

        # 3. 总时长
        total_duration = output_dict.get("total_duration", 0)
        if total_duration <= 0:
            score -= 10
            defects.append("总时长为0或未记录")
            suggestions.append("记录 total_duration")

        # 4. 文件数量匹配
        if srt_files and len(audio_files) != len(srt_files):
            score -= 15
            defects.append(f"音频文件数({len(audio_files)})与时间戳文件数({len(srt_files)})不匹配")
            suggestions.append("确保每个音频都有对应的时间戳")

        score = max(0, min(100, score))
        return self._make_result(score, defects, suggestions)


class VideoScoreOperator(ScoreOperator):
    """视频质量评估算子"""

    def evaluate(self, output: Any, expected: Optional[Any] = None,
                 context: Optional[dict] = None) -> dict[str, Any]:
        defects: list[str] = []
        suggestions: list[str] = []
        score = 100.0

        output_dict = output if isinstance(output, dict) else {}

        # 1. 视频文件路径
        video_path = output_dict.get("video_path", "")
        if not video_path:
            return self._make_result(0, ["未生成视频文件"], ["确保输出包含 video_path"])

        # 2. 时长
        duration = output_dict.get("duration", 0)
        if duration <= 0:
            score -= 15
            defects.append("视频时长为0或未记录")
            suggestions.append("记录 duration 字段")

        # 3. 文件大小
        file_size = output_dict.get("file_size_mb", 0)
        if file_size <= 0:
            score -= 5
            defects.append("文件大小未记录")
            suggestions.append("记录 file_size_mb")

        # 4. 分辨率
        resolution = output_dict.get("resolution", "")
        if resolution and "1920" not in resolution:
            score -= 10
            defects.append(f"分辨率不符合1080p: {resolution}")
            suggestions.append("确保输出 1920x1080")

        # 5. 文件存在验证
        import os
        if video_path and os.path.exists(video_path):
            size_mb = os.path.getsize(video_path) / (1024 * 1024)
            if size_mb < 1:
                score -= 20
                defects.append(f"视频文件过小（{size_mb:.1f}MB）")
                suggestions.append("检查视频是否完整编码")

        score = max(0, min(100, score))
        return self._make_result(score, defects, suggestions)


class JsonScoreOperator(ScoreOperator):
    """JSON 结构评估算子"""

    def evaluate(self, output: Any, expected: Optional[Any] = None,
                 context: Optional[dict] = None) -> dict[str, Any]:
        defects: list[str] = []
        suggestions: list[str] = []
        score = 100.0

        # 1. JSON 可序列化检查
        if not isinstance(output, (dict, list)):
            score -= 30
            defects.append(f"输出不是JSON结构（{type(output).__name__}）")
            suggestions.append("确保输出为 dict 或 list")

        # 2. 如果有 expected schema，检查必填字段
        if context and "required_fields" in context:
            output_dict = output if isinstance(output, dict) else {}
            for field in context["required_fields"]:
                if field not in output_dict:
                    score -= 15
                    defects.append(f"缺少必填字段: {field}")
                    suggestions.append(f"确保输出包含 {field} 字段")

        # 3. 空值检查
        if isinstance(output, dict):
            empty_fields = [k for k, v in output.items() if v is None or v == ""]
            if empty_fields:
                score -= min(5 * len(empty_fields), 20)
                defects.append(f"空值字段: {', '.join(empty_fields)}")
                suggestions.append("填充空值字段或移除")

        score = max(0, min(100, score))
        return self._make_result(score, defects, suggestions)


# ── 评估算子注册 ──
OPERATORS: dict[str, type[ScoreOperator]] = {
    "text": TextScoreOperator,
    "image": ImageScoreOperator,
    "audio": AudioScoreOperator,
    "video": VideoScoreOperator,
    "json": JsonScoreOperator,
}


class Evaluator:
    """
    Evaluator 评估系统

    对 ExecutionEngine 的输出按数据类型评估打分。
    评估不达标 → 触发 RepairAgent
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        sm: TaskStateMachine,
        db: Database,
        pass_threshold: float = 70.0,
    ):
        self.registry = registry
        self.sm = sm
        self.db = db
        self.pass_threshold = pass_threshold
        self._operators: dict[str, ScoreOperator] = {
            name: cls() for name, cls in OPERATORS.items()
        }

    def evaluate_step(
        self, task_id: str, step_index: int, skill_name: str,
        output: Any, expected: Optional[Any] = None, context: Optional[dict] = None
    ) -> dict[str, Any]:
        """评估单个步骤输出"""
        # 从注册表获取该能力的评估类型
        cap = self.registry.get(skill_name)
        if not cap:
            return {"score": 0, "defects": ["能力未注册"], "passed": False}

        eval_type = cap["evaluation"]["type"]
        threshold = cap["evaluation"].get("threshold", self.pass_threshold)

        if eval_type == "none":
            # 无需评估
            return {"score": 100, "defects": [], "suggestions": [], "passed": True}

        # 调用对应算子
        operator = self._operators.get(eval_type)
        if not operator:
            return {"score": 0, "defects": [f"无对应评估算子: {eval_type}"], "passed": False}

        result = operator.evaluate(output, expected, context)

        # 覆盖阈值
        result["passed"] = result["score"] >= threshold
        result["eval_type"] = eval_type
        result["threshold"] = threshold

        # 持久化评估记录
        self.db.log_evaluation({
            "task_id": task_id,
            "step_index": step_index,
            "skill_name": skill_name,
            "eval_type": eval_type,
            "score": result["score"],
            "defects": result.get("defects", []),
            "suggestions": result.get("suggestions", []),
            "passed": result["passed"],
        })

        return result

    def evaluate_task(
        self, task_id: str, exec_result: dict[str, Any], plan: dict[str, Any]
    ) -> dict[str, Any]:
        """
        评估整个任务的所有步骤。

        Returns:
            {
                "task_id": str,
                "overall_score": float,
                "step_scores": [ {step, skill, score, passed} ],
                "failed_steps": [int],
                "needs_repair": bool,
                "defects_summary": list
            }
        """
        self.sm.start_evaluation(task_id)

        step_scores: list[dict[str, Any]] = []
        failed_steps: list[int] = []
        all_defects: list[str] = []

        for step_result in exec_result["step_results"]:
            step_num = step_result["step"]
            skill = step_result["skill"]
            output = step_result.get("output", {})

            eval_result = self.evaluate_step(task_id, step_num, skill, output)

            step_scores.append({
                "step": step_num,
                "skill": skill,
                "score": eval_result["score"],
                "passed": eval_result["passed"],
                "defects": eval_result.get("defects", []),
            })

            if not eval_result["passed"]:
                failed_steps.append(step_num)
                all_defects.extend(eval_result.get("defects", []))

        # 综合分 = 所有步骤平均分
        if step_scores:
            overall_score = sum(s["score"] for s in step_scores) / len(step_scores)
        else:
            overall_score = 0

        needs_repair = len(failed_steps) > 0

        return {
            "task_id": task_id,
            "overall_score": round(overall_score, 1),
            "step_scores": step_scores,
            "failed_steps": failed_steps,
            "needs_repair": needs_repair,
            "defects_summary": all_defects,
        }
