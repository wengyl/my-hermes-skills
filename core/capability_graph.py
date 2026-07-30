"""
Capability Graph — 能力图谱 (P1)

从 Registry 的扁平列表升级为有结构的能力图谱：
  - 节点：每个原子能力是一个节点
  - 边：依赖关系（dependencies）、输出-输入衔接（producer-consumer）、替代关系（alternatives）
  - 目标映射：goal pattern → 所需能力链路

核心数据结构：
  capability_graph = {
      "nodes": {name: {cap_meta, inputs, outputs, ...}},
      "edges": {
          "depends_on": [(from, to, reason)],
          "produces_for": [(producer, consumer, field)],
          "alternative_to": [(cap_a, cap_b, reason)],
      },
      "goal_patterns": {
          "投资诊断": {capabilities: [...], path: [...]},
          "视频制作": {capabilities: [...], path: [...]},
      }
  }

使用场景：
  1. Planner 规划时查询最优路径
  2. 发现缺失能力（图中断点）
  3. 发现冗余能力（可替代的平行节点）
  4. 能力推荐（给定目标，推荐最优能力组合）
"""

import json
import logging
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Optional

import yaml

from .db import Database
from .registry import CapabilityRegistry

logger = logging.getLogger(__name__)


class CapabilityGraph:
    """
    能力图谱 — 结构化能力关系网络

    构建3种边：
      1. depends_on: A 的 dependencies 中包含 B → A depends_on B
      2. produces_for: A 的 output_schema 字段匹配 B 的 input_schema 字段 → A produces_for B
      3. alternative_to: 同 domain+category 的能力互为替代
    """

    def __init__(self, registry: CapabilityRegistry, db: Database):
        self.registry = registry
        self.db = db
        self.graph: dict[str, Any] = {
            "nodes": {},
            "edges": {"depends_on": [], "produces_for": [], "alternative_to": []},
            "goal_patterns": {},
        }
        self._build_graph()

    def _build_graph(self):
        """从注册表构建完整能力图谱"""
        caps = self.db.list_capabilities()

        # 构建节点
        for cap in caps:
            self.graph["nodes"][cap["name"]] = {
                "name": cap["name"],
                "version": cap["version"],
                "domain": cap["domain"],
                "category": cap["category"],
                "description": cap["description"],
                "inputs": self._extract_fields(cap.get("input_schema", {})),
                "outputs": self._extract_fields(cap.get("output_schema", {})),
                "dependencies": cap.get("dependencies", []),
                "cost": cap.get("cost", {}),
                "evaluation": cap.get("evaluation", {}),
            }

        # 构建边
        self._build_dependency_edges(caps)
        self._build_producer_consumer_edges(caps)
        self._build_alternative_edges(caps)

        # 构建目标模式
        self._build_goal_patterns()

        logger.info(
            f"Capability graph built: {len(self.graph['nodes'])} nodes, "
            f"{len(self.graph['edges']['depends_on'])} dep edges, "
            f"{len(self.graph['edges']['produces_for'])} prod edges, "
            f"{len(self.graph['edges']['alternative_to'])} alt edges"
        )

    def _extract_fields(self, schema: dict) -> list[str]:
        """从 JSON Schema 提取字段名"""
        if not schema:
            return []
        props = schema.get("properties", {})
        return list(props.keys())

    def _build_dependency_edges(self, caps: list[dict]):
        """构建依赖边"""
        for cap in caps:
            for dep in cap.get("dependencies", []):
                if dep in self.graph["nodes"]:
                    self.graph["edges"]["depends_on"].append({
                        "from": cap["name"],
                        "to": dep,
                        "type": "hard_dependency",
                    })

    def _build_producer_consumer_edges(self, caps: list[dict]):
        """构建生产者-消费者边（输出字段匹配输入字段）"""
        for producer in caps:
            p_outputs = self._extract_fields(producer.get("output_schema", {}))
            for consumer in caps:
                if consumer["name"] == producer["name"]:
                    continue
                c_inputs = self._extract_fields(consumer.get("input_schema", {}))
                # 找字段交集
                shared = set(p_outputs) & set(c_inputs)
                if shared:
                    self.graph["edges"]["produces_for"].append({
                        "from": producer["name"],
                        "to": consumer["name"],
                        "shared_fields": list(shared),
                    })

    def _build_alternative_edges(self, caps: list[dict]):
        """构建替代边（同域同类别）"""
        by_domain_category: dict[str, list[str]] = defaultdict(list)
        for cap in caps:
            key = f"{cap['domain']}/{cap['category']}"
            by_domain_category[key].append(cap["name"])

        for key, names in by_domain_category.items():
            if len(names) > 1:
                for i, a in enumerate(names):
                    for b in names[i + 1:]:
                        self.graph["edges"]["alternative_to"].append({
                            "from": a,
                            "to": b,
                            "reason": f"同域同类别替代: {key}",
                        })

    def _build_goal_patterns(self):
        """构建目标→能力链路映射"""
        # 基于已知的领域流水线
        goal_patterns = {
            "投资诊断": {
                "keywords": ["基金", "投资", "组合", "持仓", "诊断", "调仓"],
                "domain": "investment",
                "capabilities": [
                    "data.fetch", "portfolio.analyze", "fund.diagnose",
                    "strategy.generate", "report.generate"
                ],
            },
            "视频制作": {
                "keywords": ["视频", "讲解视频", "文档转视频", "AI视频", "配音", "字幕"],
                "domain": "video",
                "capabilities": [
                    "script.create", "script.review", "storyboard.create",
                    "scene.plan", "image.generate", "image.evaluate",
                    "voice.generate", "voice.align", "subtitle.generate",
                    "video.compose", "video.evaluate"
                ],
            },
            "模型部署": {
                "keywords": ["模型", "部署", "推理", "服务", "serve", "vllm"],
                "domain": "mlops",
                "capabilities": [
                    "model.search", "model.load", "model.evaluate", "model.serve"
                ],
            },
        }

        # 为每个目标模式验证能力存在性
        for pattern_name, pattern in goal_patterns.items():
            valid_caps = []
            for cap_name in pattern["capabilities"]:
                if cap_name in self.graph["nodes"]:
                    valid_caps.append(cap_name)
                else:
                    logger.warning(f"Goal pattern '{pattern_name}' references missing capability: {cap_name}")

            # 计算最优路径（拓扑排序）
            path = self._compute_path(valid_caps)

            self.graph["goal_patterns"][pattern_name] = {
                "keywords": pattern["keywords"],
                "domain": pattern["domain"],
                "capabilities": valid_caps,
                "optimal_path": path,
            }

    def _compute_path(self, cap_names: list[str]) -> list[str]:
        """计算能力的拓扑排序路径"""
        return self.registry.get_execution_order(cap_names)

    def query_capabilities_for_goal(self, goal: str) -> dict[str, Any]:
        """
        给定目标，推荐最优能力组合

        Returns:
            {
                "matched_pattern": str,
                "domain": str,
                "capabilities": [str],
                "optimal_path": [str],
                "parallel_groups": [[str]],
                "missing_capabilities": [str],
            }
        """
        goal_lower = goal.lower()
        best_pattern = None
        best_score = 0

        for name, pattern in self.graph["goal_patterns"].items():
            score = sum(1 for kw in pattern["keywords"] if kw.lower() in goal_lower)
            if score > best_score:
                best_score = score
                best_pattern = name

        if not best_pattern or best_score == 0:
            return {
                "matched_pattern": None,
                "domain": "general",
                "capabilities": [],
                "optimal_path": [],
                "parallel_groups": [],
                "missing_capabilities": [],
            }

        pattern = self.graph["goal_patterns"][best_pattern]

        # 检测缺失能力
        missing = [
            cap for cap in pattern["capabilities"]
            if cap not in self.graph["nodes"]
        ]

        # 计算并行组
        parallel_groups = self._find_parallel_groups(pattern["optimal_path"])

        return {
            "matched_pattern": best_pattern,
            "domain": pattern["domain"],
            "capabilities": pattern["capabilities"],
            "optimal_path": pattern["optimal_path"],
            "parallel_groups": parallel_groups,
            "missing_capabilities": missing,
        }

    def _find_parallel_groups(self, path: list[str]) -> list[list[str]]:
        """在路径中找出可并行执行的能力组"""
        groups: list[list[str]] = []
        visited: set[str] = set()

        for cap_name in path:
            deps = self.graph["nodes"].get(cap_name, {}).get("dependencies", [])
            # 如果所有依赖都已visited，可以加入当前组
            unmet = [d for d in deps if d not in visited and d in path]
            if not unmet:
                # 检查是否有替代关系
                alts = [
                    e for e in self.graph["edges"]["alternative_to"]
                    if e["from"] == cap_name or e["to"] == cap_name
                ]
                if alts and not visited:
                    groups.append([cap_name])
                else:
                    groups.append([cap_name])
            visited.add(cap_name)

        # 简化：返回独立的并行标记
        # 实际并行需要更精细的依赖分析
        return groups

    def find_gaps(self) -> list[dict[str, Any]]:
        """
        发现能力图谱中的断点
          - 被依赖但不存在的能力
          - 无消费者的重要输出
          - 孤立节点（无依赖无被依赖）
        """
        gaps: list[dict[str, Any]] = []

        # 被引用但不存在的能力
        for node_name, node in self.graph["nodes"].items():
            for dep in node.get("dependencies", []):
                if dep not in self.graph["nodes"]:
                    gaps.append({
                        "type": "missing_dependency",
                        "capability": node_name,
                        "missing": dep,
                    })

        # 孤立节点
        all_dep_from = {e["from"] for e in self.graph["edges"]["depends_on"]}
        all_dep_to = {e["to"] for e in self.graph["edges"]["depends_on"]}
        all_prod_from = {e["from"] for e in self.graph["edges"]["produces_for"]}
        all_prod_to = {e["to"] for e in self.graph["edges"]["produces_for"]}

        for node_name in self.graph["nodes"]:
            is_isolated = (
                node_name not in all_dep_from and
                node_name not in all_dep_to and
                node_name not in all_prod_from and
                node_name not in all_prod_to
            )
            if is_isolated:
                gaps.append({
                    "type": "isolated_node",
                    "capability": node_name,
                })

        return gaps

    def export_graph(self, output_path: str):
        """导出图谱为JSON"""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.graph, f, ensure_ascii=False, indent=2)
        return output_path

    def get_graph_summary(self) -> dict[str, Any]:
        return {
            "total_nodes": len(self.graph["nodes"]),
            "total_edges": {
                "depends_on": len(self.graph["edges"]["depends_on"]),
                "produces_for": len(self.graph["edges"]["produces_for"]),
                "alternative_to": len(self.graph["edges"]["alternative_to"]),
            },
            "goal_patterns": list(self.graph["goal_patterns"].keys()),
            "domains": list(set(n["domain"] for n in self.graph["nodes"].values())),
        }
