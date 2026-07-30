"""
Decision Engine — 规则驱动的决策执行 (P1)

区别：
  LLM 生成建议（"建议减仓"）
  Decision Engine 执行规则（如果回撤>15%则降低仓位10%）

规则结构：
  id, name, domain, condition(表达式), action, priority, enabled

规则示例（投资域）：
  - 如果组合回撤 > 15% 且 风险评分下降 → 降低权益仓位10%
  - 如果单只基金占比 > 30% → 触发再平衡提醒
  - 如果行业集中度 > 60% → 标记行业风险

决策日志：
  每次决策记录：规则ID、触发条件值、执行动作、时间戳
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


class DecisionEngine:
    """
    Decision Engine — 规则驱动的自动决策

    规则存储在 decision-engine/rules/{domain}.yaml
    每次执行 evaluate(data) → 返回匹配的决策列表
    """

    def __init__(self, rules_dir: str = "decision-engine/rules"):
        self.rules_dir = Path(rules_dir)
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        self.rules: list[dict[str, Any]] = []
        self._load_rules()

    def _load_rules(self):
        """加载所有规则文件"""
        for f in sorted(self.rules_dir.glob("*.yaml")):
            with open(f, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if data and isinstance(data, list):
                    self.rules.extend(data)
                elif data and "rules" in data:
                    self.rules.extend(data["rules"])
        logger.info(f"Decision engine loaded {len(self.rules)} rules")

    def add_rule(self, rule: dict[str, Any]) -> str:
        """添加一条规则"""
        rule_id = rule.get("id") or f"rule_{len(self.rules)+1:04d}"
        rule["id"] = rule_id
        rule["enabled"] = rule.get("enabled", True)
        rule["created_at"] = datetime.now().isoformat()
        self.rules.append(rule)

        # 持久化到对应域文件
        domain = rule.get("domain", "general")
        rules_file = self.rules_dir / f"{domain}.yaml"
        domain_rules = [r for r in self.rules if r.get("domain") == domain]
        with open(rules_file, "w", encoding="utf-8") as f:
            yaml.dump({"rules": domain_rules}, f, allow_unicode=True, sort_keys=False)

        logger.info(f"Rule added: {rule_id} → {rules_file}")
        return rule_id

    def evaluate(self, data: dict[str, Any], domain: Optional[str] = None) -> list[dict[str, Any]]:
        """
        评估数据，返回所有匹配的决策

        Args:
            data: 输入数据（如投资组合状态）
            domain: 限定域（如 investment）

        Returns:
            [{rule_id, name, condition_met, action, priority, data_snapshot}]
        """
        decisions: list[dict[str, Any]] = []

        for rule in self.rules:
            if not rule.get("enabled", True):
                continue
            if domain and rule.get("domain") != domain:
                continue

            condition = rule.get("condition", "")
            try:
                if self._eval_condition(condition, data):
                    decisions.append({
                        "rule_id": rule["id"],
                        "name": rule.get("name", ""),
                        "domain": rule.get("domain", "general"),
                        "condition_met": condition,
                        "action": rule.get("action", ""),
                        "priority": rule.get("priority", 5),
                        "data_snapshot": self._snapshot_relevant_data(condition, data),
                        "timestamp": datetime.now().isoformat(),
                    })
            except Exception as e:
                logger.warning(f"Rule {rule['id']} evaluation error: {e}")

        # 按优先级排序
        decisions.sort(key=lambda d: d["priority"], reverse=True)
        return decisions

    def _eval_condition(self, condition: str, data: dict[str, Any]) -> bool:
        """
        安全评估条件表达式

        支持：
          - 字段引用: portfolio.drawdown
          - 比较运算: >, <, >=, <=, ==, !=
          - 逻辑运算: and, or, not
          - 数值/字符串字面量

        示例:
          "portfolio.drawdown > 15 and risk.score < 50"
        """
        if not condition:
            return False

        # 替换字段引用为数据值
        def replace_field(match):
            path = match.group(0)
            value = self._get_nested(data, path)
            return str(value) if value is not None else "None"

        # 匹配 xxx.yyy.zzz 模式的字段引用
        expr = re.sub(r'[a-zA-Z_][a-zA-Z0-9_.]*', replace_field, condition)

        # 安全评估（只允许基本运算）
        allowed = re.match(r'^[\d\s.><=!]+$|^[\d\s.><=!andorNte]+$|^[\d\s.><=!andorNte()]+$', expr.replace("None", "0"))
        if not allowed:
            # fallback: 简化评估
            return self._simple_eval(condition, data)

        try:
            # 替换 None 为 0
            expr = expr.replace("None", "0")
            result = eval(expr, {"__builtins__": {}}, {})
            return bool(result)
        except Exception:
            return self._simple_eval(condition, data)

    def _simple_eval(self, condition: str, data: dict[str, Any]) -> bool:
        """简化的条件评估（支持 > < >= <= == !=）"""
        operators = [">=", "<=", "!=", "==", ">", "<"]
        for op in operators:
            if op in condition:
                parts = condition.split(op)
                if len(parts) == 2:
                    left = self._get_value(parts[0].strip(), data)
                    right = self._get_value(parts[1].strip(), data)
                    if left is None or right is None:
                        return False
                    try:
                        left = float(left)
                        right = float(right)
                    except (ValueError, TypeError):
                        left = str(left)
                        right = str(right)

                    if op == ">":
                        return left > right
                    elif op == "<":
                        return left < right
                    elif op == ">=":
                        return left >= right
                    elif op == "<=":
                        return left <= right
                    elif op == "==":
                        return left == right
                    elif op == "!=":
                        return left != right
        return False

    def _get_value(self, token: str, data: dict) -> Any:
        """从token获取值（字段引用或字面量）"""
        token = token.strip()
        # 尝试作为字段路径
        val = self._get_nested(data, token)
        if val is not None:
            return val
        # 尝试作为数值
        try:
            return float(token)
        except ValueError:
            # 作为字符串
            return token.strip("'\"")

    def _get_nested(self, data: dict, path: str) -> Any:
        """通过点号路径获取嵌套值"""
        keys = path.split(".")
        val = data
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return None
        return val

    def _snapshot_relevant_data(self, condition: str, data: dict) -> dict:
        """提取条件中引用的字段值"""
        fields = re.findall(r'[a-zA-Z_][a-zA-Z0-9_.]*', condition)
        snapshot = {}
        for f in fields:
            if f not in ["and", "or", "not", "None", "True", "False"]:
                val = self._get_nested(data, f)
                if val is not None:
                    snapshot[f] = val
        return snapshot

    def list_rules(self, domain: Optional[str] = None) -> list[dict]:
        """列出规则"""
        if domain:
            return [r for r in self.rules if r.get("domain") == domain]
        return self.rules
