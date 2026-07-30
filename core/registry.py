"""
CapabilityRegistry — 能力注册中心

系统启动时自动扫描 capabilities/ 下所有 SKILL.yaml，
构建结构化能力索引，同步到 SQLite。
Planner 规划阶段读取注册表动态挑选可用能力。
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import yaml

from .db import Database
from .schema import validate_skill_yaml, SchemaValidationError

logger = logging.getLogger(__name__)

# 默认能力扫描根目录
DEFAULT_SCAN_ROOT = "capabilities"


class CapabilityRegistry:
    """
    能力注册中心。

    - scan(): 遍历 capabilities/ 下所有子目录，发现 SKILL.yaml 并校验
    - sync(): 将校验通过的能力元数据写入 SQLite
    - query(): 按 domain/category/dependencies 查询可用能力
    - get(): 获取单个能力详情
    - build_index(): 构建内存索引供 Planner 高速查询
    """

    def __init__(self, db: Database, scan_root: str = DEFAULT_SCAN_ROOT):
        self.db = db
        self.scan_root = Path(scan_root)
        self._index: dict[str, dict[str, Any]] = {}  # name → capability dict

    def scan(self) -> dict[str, Any]:
        """
        扫描 scan_root 下所有含 SKILL.yaml 的子目录，
        校验元数据，返回扫描结果报告。
        """
        results = {"scanned": 0, "valid": 0, "invalid": 0, "errors": [], "capabilities": []}

        if not self.scan_root.exists():
            logger.warning(f"Scan root not found: {self.scan_root}")
            return results

        # 遍历所有子目录（支持多级嵌套）
        for skill_yaml_path in sorted(self.scan_root.rglob("SKILL.yaml")):
            results["scanned"] += 1
            try:
                cap_data = validate_skill_yaml(skill_yaml_path)
                # 附加 skill_dir 字段（runner.py 所在目录）
                cap_data["skill_dir"] = str(skill_yaml_path.parent)
                results["capabilities"].append(cap_data)
                results["valid"] += 1
                logger.debug(f"✅ Valid: {cap_data['name']} @ {skill_yaml_path}")
            except SchemaValidationError as e:
                results["invalid"] += 1
                error_msg = str(e)
                results["errors"].append({
                    "file": str(skill_yaml_path),
                    "error": error_msg
                })
                logger.warning(f"❌ Invalid: {skill_yaml_path}\n  {error_msg}")

        return results

    def sync(self) -> dict[str, Any]:
        """
        扫描 + 同步到 SQLite。返回扫描报告。
        """
        report = self.scan()

        for cap_data in report["capabilities"]:
            self.db.upsert_capability(cap_data)
            self._index[cap_data["name"]] = cap_data

        logger.info(
            f"Registry synced: {report['valid']} valid, "
            f"{report['invalid']} invalid, "
            f"{len(self._index)} total indexed"
        )
        return report

    def build_index(self) -> dict[str, dict[str, Any]]:
        """从 SQLite 重新加载全部能力到内存索引"""
        caps = self.db.list_capabilities()
        self._index = {cap["name"]: cap for cap in caps}
        return self._index

    def get(self, name: str) -> Optional[dict]:
        """获取单个能力详情"""
        if name in self._index:
            return self._index[name]
        cap = self.db.get_capability(name)
        if cap:
            self._index[name] = cap
        return cap

    def query(
        self,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[list] = None,
    ) -> list[dict[str, Any]]:
        """按条件查询能力列表"""
        caps = list(self._index.values())

        if domain:
            caps = [c for c in caps if c["domain"] == domain]
        if category:
            caps = [c for c in caps if c["category"] == category]
        if tags:
            caps = [c for c in caps if any(t in c.get("tags", []) for t in tags)]

        return sorted(caps, key=lambda c: c["name"])

    def get_by_dependency(self, skill_name: str) -> list[dict[str, Any]]:
        """查找所有依赖某个技能的能力"""
        return [
            cap for cap in self._index.values()
            if skill_name in cap.get("dependencies", [])
        ]

    def get_execution_order(self, skill_names: list[str]) -> list[str]:
        """
        拓扑排序：根据 dependencies 排出执行顺序。
        被依赖的技能排前面。
        """
        # 构建依赖图
        graph: dict[str, list[str]] = {}
        for name in skill_names:
            cap = self.get(name)
            if cap:
                deps = [d for d in cap.get("dependencies", []) if d in skill_names]
                graph[name] = deps
            else:
                graph[name] = []

        # 拓扑排序（Kahn's algorithm）
        in_degree = {name: 0 for name in graph}
        for name, deps in graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[name] = in_degree.get(name, 0) + 1

        queue = [name for name, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for name, deps in graph.items():
                if node in deps and name not in result:
                    in_degree[name] -= 1
                    if in_degree[name] == 0 and name not in queue:
                        queue.append(name)

        # 检测环
        if len(result) != len(skill_names):
            # 有环依赖，直接返回原始顺序
            logger.warning("Circular dependency detected, using original order")
            return skill_names

        return result

    def load_runner(self, name: str) -> Any:
        """
        动态加载能力的 runner.py 模块。
        返回模块对象（可调用 execute() 函数）。
        """
        import importlib.util

        cap = self.get(name)
        if not cap:
            raise ValueError(f"Capability not found: {name}")

        runner_path = Path(cap["skill_dir"]) / "runner.py"
        if not runner_path.exists():
            raise FileNotFoundError(f"Runner not found: {runner_path}")

        spec = importlib.util.spec_from_file_location(
            f"capability_{name.replace('.', '_')}", runner_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def summary(self) -> dict[str, Any]:
        """返回注册中心摘要统计"""
        caps = list(self._index.values())
        by_domain: dict[str, int] = {}
        by_category: dict[str, int] = {}
        for cap in caps:
            by_domain[cap["domain"]] = by_domain.get(cap["domain"], 0) + 1
            by_category[cap["category"]] = by_category.get(cap["category"], 0) + 1

        return {
            "total": len(caps),
            "by_domain": by_domain,
            "by_category": by_category,
            "capabilities": sorted([c["name"] for c in caps]),
        }

    def export_index_json(self, output_path: str):
        """导出能力索引为 JSON 文件（供外部系统读取）"""
        caps = list(self._index.values())
        # 简化输出（不含内部字段）
        export_data = []
        for cap in caps:
            export_data.append({
                "name": cap["name"],
                "version": cap["version"],
                "domain": cap["domain"],
                "category": cap["category"],
                "description": cap["description"],
                "cost": cap["cost"],
                "evaluation": cap["evaluation"],
                "dependencies": cap.get("dependencies", []),
                "hermes_tools": cap.get("hermes_tools", []),
            })

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        return output_path
