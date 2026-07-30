"""
SKILL.yaml 元数据规范 + JSON Schema 验证器

每个原子能力（AtomicCapability）目录下必须包含一个 SKILL.yaml 文件，
描述该能力的输入/输出契约、成本、评估指标、前置依赖等。

规范字段（必填）：
  name:           能力唯一标识（snake_case）
  version:        语义化版本号
  domain:         业务域 (video / mlops / investment / general)
  category:       能力分类 (perception / generation / evaluation / execution / ...)
  description:    一句话描述
  input_schema:   入参 JSON Schema
  output_schema:  出参 JSON Schema
  cost:           算力/Token 成本估算
    token_estimate: int
    latency_tier: "low" | "medium" | "high"
  evaluation:     评估指标依赖
    type: "text" | "image" | "audio" | "video" | "json" | "none"
    metrics: [str]  # 依赖哪些评估算子
  dependencies:   前置依赖技能名称列表

规范字段（选填）：
  hermes_tools:   对应的 Hermes 工具列表
  examples:       使用示例
  tags:            标签列表
"""

import json
import re
from pathlib import Path
from typing import Any, Optional, Union
import yaml

# ── JSON Schema for SKILL.yaml validation ──────────────────────────────

SKILL_YAML_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "AtomicCapability SKILL.yaml",
    "type": "object",
    "required": ["name", "version", "domain", "category", "description",
                 "input_schema", "output_schema", "cost", "evaluation", "dependencies"],
    "properties": {
        "name": {
            "type": "string",
            "pattern": r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$",
            "description": "能力唯一标识，snake_case，可含点号分层"
        },
        "version": {
            "type": "string",
            "pattern": r"^\d+\.\d+\.\d+$",
            "description": "语义化版本号"
        },
        "domain": {
            "type": "string",
            "enum": ["video", "mlops", "investment", "general"],
            "description": "业务域"
        },
        "category": {
            "type": "string",
            "enum": [
                "perception", "comprehension", "memory", "reasoning",
                "generation", "execution", "evaluation", "coordination",
                "safety", "verification", "evolution", "repair"
            ],
            "description": "能力分类"
        },
        "description": {
            "type": "string",
            "minLength": 5,
            "description": "一句话功能描述"
        },
        "input_schema": {
            "type": "object",
            "description": "入参 JSON Schema（Draft 2020-12）"
        },
        "output_schema": {
            "type": "object",
            "description": "出参 JSON Schema（Draft 2020-12）"
        },
        "cost": {
            "type": "object",
            "required": ["token_estimate", "latency_tier"],
            "properties": {
                "token_estimate": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "预估Token消耗（输入+输出总和）"
                },
                "latency_tier": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "延迟等级：low<5s, medium<30s, high>30s"
                },
                "price_cny": {
                    "type": "number",
                    "minimum": 0,
                    "description": "预估单次调用成本（元）"
                }
            }
        },
        "evaluation": {
            "type": "object",
            "required": ["type", "metrics"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["text", "image", "audio", "video", "json", "none"],
                    "description": "产出数据类型"
                },
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "依赖的评估算子列表"
                },
                "threshold": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "及格分数阈值（0-100）"
                }
            }
        },
        "dependencies": {
            "type": "array",
            "items": {"type": "string"},
            "description": "前置依赖技能名称列表（可为空）"
        },
        # ── 可选字段 ──
        "hermes_tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": "对应的 Hermes 工具列表"
        },
        "examples": {
            "type": "array",
            "items": {"type": "string"},
            "description": "使用示例"
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "标签列表"
        }
    },
    "additionalProperties": False
}


class SchemaValidationError(Exception):
    """SKILL.yaml 校验失败"""


def validate_skill_yaml(yaml_path: Union[str, Path]) -> dict[str, Any]:
    """
    加载并校验一个 SKILL.yaml 文件。
    返回解析后的 dict（校验通过）或抛出 SchemaValidationError。
    """
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise SchemaValidationError(f"SKILL.yaml not found: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        raise SchemaValidationError(f"SKILL.yaml is empty: {yaml_path}")

    errors: list[str] = []

    # ── 必填字段检查 ──
    for field in SKILL_YAML_SCHEMA["required"]:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    if errors:
        raise SchemaValidationError(
            f"SKILL.yaml validation failed for {yaml_path}:\n  - "
            + "\n  - ".join(errors)
        )

    # ── 字段类型检查（轻量级，不依赖 jsonschema 库）──
    # name pattern
    if not re.match(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$", data["name"]):
        errors.append(f"Invalid name pattern: {data['name']}")

    # version pattern
    if not re.match(r"^\d+\.\d+\.\d+$", str(data.get("version", ""))):
        errors.append(f"Invalid version: {data.get('version')}")

    # domain enum
    if data["domain"] not in ["video", "mlops", "investment", "general"]:
        errors.append(f"Invalid domain: {data['domain']}")

    # category enum
    valid_categories = {
        "perception", "comprehension", "memory", "reasoning",
        "generation", "execution", "evaluation", "coordination",
        "safety", "verification", "evolution", "repair"
    }
    if data["category"] not in valid_categories:
        errors.append(f"Invalid category: {data['category']}")

    # input_schema / output_schema must be objects
    for field in ["input_schema", "output_schema"]:
        if not isinstance(data.get(field), dict):
            errors.append(f"{field} must be an object (JSON Schema)")

    # cost
    cost = data.get("cost", {})
    if not isinstance(cost.get("token_estimate"), int):
        errors.append("cost.token_estimate must be int")
    if cost.get("latency_tier") not in ("low", "medium", "high"):
        errors.append(f"Invalid cost.latency_tier: {cost.get('latency_tier')}")

    # evaluation
    ev = data.get("evaluation", {})
    if ev.get("type") not in ("text", "image", "audio", "video", "json", "none"):
        errors.append(f"Invalid evaluation.type: {ev.get('type')}")
    if not isinstance(ev.get("metrics"), list):
        errors.append("evaluation.metrics must be a list")

    # dependencies must be list
    if not isinstance(data.get("dependencies"), list):
        errors.append("dependencies must be a list")

    if errors:
        raise SchemaValidationError(
            f"SKILL.yaml validation failed for {yaml_path}:\n  - "
            + "\n  - ".join(errors)
        )

    return data


def load_skill_yaml(yaml_path: Union[str, Path]) -> dict[str, Any]:
    """加载 SKILL.yaml（已校验）"""
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def create_skill_yaml_template(name: str, domain: str = "general") -> str:
    """生成一个 SKILL.yaml 模板字符串"""
    template = {
        "name": name,
        "version": "1.0.0",
        "domain": domain,
        "category": "generation",
        "description": "TODO: 一句话描述该原子能力",
        "input_schema": {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "输入参数"}
            },
            "required": ["input"]
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "output": {"type": "string", "description": "输出结果"}
            },
            "required": ["output"]
        },
        "cost": {
            "token_estimate": 1000,
            "latency_tier": "medium"
        },
        "evaluation": {
            "type": "text",
            "metrics": ["text.score"],
            "threshold": 70
        },
        "dependencies": []
    }
    return yaml.dump(template, allow_unicode=True, sort_keys=False)
