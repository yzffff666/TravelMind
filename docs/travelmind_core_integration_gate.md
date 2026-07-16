# TravelMind Core Integration Gate

## 目标

这个门禁用于固定 TravelMind 当前最关键的可交付链路：

```text
创建/追问意图识别
→ 局部编辑与候选驱动重规划
→ QA 不误触发行程修改
→ SSE edit_diff / final_itinerary 契约
→ 前端 diff 展示、QA 状态、类型检查与生产构建
```

它不是完整压测，也不调用真实 Provider 或 LLM；它的定位是本地快速回归，保证核心演示路径不会被日常改动破坏。

## 运行命令

在后端目录运行：

```bash
cd llm_backend
./.venv/bin/python -m scripts.milestone_runner
```

如需固定 run id，方便对比报告：

```bash
./.venv/bin/python -m scripts.milestone_runner --run-id local-core-gate-check
```

输出文件位于：

```text
llm_backend/reports/milestone-runs/<run_id>/
├── status.json
├── failures.json
└── summary.txt
```

## 当前 Gate

| Gate | 覆盖内容 |
| --- | --- |
| `qp_eval` | 96 条 QP 规则评测，防止 create / edit / qa / reset 路由退化 |
| `ranking_eval` | 离线 POI 排序 badcase 评测，验证好候选 Top-K 命中、bbox/duplicate/generic 拒绝 |
| `backend_core_integration_tests` | QP、patch engine、day replan、edit_diff、QA、SSE envelope、runner 自测 |
| `frontend_chat_component_tests` | DiffCard 与 PhaseIndicator，防止编辑结果重复展示、QA 状态误导 |
| `frontend_type_check` | Vue/TypeScript 类型契约 |
| `frontend_production_build` | 前端生产构建可用性 |

## 通过标准

```text
milestone=travelmind-core-integration-gate
status=passed
gates=6/6 passed
```

如果任一 Gate 失败，先看：

```text
llm_backend/reports/milestone-runs/<run_id>/failures.json
```

里面会保留失败命令、返回码和输出尾部。

## 使用时机

建议在这些场景运行：

- 修改 QP / intent routing 之后。
- 修改 `POIRankingPolicy`、bbox 或候选排序权重之后。
- 修改 patch engine / day replan 之后。
- 修改 SSE event payload 或前端聊天展示之后。
- 准备演示或 push 前。

## 单独运行排序评估

如果只想验证 POI 候选排序策略，可以运行：

```bash
cd llm_backend
./.venv/bin/python -m scripts.ranking_eval_report --output-dir reports/ranking-eval/latest
```

报告会输出：

```text
reports/ranking-eval/latest/
├── ranking-eval-report.json
└── ranking-eval-report.md
```

当前评估集覆盖：

- 目的地 bbox 错误：例如普吉岛候选混入巴黎 POI、上海候选混入东京 POI。
- 重复 POI：同一地点来自不同 provider 时只保留高质量候选。
- 泛活动：拒绝“核心景点参观”“室内休闲活动”这类不可落地图的泛化候选。
- 好候选 Top-K：检查高证据、高可解析、目的地一致的 POI 是否进入 policy top。

## 边界

这个 Gate 不能替代真实浏览器联调。它只保证核心逻辑和前端构建不退化。

如果要验证完整用户体验，还需要启动：

```bash
cd llm_backend && ./.venv/bin/python run.py
cd frontend/DsAgentChat_web && npm run dev
```

然后在浏览器中实际测试：

```text
帮我规划上海3天，预算6000，喜欢文化和美食
把第二天改轻松一点
第三天下午去哪里
```
