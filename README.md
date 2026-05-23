# TravelMind — AI 旅行规划系统

基于 LangGraph 多节点状态图引擎的智能旅行规划系统，支持多轮对话式行程生成、编辑与优化。

前后端分离架构，围绕"可对话、可解释、可编辑"的目标，落地 Agent + 检索增强 + 证据归因 + 渐进式交互的工程化链路。

**源码仓库**：[https://github.com/yzffff666/TravelMind](https://github.com/yzffff666/TravelMind)

---

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                  Vue 3 + TypeScript                      │
│          SSE 渐进渲染 · 逐天呈现 · 编辑 Diff             │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / SSE
┌────────────────────────▼────────────────────────────────┐
│                 FastAPI + Uvicorn                         │
│                                                          │
│  意图路由(QP) → 多轮对话 → 行程草案生成 → 编辑/问答/重置   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              LangGraph 4-Node StateGraph                 │
│                                                          │
│  extract_node ─┬→ recall_node → llm_draft_node → postprocess_node → END
│                │                                         │
│                └→ early_exit_node → END (P0 缺失早退)     │
└──────┬──────────────┬──────────────┬────────────────────┘
       │              │              │
  ┌────▼────┐   ┌────▼─────┐   ┌───▼────┐
  │Provider │   │ DeepSeek │   │ MySQL  │
  │并行检索  │   │ astream  │   │会话状态 │
  │Amap/Serp│   │ 流式生成  │   │        │
  └────┬────┘   └──────────┘   └────────┘
       │
  ┌────▼────┐
  │  Redis  │
  │语义缓存  │
  └─────────┘
```

---

## 核心功能

### 多轮对话与意图路由

- 意图识别（create / edit / qa / reset / chat）+ 约束提取
- 缺失硬约束（目的地/天数/预算）时自动澄清追问
- 会话状态 MySQL 持久化，支持 resume 续答与 reset 重置
- LLM 引导式对话，上下文感知的多轮交互

### 检索与证据流水线

- QP → 并行召回 → 可解释排序 → 规则过滤 → 证据组织
- Provider 抽象层（高德 Amap / SerpAPI / Mock），asyncio.gather 并行调用
- Evidence Builder 组织证据链（provider / url / fetched_at / attribution）

### 行程生成与编辑

- itinerary v1 结构化行程契约（trip_profile / days / slots / budget / evidence）
- P0/P1 分级降级策略（P0 缺失回澄清，P1 降级写 assumptions）
- Edit Day N 局部重规划，patch_engine 支持 slot 替换/删除/插入
- revision/diff 记录改动历史

### 渐进式交互

- LLM astream 流式生成 + SSE 渐进协议
- pipeline_complete → day_ready × N → final_itinerary 逐步推送
- 前端骨架屏 → 进度提示 → 逐天渲染，用户无需空等

### 性能优化

- LangGraph 单节点 → 4 节点重构 + 条件边路由
- Provider 串行 → asyncio.gather 并行（检索提升 75%）
- LLM ainvoke → astream 流式（用户感知首屏提升 87%）
- 缺字段条件边早退（<2ms vs 原 75s，提升 99.99%）
- 9 项性能回归测试 + 节点级 perf 指标自动采集

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 · TypeScript · Pinia · Axios · SSE |
| 后端 | FastAPI · Uvicorn · Python 3.10+ |
| 工作流 | LangGraph（4 节点状态图 + 条件边） |
| LLM | DeepSeek Chat API（astream 流式） |
| Embedding | Ollama / bge-m3 |
| 数据库 | MySQL（SQLAlchemy 异步 ORM） |
| 缓存 | Redis（语义缓存） |
| 检索 | 高德 Amap API · SerpAPI |

---

## 快速启动

### 1. 安装后端依赖

```bash
cd llm_backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `env.example` 到 `llm_backend/.env`，修改以下配置：

```env
# LLM
DEEPSEEK_API_KEY=your-api-key
DEEPSEEK_MODEL=deepseek-chat

# Ollama (Embedding)
OLLAMA_BASE_URL=http://localhost:11434

# MySQL
DATABASE_URL=mysql+aiomysql://user:pass@localhost:3306/travelmind

# Redis
REDIS_URL=redis://localhost:6379/0

# Provider（可选但推荐）
AMAP_API_KEY=your-amap-key
GEOAPIFY_KEY=your-geoapify-key
SERPAPI_KEY=your-serpapi-key
PROVIDER_COST_MODE=standard
```

Provider 默认顺序是 `Amap -> Geoapify -> SerpAPI -> Mock`：国内优先高德，海外日常优先低成本 Geoapify，SerpAPI 作为更贵的兜底来源。日常开发建议保持 `SERPAPI_LIVE_ENABLED=false`，避免调试时误烧 SerpAPI 额度。

### 3. 安装前端依赖

```bash
cd frontend/DsAgentChat_web
npm install
```

### 4. 启动服务

```bash
# 后端（默认端口 9000）
cd llm_backend
python run.py

# 前端（开发模式）
cd frontend/DsAgentChat_web
npm run dev
```

---

## 项目结构

```
TravelMind-main/
├── llm_backend/                    # 后端
│   ├── app/
│   │   ├── api/travel.py           # 旅行 API + SSE 推送
│   │   ├── lg_agent/               # LangGraph 工作流
│   │   │   └── travel_draft_graph.py  # 4 节点状态图
│   │   ├── services/               # 业务服务
│   │   │   ├── conversation_service.py
│   │   │   ├── travel_clarification_service.py
│   │   │   ├── recall_service.py
│   │   │   ├── ranking_scorer.py
│   │   │   ├── constraint_filter.py
│   │   │   ├── evidence_builder.py
│   │   │   └── providers/          # 检索 Provider
│   │   │       ├── orchestrator.py    # 并行编排
│   │   │       ├── amap.py
│   │   │       └── serp.py
│   │   ├── domain/travel/          # 领域规则
│   │   │   └── patch_engine.py        # Edit Day N
│   │   └── schemas/
│   │       └── itinerary_v1.py        # 行程契约
│   └── tests/                      # 测试
│       ├── test_performance_regression.py  # 性能回归 (9 tests)
│       └── test_e2e_performance.py         # E2E 性能测试
├── frontend/DsAgentChat_web/       # 前端
│   └── src/
│       ├── views/TravelPlanner.vue    # 主工作台
│       └── services/api.ts            # SSE 事件处理
├── docs/                           # 文档
│   ├── performance-analysis-report.md  # 性能优化分析报告
│   ├── design.md                       # 工程设计文档
│   ├── task.md                         # 任务拆解
│   └── requirement.md                  # 产品需求
└── README.md
```

---

## 测试

```bash
cd llm_backend

# 性能回归测试（9 项，全 mock）
py -X utf8 -m pytest tests/test_performance_regression.py -v

# 全量测试
py -X utf8 -m pytest -v
```

---

## 文档

| 文档 | 说明 |
|------|------|
| [性能优化分析报告](docs/performance-analysis-report.md) | STAR 结构，含实测数据、选型决策、行业对标 |
| [工程设计文档](docs/design.md) | 架构设计、流程定义、Schema 契约 |
| [任务拆解](docs/task.md) | 里程碑与任务分解 |
| [产品需求](docs/requirement.md) | 产品目标与功能范围 |

---

## License

MIT
