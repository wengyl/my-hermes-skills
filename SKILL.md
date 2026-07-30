---
name: agent-os-enhancement
description: "Hermes Agent OS 增强层 — 知识管理、反思沉淀、能力注册、评估治理。不替代 Hermes 原生 Skill/Memory/Planner，而是在其上增加 Enterprise Agent Layer。"
version: 2.0.0
author: wyl
metadata:
  hermes:
    tags: [agent-os, enhancement, knowledge, reflection, evaluation]
    related_skills: [hermes-agent, ai-video-factory-pipeline, fund-investment-advisor]
---

# Agent OS Enhancement Layer

## 定位

这个项目不是替代 Hermes，而是建立在 Hermes 原生架构之上的**增强层**。

```
Hermes Core (原生)
  ├── Skills System (按需加载)
  ├── Persistent Memory (跨会话)
  ├── Tools / Toolsets
  ├── Self-improving Loop
  └── Skill Creation & Optimization
         ↑
         │ 增强和治理
         │
Enhancement Layer (本项目)
  ├── Knowledge Layer (最佳实践/失败案例/工作流模式/经验)
  ├── Reflection Engine (任务后反思 → 候选管道)
  ├── Knowledge Curator (Memos → Knowledge 路由)
  ├── Knowledge Bridge (连接 Hermes 原生能力)
  ├── Capability Registry (原子能力注册+评估)
  ├── Evaluator (输出质量评估)
  ├── Cost Manager (成本治理)
  └── Evolution Module (自动演进)
```

## 三个核心原则

**原则1**: 不替换 Hermes，增强它
**原则2**: 不把知识全部变Skill — 事实→Memory，怎么做→Skill，经验→Reflection，规则→Knowledge，流程→Best Practice
**原则3**: 不让AI直接修改生产Skill — Experience→Candidate→Benchmark→Approve→Production

## 使用方式

### 1. 为 Hermes Agent 提供规划增强上下文

```python
from core.knowledge_bridge import KnowledgeBridge
from core.db import Database
from core.registry import CapabilityRegistry
from core.memory import MemorySubsystem
from core.reflection import ReflectionEngine
from core.knowledge_curator import KnowledgeCurator

db = Database("data/agent_os.db")
registry = CapabilityRegistry(db, scan_root="capabilities")
registry.sync()
memory = MemorySubsystem(db)
reflection = ReflectionEngine(db, registry, memory, "knowledge")
curator = KnowledgeCurator("knowledge")
bridge = KnowledgeBridge(db, registry, memory, reflection, curator, "knowledge")

# 获取规划上下文（含最佳实践、已知失败、工作流模板）
context = bridge.get_planning_context("诊断基金组合")
# 返回: domain, workflow_pattern, best_practices, known_failures,
#       user_preferences, recent_best_cases, available_capabilities
```

### 2. 任务后反思

```python
# 任务完成后自动反思
result = orch.run("把道氏理论PDF转成AI讲解视频")
# Orchestrator 自动触发 ReflectionEngine
# 生成知识候选到 knowledge/.candidates/
# 候选需人工审批后才合并到生产知识
```

### 3. 知识 Inbox

```python
# 用户输入一条经验
curator.ingest_memo("投资分析时必须先看宏观再看行业最后看估值")
# 自动分类: procedure → 路由到 hermes_skill

curator.ingest_memo("制作视频不要在AI配图中生成文字")
# 自动分类: rule → 路由到 knowledge/best_practices
```

### 4. 导出知识到 Hermes Skill references

```python
# 将积累的知识导出为 Hermes Skill 可引用的 markdown
bridge.export_to_skill_references("investment", output_dir="skills")
# 生成: skills/investment/references/best_practices.md
#        skills/investment/references/common_failures.md
#        skills/investment/references/workflow.md
```

### 5. 候选审批管道

```python
# 查看待审批候选
candidates = reflection.list_candidates()

# 审批通过 → 合并到生产知识
reflection.approve_candidate("candidate_id")

# 拒绝
reflection.reject_candidate("candidate_id", reason="不适用")

# 自动验证（同一缺陷出现≥3次自动批准）
reflection.auto_validate_candidates()
```

## 知识路由规则

| 内容类型 | 判断关键词 | 存储位置 |
|---------|-----------|---------|
| 事实/偏好 | 是/等于/偏好/喜欢 | Hermes Memory |
| 怎么做/方法 | 步骤/流程/先/然后 | Hermes Skill |
| 规则/标准 | 必须/不要/应该/禁止 | knowledge/best_practices/ |
| 经验/教训 | 上次/失败/教训/踩坑 | knowledge/failures/ |
| 模式/规律 | 模式/通常/一般 | knowledge/patterns/ |
| 成功案例 | 高分/优秀/成功 | knowledge/cases/ |

## 候选管道流程

```
Experience (任务执行)
  ↓
Candidate (写入 .candidates/)
  ↓
Validate (自动验证: 同一缺陷≥3次自动批准)
  ↓
Approve (人工审批: best_practice必须人工)
  ↓
Merge (合并到生产知识)
  ↓
[可选] Skill Update (通过 skill_manage 更新 Hermes Skill)
```

## 现有知识库

### Video 域
- `best_practices/financial_video_style.yaml` — 财经视频风格规范 (6条规则, confidence=0.92)
- `failures/common_failures.yaml` — 4个已知失败模式
- `patterns/financial_explainer_workflow.yaml` — 5阶段标准流程

### Investment 域
- `best_practices/fund_diagnosis_methodology.yaml` — 基金诊断方法论 (5条规则, confidence=0.95)
- `failures/common_failures.yaml` — 2个已知失败模式
- `patterns/fund_diagnosis_workflow.yaml` — 5阶段诊断流程

### MLOps 域
- `best_practices/model_deploy_safety.yaml` — 模型部署安全规范 (3条规则)

## 原子能力注册表

23个原子能力已注册，按域分布：
- Video: 11 (script→storyboard→scene→image→voice→subtitle→compose→evaluate)
- MLOps: 6 (search→load→evaluate→serve)
- Investment: 6 (fetch→analyze→diagnose→strategy→report)

## 演进路线

- ✅ 阶段1: 整理现有Skills + 建立Knowledge结构
- ✅ 阶段2: Memos → Knowledge Pipeline (KnowledgeCurator)
- ✅ 阶段3: Reflection系统 (ReflectionEngine)
- 🚧 阶段4: Evaluation + Benchmark (已有框架, 需更多真实数据)
- 🚧 阶段5: Skill自动进化 (已有Evolution模块, 需连接Candidate管道)

## 文件结构

```
my-hermes-skills/
├── core/                      # 增强层核心引擎
│   ├── orchestrator.py         # 总调度入口 (含Reflection+KnowledgeBridge)
│   ├── planner.py              # 规划增强 (领域识别+拓扑排序+并行标记)
│   ├── executor.py             # 执行引擎
│   ├── evaluator.py            # 评估系统 (text/image/audio/video/json 5算子)
│   ├── repair.py               # 自动修复
│   ├── memory.py               # 记忆子系统
│   ├── registry.py             # 能力注册中心
│   ├── state_machine.py        # 任务状态机
│   ├── cost_manager.py         # 成本治理
│   ├── schema.py               # SKILL.yaml 元数据规范
│   ├── db.py                   # SQLite持久化层
│   ├── reflection.py           # ★ 反思引擎 + 候选管道
│   ├── knowledge_curator.py    # ★ 知识整理路由
│   ├── knowledge_bridge.py     # ★ Hermes原生能力桥接
│   └── evolution.py             # 演进模块
├── knowledge/                  # ★ 知识层 (增强层核心)
│   ├── best_practices/         # 最佳实践规则
│   │   ├── video/
│   │   ├── investment/
│   │   └── mlops/
│   ├── failures/               # 失败案例库
│   │   ├── video/
│   │   └── investment/
│   ├── patterns/                # 工作流模式
│   │   ├── video/
│   │   └── investment/
│   ├── cases/                  # 经验案例
│   ├── .candidates/            # ★ 待审批知识候选
│   └── .inbox/                 # ★ Memos 收件箱
├── capabilities/               # 原子能力库
├── benchmark/                  # 基准测试
├── tests/                      # 测试套件 (Phase 1-5)
├── data/                       # SQLite + 索引
├── config.yaml                 # 全局配置
└── README.md
```
