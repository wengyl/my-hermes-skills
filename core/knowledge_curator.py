"""
Knowledge Curator — Memos → Knowledge 路由管道

核心理念：不是Memory，而是 Knowledge Inbox
  Memos (原始想法/笔记)
    → AI Curator (结构化整理)
    → Knowledge Objects (路由到正确的知识层)
    → Hermes Memory / Skills / Knowledge Base

路由规则：
  - 事实/偏好 → Hermes Memory (via memory tool)
  - 怎么做/方法论 → Hermes Skill (via skill_manage)
  - 经验/教训 → Knowledge/failures 或 Knowledge/best_practices
  - 规则/标准 → Knowledge/best_practices
  - 标准流程 → Knowledge/patterns (workflow templates)
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


class KnowledgeCurator:
    """
    Knowledge Curator — 知识整理和路由

    接收原始 Memos → 判断知识类型 → 路由到正确的存储层
    """

    # 知识类型判断关键词
    TYPE_KEYWORDS = {
        "fact": ["是", "等于", "位于", "属于", "叫做", "定义", "meaning"],
        "preference": ["偏好", "喜欢", "希望", "要求", "不喜欢", "preference"],
        "procedure": ["步骤", "流程", "先", "然后", "最后", "how to", "怎么做"],
        "rule": ["必须", "不要", "应该", "禁止", "always", "never", "rule"],
        "experience": ["上次", "之前", "发现", "踩坑", "教训", "失败", "经验"],
        "pattern": ["模式", "规律", "通常", "一般", "workflow", "pattern"],
    }

    def __init__(self, knowledge_dir: str = "knowledge"):
        self.knowledge_dir = Path(knowledge_dir)
        self.inbox_dir = self.knowledge_dir / ".inbox"
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

    def ingest_memo(self, memo: str, source: str = "user") -> dict[str, Any]:
        """
        接收一条原始 Memo → 分类 → 路由

        Args:
            memo: 原始文本内容
            source: 来源标识

        Returns:
            {
                "memo_id": str,
                "classified_type": str,
                "routing_target": str,
                "structured_content": dict,
                "action_required": str,
            }
        """
        # 1. 分类
        ktype = self._classify(memo)

        # 2. 结构化
        structured = self._structure(memo, ktype)

        # 3. 路由
        routing = self._route(ktype, structured)

        # 4. 持久化到 inbox
        memo_id = f"memo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        record = {
            "memo_id": memo_id,
            "source": source,
            "raw": memo,
            "classified_type": ktype,
            "routing_target": routing["target"],
            "structured_content": structured,
            "action_required": routing["action"],
            "status": "pending_curator_review",
            "created_at": datetime.now().isoformat(),
        }

        inbox_path = self.inbox_dir / f"{memo_id}.yaml"
        with open(inbox_path, "w", encoding="utf-8") as f:
            yaml.dump(record, f, allow_unicode=True, sort_keys=False)

        logger.info(f"Memo ingested: {memo_id} → {routing['target']}")
        return record

    def _classify(self, text: str) -> str:
        """分类知识类型"""
        text_lower = text.lower()
        scores: dict[str, int] = {}

        for ktype, keywords in self.TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > 0:
                scores[ktype] = score

        if not scores:
            return "fact"

        return max(scores, key=scores.get)

    def _structure(self, memo: str, ktype: str) -> dict[str, Any]:
        """将原始memo结构化为知识对象"""
        if ktype == "procedure":
            return self._structure_procedure(memo)
        elif ktype == "rule":
            return self._structure_rule(memo)
        elif ktype == "experience":
            return self._structure_experience(memo)
        elif ktype == "pattern":
            return self._structure_pattern(memo)
        elif ktype == "preference":
            return self._structure_preference(memo)
        else:
            return self._structure_fact(memo)

    def _structure_procedure(self, memo: str) -> dict:
        steps = re.split(r'[;\n]|然后|之后|最后', memo)
        return {
            "type": "procedure",
            "steps": [s.strip() for s in steps if s.strip()],
        }

    def _structure_rule(self, memo: str) -> dict:
        is_negative = bool(re.search(r'不要|禁止|never|不能|不可以', memo, re.I))
        return {
            "type": "rule",
            "text": memo.strip(),
            "enforcement": "hard" if is_negative else "soft",
        }

    def _structure_experience(self, memo: str) -> dict:
        return {
            "type": "experience",
            "text": memo.strip(),
            "domain": self._guess_domain(memo),
        }

    def _structure_pattern(self, memo: str) -> dict:
        return {
            "type": "pattern",
            "text": memo.strip(),
            "domain": self._guess_domain(memo),
        }

    def _structure_preference(self, memo: str) -> dict:
        return {
            "type": "preference",
            "text": memo.strip(),
        }

    def _structure_fact(self, memo: str) -> dict:
        return {
            "type": "fact",
            "text": memo.strip(),
        }

    def _guess_domain(self, text: str) -> str:
        if any(kw in text for kw in ["基金", "投资", "组合", "持仓", "净值"]):
            return "investment"
        if any(kw in text for kw in ["视频", "配音", "字幕", "TTS"]):
            return "video"
        if any(kw in text for kw in ["模型", "训练", "推理", "部署"]):
            return "mlops"
        return "general"

    def _route(self, ktype: str, structured: dict) -> dict[str, str]:
        """决定知识路由去向"""
        routing_map = {
            "fact": {
                "target": "hermes_memory",
                "action": "store via memory tool (target=user or memory)",
            },
            "preference": {
                "target": "hermes_memory",
                "action": "store via memory tool (target=user)",
            },
            "procedure": {
                "target": "hermes_skill",
                "action": "create/update Skill via skill_manage (procedural knowledge)",
            },
            "rule": {
                "target": "knowledge_best_practices",
                "action": "add to knowledge/best_practices/{domain}/",
            },
            "experience": {
                "target": "knowledge_failures_or_cases",
                "action": "add to knowledge/failures/ or knowledge/cases/",
            },
            "pattern": {
                "target": "knowledge_patterns",
                "action": "add to knowledge/patterns/{domain}/",
            },
        }
        return routing_map.get(ktype, routing_map["fact"])

    def list_inbox(self, status: str = "pending_curator_review") -> list[dict]:
        """列出待处理的 inbox 条目"""
        items = []
        for f in sorted(self.inbox_dir.glob("*.yaml")):
            with open(f, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if data.get("status") == status:
                    items.append(data)
        return items

    def curate(self, memo_id: str, approved: bool = True,
               override_target: Optional[str] = None) -> dict[str, Any]:
        """
        执行知识路由 — 将 inbox 条目实际写入目标知识层

        Args:
            memo_id: inbox条目ID
            approved: 是否审批通过
            override_target: 覆盖路由目标

        Returns:
            路由执行结果
        """
        inbox_path = self.inbox_dir / f"{memo_id}.yaml"
        if not inbox_path.exists():
            return {"error": f"Inbox entry not found: {memo_id}"}

        with open(inbox_path, "r", encoding="utf-8") as f:
            record = yaml.safe_load(f)

        if not approved:
            record["status"] = "rejected"
            with open(inbox_path, "w", encoding="utf-8") as f:
                yaml.dump(record, f, allow_unicode=True, sort_keys=False)
            return {"memo_id": memo_id, "status": "rejected"}

        target = override_target or record["routing_target"]
        structured = record["structured_content"]
        domain = structured.get("domain", "general")

        result: dict[str, Any] = {"memo_id": memo_id, "routed_to": target}

        if target == "knowledge_best_practices":
            bp_dir = self.knowledge_dir / "best_practices" / domain
            bp_dir.mkdir(parents=True, exist_ok=True)
            bp_file = bp_dir / f"{memo_id}.yaml"
            bp_data = {
                "id": memo_id,
                "domain": domain,
                "source": "knowledge_curator",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "rules": [{
                    "id": f"rule_0",
                    "rule": structured.get("text", record.get("raw", "")),
                    "enforcement": structured.get("enforcement", "soft"),
                }],
            }
            with open(bp_file, "w", encoding="utf-8") as f:
                yaml.dump(bp_data, f, allow_unicode=True, sort_keys=False)
            result["path"] = str(bp_file)

        elif target == "knowledge_patterns":
            pat_dir = self.knowledge_dir / "patterns" / domain
            pat_dir.mkdir(parents=True, exist_ok=True)
            pat_file = pat_dir / f"{memo_id}.yaml"
            with open(pat_file, "w", encoding="utf-8") as f:
                yaml.dump(structured, f, allow_unicode=True, sort_keys=False)
            result["path"] = str(pat_file)

        elif target == "knowledge_failures_or_cases":
            fail_dir = self.knowledge_dir / "failures" / domain
            fail_dir.mkdir(parents=True, exist_ok=True)
            fail_file = fail_dir / f"{memo_id}.yaml"
            fail_data = {
                "domain": domain,
                "failures": [{
                    "id": memo_id,
                    "pattern": structured.get("text", record.get("raw", "")),
                    "status": "candidate",
                }],
            }
            with open(fail_file, "w", encoding="utf-8") as f:
                yaml.dump(fail_data, f, allow_unicode=True, sort_keys=False)
            result["path"] = str(fail_file)

        elif target == "hermes_memory":
            result["action_required"] = (
                "Call memory tool: "
                f"memory(action='add', target='{structured.get('type', 'memory')}', "
                f"content='{structured.get('text', record.get('raw', ''))[:100]}')"
            )

        elif target == "hermes_skill":
            result["action_required"] = (
                "Call skill_manage to create/update Skill. "
                "Procedural knowledge should be encoded as a Hermes Skill."
            )

        record["status"] = "curated"
        record["routed_to"] = target
        record["curated_at"] = datetime.now().isoformat()
        with open(inbox_path, "w", encoding="utf-8") as f:
            yaml.dump(record, f, allow_unicode=True, sort_keys=False)

        logger.info(f"Memo {memo_id} curated → {target}")
        return result
