# my-hermes-skills — Hermes Agent OS

**不替代 Hermes，增强它。从 Skill Engineering 到 Agent Engineering。**

```
Hermes OS = Hermes Core (原生) + Enhancement Layer + Agent Engineering Layer
```

## 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent Engineering Layer                    │
│  Context Engine │ Capability Graph │ Decision Engine        │
│  Model Router   │ Feedback Loop    │ Multi-Agent Roles      │
│  Goal Manager   │ Agent Journal    │                        │
└──────────────────────────┬──────────────────────────────────┘
                           │ 增强
┌──────────────────────────┴──────────────────────────────────┐
│                    Enhancement Layer                         │
│  Knowledge Layer │ Reflection Engine │ Knowledge Curator     │
│  Knowledge Bridge │ Capability Registry │ Evaluator         │
│  Cost Manager │ Evolution Module                             │
└──────────────────────────┬──────────────────────────────────┘
                           │ 协同
┌──────────────────────────┴──────────────────────────────────┐
│                    Hermes Core (原生)                         │
│  Skills System │ Persistent Memory │ Tools / Toolsets       │
│  Self-improving Loop │ Skill Creation & Optimization        │
└─────────────────────────────────────────────────────────────┘
```

## Agent Engineering 模块 (P0/P1/P2)

| 模块 | 优先级 | 核心能力 |
|------|--------|---------|
| Context Engine | P0 | 6层动态上下文组装 (任务→领域→历史→用户→约束→实时) |
| Capability Graph | P1 | 23节点+3种边(依赖/生产消费/替代)+目标映射 |
| Decision Engine | P1 | 规则驱动自动决策 (5条投资规则) |
| Model Router | P1 | 智能模型路由 (3层级+预算约束+历史效果) |
| Feedback Loop | P1 | 结构化用户反馈+模式分析+学习闭环 |
| Agent Journal | P2 | 智能工作日志+周期报告 |
| Goal Manager | P2 | 长期目标管理+进度追踪 |
| Multi-Agent Roles | P2 | 4角色分工(Researcher/Analyst/Writer/Reviewer) |

## Enhancement Layer 模块

| 模块 | 核心能力 |
|------|---------|
| Knowledge Layer | best_practices/failures/patterns/cases 4层知识 |
| Reflection Engine | 任务后反思+候选管道(Candidate→Approve→Merge) |
| Knowledge Curator | Memos→Knowledge路由(6类型分类) |
| Knowledge Bridge | 连接Hermes原生能力 |
| Capability Registry | 23个原子能力注册+元数据 |
| Evaluator | 5种评估算子(text/image/audio/video/json) |

## 三个核心原则

1. **不替换 Hermes，增强它**
2. **知识分层** — 事实→Memory, 怎么做→Skill, 经验→Reflection, 规则→Knowledge, 流程→Pattern
3. **不直接改生产Skill** — Experience→Candidate→Benchmark→Approve→Production

## 测试

```bash
python -m tests.test_phase1   # Schema→Registry→SQLite (23能力)
python -m tests.test_phase2   # StateMachine+Planner+Executor
python -m tests.test_phase3   # Evaluator+Repair+Memory+E2E
python -m tests.test_phase4   # Evolution+Benchmark
python -m tests.test_phase5   # Enhancement Layer (Knowledge+Reflection+Curator+Bridge)
python -m tests.test_phase6   # Agent Engineering (Context+Graph+Decision+Router+Feedback+Journal+Goal+MultiAgent)
```

## 关于作者 / 支持

由 [wengyl](https://github.com/wengyl) 创作与维护。这里存放的是我日常在真实 Agent 工程实践中沉淀的技能与架构方案。

如果你觉得这些内容有帮助，欢迎在我的 [爱发电主页](https://afdian.com/a/devtoolbox2026) 发电支持——那是我持续整理、发布跨境合规速报、数字工具模板与自动化方案的地方。

```
爱发电 · 开发者工具箱 → https://afdian.com/a/devtoolbox2026
```
