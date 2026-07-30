#!/usr/bin/env python3
"""
Phase 1 集成测试：验证 schema → 扫描能力 → 注册到 SQLite 全链路。
"""

import sys
import os
import json

# 确保可以 import core 包
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from core.db import Database
from core.registry import CapabilityRegistry
from core.schema import validate_skill_yaml, SchemaValidationError

def main():
    print("━━━ Phase 1 Integration Test ━━━")

    # 1. 初始化数据库
    db = Database("data/agent_os.db")
    print("✅ SQLite database initialized")

    # 2. 初始化能力注册中心
    registry = CapabilityRegistry(db, scan_root="capabilities")

    # 3. 扫描 + 校验 + 同步
    print("\n--- Scanning capabilities/ ---")
    report = registry.sync()

    print(f"  Scanned: {report['scanned']}")
    print(f"  Valid:   {report['valid']}")
    print(f"  Invalid: {report['invalid']}")

    if report["errors"]:
        print("\n  ⚠️ Errors:")
        for err in report["errors"]:
            print(f"    {err['file']}: {err['error'][:80]}...")

    # 4. 打印注册中心摘要
    print("\n--- Registry Summary ---")
    summary = registry.summary()
    print(f"  Total capabilities: {summary['total']}")
    print(f"  By domain:  {summary['by_domain']}")
    print(f"  By category: {summary['by_category']}")

    print("\n  All registered capabilities:")
    for name in summary["capabilities"]:
        cap = registry.get(name)
        cost = cap["cost"]
        print(f"    {name:30s} | {cap['domain']:12s} | {cap['category']:14s} | tokens={cost['token_estimate']:5d} | {cap['description'][:40]}")

    # 5. 测试拓扑排序（视频域完整流水线）
    print("\n--- Topological Sort Test (video pipeline) ---")
    video_caps = [
        "script.create", "script.review", "storyboard.create", "scene.plan",
        "image.generate", "image.evaluate", "voice.generate", "voice.align",
        "subtitle.generate", "video.compose", "video.evaluate"
    ]
    order = registry.get_execution_order(video_caps)
    print(f"  Execution order ({len(order)} steps):")
    for i, name in enumerate(order):
        print(f"    {i+1:2d}. {name}")

    # 6. 测试按域查询
    print("\n--- Domain Query Tests ---")
    for domain in ["video", "mlops", "investment"]:
        caps = registry.query(domain=domain)
        print(f"  {domain}: {len(caps)} capabilities")

    # 7. 导出能力索引 JSON
    index_path = registry.export_index_json("data/capability_index.json")
    print(f"\n✅ Capability index exported to: {index_path}")

    # 8. 测试从 SQLite 重建索引
    registry2 = CapabilityRegistry(Database("data/agent_os.db"))
    registry2.build_index()
    assert len(registry2._index) == summary["total"], "Rebuild index mismatch!"
    print(f"✅ Rebuilt index from SQLite: {len(registry2._index)} capabilities")

    print("\n━━━ Phase 1 Integration Test PASSED ━━━")
    print(f"  Total atomic capabilities: {summary['total']}")
    print(f"  Video:     {summary['by_domain'].get('video', 0)}")
    print(f"  MLOps:     {summary['by_domain'].get('mlops', 0)}")
    print(f"  Investment: {summary['by_domain'].get('investment', 0)}")

    db.close()

if __name__ == "__main__":
    main()
