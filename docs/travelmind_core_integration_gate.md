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
| `backend_core_integration_tests` | QP、patch engine、day replan、edit_diff、QA、SSE envelope、runner 自测 |
| `frontend_chat_component_tests` | DiffCard 与 PhaseIndicator，防止编辑结果重复展示、QA 状态误导 |
| `frontend_type_check` | Vue/TypeScript 类型契约 |
| `frontend_production_build` | 前端生产构建可用性 |

## 通过标准

```text
milestone=travelmind-core-integration-gate
status=passed
gates=5/5 passed
```

如果任一 Gate 失败，先看：

```text
llm_backend/reports/milestone-runs/<run_id>/failures.json
```

里面会保留失败命令、返回码和输出尾部。

## 使用时机

建议在这些场景运行：

- 修改 QP / intent routing 之后。
- 修改 patch engine / day replan 之后。
- 修改 SSE event payload 或前端聊天展示之后。
- 准备演示或 push 前。

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

