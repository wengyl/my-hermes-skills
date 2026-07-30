"""
SQLite 持久化层 — Agent Capability OS 数据库

表结构：
  - capabilities      : 能力注册表（从 SKILL.yaml 同步）
  - tasks             : 任务表（状态机持久化）
  - execution_logs    : 执行记录表
  - evaluation_records: 评估记录表
  - memory_store      : 记忆库（user/failure/skill/best_case 四类）
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

DEFAULT_DB_PATH = "data/agent_os.db"

SCHEMA_SQL = """
-- ── 能力注册表 ──
CREATE TABLE IF NOT EXISTS capabilities (
    name            TEXT PRIMARY KEY,
    version         TEXT NOT NULL,
    domain          TEXT NOT NULL,
    category        TEXT NOT NULL,
    description     TEXT NOT NULL,
    input_schema    TEXT NOT NULL,   -- JSON
    output_schema   TEXT NOT NULL,   -- JSON
    cost_json       TEXT NOT NULL,   -- JSON
    evaluation_json TEXT NOT NULL,  -- JSON
    dependencies    TEXT NOT NULL DEFAULT '[]',  -- JSON array
    hermes_tools    TEXT DEFAULT '[]',
    tags            TEXT DEFAULT '[]',
    skill_dir       TEXT,            -- 原子技能目录路径
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── 任务表（状态机持久化）──
CREATE TABLE IF NOT EXISTS tasks (
    task_id         TEXT PRIMARY KEY,
    goal            TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'created',
    -- created|planning|executing|evaluating|repairing|completed|learning|failed
    plan_json       TEXT,            -- Planner输出的执行计划
    current_step    INTEGER DEFAULT 0,
    total_steps     INTEGER DEFAULT 0,
    retry_count     INTEGER DEFAULT 0,
    result_json     TEXT,            -- 最终结果
    cost_cny        REAL DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── 执行记录表 ──
CREATE TABLE IF NOT EXISTS execution_logs (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    step_index      INTEGER NOT NULL,
    skill_name      TEXT NOT NULL,
    input_json      TEXT,
    output_json     TEXT,
    success         INTEGER DEFAULT 0,
    duration_ms     INTEGER DEFAULT 0,
    error_message   TEXT,
    token_used      INTEGER DEFAULT 0,
    cost_cny        REAL DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

-- ── 评估记录表 ──
CREATE TABLE IF NOT EXISTS evaluation_records (
    eval_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    step_index      INTEGER,
    skill_name      TEXT,
    eval_type       TEXT NOT NULL,   -- text|image|audio|video|json
    score           REAL NOT NULL,   -- 0-100
    defects_json    TEXT,            -- 缺陷清单 JSON array
    suggestions_json TEXT,           -- 修复建议 JSON array
    passed          INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

-- ── 记忆库 ──
CREATE TABLE IF NOT EXISTS memory_store (
    memory_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_type     TEXT NOT NULL,   -- user|failure|skill|best_case
    key             TEXT NOT NULL,   -- 检索键
    value_json      TEXT NOT NULL,   -- 记忆内容
    domain          TEXT,            -- 业务域
    skill_name      TEXT,            -- 关联技能
    task_id         TEXT,            -- 关联任务
    score           REAL,            -- 关联评分
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── 索引 ──
CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_exec_task ON execution_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_eval_task ON evaluation_records(task_id);
CREATE INDEX IF NOT EXISTS idx_mem_type ON memory_store(memory_type);
CREATE INDEX IF NOT EXISTS idx_mem_key ON memory_store(key);
CREATE INDEX IF NOT EXISTS idx_cap_domain ON capabilities(domain);
CREATE INDEX IF NOT EXISTS idx_cap_category ON capabilities(category);
"""


class Database:
    """SQLite 持久化层"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()

    def _connect(self):
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._connect()
        return self._conn  # type: ignore

    # ── 能力注册表 CRUD ──

    def upsert_capability(self, cap: dict[str, Any]) -> bool:
        """插入或更新能力记录"""
        sql = """
        INSERT INTO capabilities
            (name, version, domain, category, description,
             input_schema, output_schema, cost_json, evaluation_json,
             dependencies, hermes_tools, tags, skill_dir, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(name) DO UPDATE SET
            version=excluded.version,
            domain=excluded.domain,
            category=excluded.category,
            description=excluded.description,
            input_schema=excluded.input_schema,
            output_schema=excluded.output_schema,
            cost_json=excluded.cost_json,
            evaluation_json=excluded.evaluation_json,
            dependencies=excluded.dependencies,
            hermes_tools=excluded.hermes_tools,
            tags=excluded.tags,
            skill_dir=excluded.skill_dir,
            updated_at=datetime('now')
        """
        self.conn.execute(sql, (
            cap["name"], cap["version"], cap["domain"], cap["category"],
            cap["description"],
            json.dumps(cap["input_schema"]),
            json.dumps(cap["output_schema"]),
            json.dumps(cap["cost"]),
            json.dumps(cap["evaluation"]),
            json.dumps(cap.get("dependencies", [])),
            json.dumps(cap.get("hermes_tools", [])),
            json.dumps(cap.get("tags", [])),
            cap.get("skill_dir", ""),
        ))
        self.conn.commit()
        return True

    def get_capability(self, name: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM capabilities WHERE name=?", (name,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_capability(row)

    def list_capabilities(self, domain: Optional[str] = None) -> list[dict[str, Any]]:
        if domain:
            rows = self.conn.execute(
                "SELECT * FROM capabilities WHERE domain=? ORDER BY name", (domain,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM capabilities ORDER BY name"
            ).fetchall()
        return [self._row_to_capability(r) for r in rows]

    def _row_to_capability(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "name": row["name"],
            "version": row["version"],
            "domain": row["domain"],
            "category": row["category"],
            "description": row["description"],
            "input_schema": json.loads(row["input_schema"]),
            "output_schema": json.loads(row["output_schema"]),
            "cost": json.loads(row["cost_json"]),
            "evaluation": json.loads(row["evaluation_json"]),
            "dependencies": json.loads(row["dependencies"]),
            "hermes_tools": json.loads(row["hermes_tools"]),
            "tags": json.loads(row["tags"]),
            "skill_dir": row["skill_dir"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ── 任务表 CRUD ──

    def create_task(self, task_id: str, goal: str) -> dict[str, Any]:
        self.conn.execute(
            "INSERT INTO tasks (task_id, goal, state) VALUES (?, ?, 'created')",
            (task_id, goal)
        )
        self.conn.commit()
        return {"task_id": task_id, "goal": goal, "state": "created"}

    def get_task(self, task_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def update_task_state(self, task_id: str, state: str, **extra):
        sets = ["state = ?", "updated_at = datetime('now')"]
        vals: list[Any] = [state]
        for k, v in extra.items():
            sets.append(f"{k} = ?")
            vals.append(v if isinstance(v, (int, float, str, type(None))) else json.dumps(v))
        vals.append(task_id)
        self.conn.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE task_id=?", vals
        )
        self.conn.commit()

    def list_tasks(self, state: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        if state:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE state=? ORDER BY created_at DESC LIMIT ?",
                (state, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── 执行记录 ──

    def log_execution(self, log: dict[str, Any]):
        self.conn.execute("""
            INSERT INTO execution_logs
                (task_id, step_index, skill_name, input_json, output_json,
                 success, duration_ms, error_message, token_used, cost_cny)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log["task_id"], log["step_index"], log["skill_name"],
            json.dumps(log.get("input", {})),
            json.dumps(log.get("output", {})),
            int(log.get("success", False)),
            log.get("duration_ms", 0),
            log.get("error_message"),
            log.get("token_used", 0),
            log.get("cost_cny", 0),
        ))
        self.conn.commit()

    def get_execution_logs(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM execution_logs WHERE task_id=? ORDER BY step_index",
            (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 评估记录 ──

    def log_evaluation(self, eval_record: dict[str, Any]):
        self.conn.execute("""
            INSERT INTO evaluation_records
                (task_id, step_index, skill_name, eval_type, score,
                 defects_json, suggestions_json, passed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            eval_record["task_id"],
            eval_record.get("step_index"),
            eval_record.get("skill_name"),
            eval_record["eval_type"],
            eval_record["score"],
            json.dumps(eval_record.get("defects", [])),
            json.dumps(eval_record.get("suggestions", [])),
            int(eval_record.get("passed", False)),
        ))
        self.conn.commit()

    def get_evaluations(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM evaluation_records WHERE task_id=? ORDER BY eval_id",
            (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 记忆库 ──

    def store_memory(self, mem_type: str, key: str, value: Any, **meta):
        self.conn.execute("""
            INSERT INTO memory_store (memory_type, key, value_json, domain, skill_name, task_id, score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            mem_type, key, json.dumps(value, ensure_ascii=False),
            meta.get("domain"), meta.get("skill_name"),
            meta.get("task_id"), meta.get("score")
        ))
        self.conn.commit()

    def search_memory(self, mem_type: Optional[str] = None, key: Optional[str] = None,
                      limit: int = 20) -> list[dict[str, Any]]:
        query = "SELECT * FROM memory_store WHERE 1=1"
        params: list[Any] = []
        if mem_type:
            query += " AND memory_type=?"
            params.append(mem_type)
        if key:
            query += " AND key LIKE ?"
            params.append(f"%{key}%")
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["value"] = json.loads(d.pop("value_json"))
            results.append(d)
        return results

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
