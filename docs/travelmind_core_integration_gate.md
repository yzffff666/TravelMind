# TravelMind Core Integration Gate

## 目标

这个门禁用于固定 TravelMind 当前最关键的可交付链路：

```text
创建/追问意图识别
→ 多轮会话目标保持、目的地切换与状态迁移
→ Provider 候选发布门禁（坐标/目的地/Mock/数量）
→ 可灰度 POI 排序与约束规划
→ 局部编辑与候选驱动重规划（复用同一门禁）
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
| `hybrid_qp_eval` | 30 条 Hybrid Structured QP holdout，验证 Rule/LLM 路由、shadow、异常回退及 QA/Edit 状态安全门禁 |
| `structured_edit_replan_eval` | 15 条结构化编辑命令验收，验证 target day/slot/constraint 映射，以及 QA、越界、无约束输入零修改 |
| `explicit_poi_edit_eval` | 16 条指定 POI 编辑验收，验证中英文地点名不会退化为原文替换或泛化约束，越界/QA 不产生修改请求 |
| `golden_demo_eval` | 演示主链路 golden cases，覆盖深圳/香港/澳门/旧金山 create、QA 只读、局部重规划、跨城 bbox |
| `ranking_eval` | 20 个目的地、63 个候选的离线排序门禁，比较 legacy/candidate 命中率，并验证跨城、缺坐标、Mock、duplicate、generic 拒绝、证据覆盖与 P95 |
| `planner_eval` | 12 个约束规划案例，验证不重复、预算、日内距离、室内约束、锁定日期与候选不足降级 |
| `unseen_destination_eval` | 10 个未配置 bbox/alias 的城市，验证动态目的地 Profile、本地候选接受、跨城候选拒绝与候选不足安全降级 |
| `destination_readiness_eval` | 12 个中外混合城市矩阵，验证静态/动态 Profile、坐标必填发布门槛、东京/京都等跨城干扰拒绝，以及证据/图片覆盖质量信号 |
| `multi_turn_conversation_eval` | 24 组、49 turn 的确定性回放，覆盖目的地切换/提及只读、QA 不误改、模糊澄清、闲聊目标保持、连续编辑与 reset 恢复 |
| `backend_core_integration_tests` | QP、patch engine、day replan、edit_diff、QA、SSE envelope、候选人工审核、目的地 grounding 契约、runner 自测 |
| `frontend_chat_component_tests` | DiffCard 与 PhaseIndicator，防止编辑结果重复展示、QA 状态误导 |
| `frontend_type_check` | Vue/TypeScript 类型契约 |
| `frontend_production_build` | 前端生产构建可用性 |

## 通过标准

```text
milestone=travelmind-core-integration-gate
status=passed
gates=14/14 passed
```

如果任一 Gate 失败，先看：

```text
llm_backend/reports/milestone-runs/<run_id>/failures.json
```

里面会保留失败命令、返回码和输出尾部。

## 使用时机

建议在这些场景运行：

- 修改 QP / intent routing 之后。
- 修改多轮对话状态、澄清、目的地切换、连续编辑或 reset 逻辑之后。
- 修改 Structured QP 路由、模型 schema、置信度阈值或安全回退之后。
- 修改 Structured QP 到 PatchOp、候选重规划或局部 slot 替换之后。
- 修改指定 POI 替换、名称匹配或目的地过滤之后。
- 修改演示主链路、QA/edit 边界、局部重规划之后。
- 修改 `POIRankingPolicy`、bbox 或候选排序权重之后。
- 修改跨天 POI 组合、预算/距离/节奏约束或局部重规划策略之后。
- 修改动态目的地解析、Provider 地理编码或未见城市候选过滤之后。
- 修改 patch engine / day replan 之后。
- 修改 SSE event payload 或前端聊天展示之后。
- 准备演示或 push 前。

## 单独运行多轮会话回放

```bash
cd llm_backend
./.venv/bin/python -m scripts.multi_turn_conversation_eval \
  --output-dir reports/multi-turn-conversation-eval/latest
```

通过标准是 `24/24 cases` 且 `49/49 turns`。评测集按六类平均分布：

```text
destination_switch
destination_mention_readonly
qa_readonly
flexible_clarification
chat_goal_retention
edit_reset_recovery
```

失败报告会给出 `case_id`、类别、具体 turn、原始 query、expected/actual
差异。该 gate 直接复用生产的 `ConversationDecisionService`、状态迁移和
澄清服务，但不调用真实 LLM、地图或搜索 Provider，因此可以稳定地放进
本地回归与 CI；外部服务质量仍由 live probe 和浏览器联调验证。

## 单独运行排序评估

如果只想验证演示主链路 golden cases，可以运行：

```bash
cd llm_backend
./.venv/bin/python -m scripts.golden_demo_eval --output-dir reports/golden-demo-eval/latest
```

报告会输出：

```text
reports/golden-demo-eval/latest/
├── golden-demo-eval.json
└── golden-demo-eval.md
```

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

- 20 个中外目的地，覆盖国内、东亚、东南亚、欧洲和北美。
- 目的地 bbox 错误：例如普吉岛候选混入巴黎 POI、上海候选混入东京 POI。
- 重复 POI：同一地点来自不同 provider 时只保留高质量候选。
- 泛活动：拒绝“核心景点参观”“室内休闲活动”这类不可落地图的泛化候选。
- 好候选 Top-K：检查高证据、高可解析、目的地一致的 POI 是否进入 policy top。
- 排序 Guardrail：`unsafe_accepted_count == 0`、candidate 命中率不低于 legacy、证据覆盖不低于 80%、P95 低于 50ms。

运行时通过 `POI_RANKING_MODE` 灰度和回滚：

```text
legacy    只使用旧 RankingScorer
shadow    新旧排序同时计算，规划器仍使用旧排序（默认）
candidate 新 POIRankingPolicy 真正进入创建和局部重规划
```

无论使用哪种排序，创建和局部重规划都会先经过共享发布门禁。目的地无法定位、有效候选不足、候选服务异常时系统 fail-closed，不会把 Mock 或未经验证的地点交给 LLM 自由生成。

## 单独运行约束规划评测

```bash
cd llm_backend
./.venv/bin/python -m scripts.planner_eval --output-dir reports/planner-eval/latest
```

该评测固定覆盖 12 个 create/local-replan 决策案例：紧凑路线、不同节奏、室内硬约束、预算上限、锁定日期不重复、锚点距离、候选不足和自动降低每日 POI 密度。通过时，Planner P95 必须低于 `200ms`。

## 真实 Structured QP Shadow 回放

真实模型回放不属于默认 milestone，避免消耗 API 额度。它只保留 Rule 路由结果、记录 Structured QP 观察值，不会修改 itinerary 或数据库：

```bash
cd llm_backend
./.venv/bin/python -m scripts.structured_qp_shadow_eval \
  --output reports/structured-qp-shadow/manual-run.json
```

v1 已完成两轮 12 条回放：两轮均 `12/12` 通过，7 次模型调用的 P95 分别为 `2427ms` 和 `2622ms`，低于 `4s` timeout。默认配置仍为 `off`；可在本地或灰度用 `STRUCTURED_QP_MODE=selective` 启用。

## 未见城市与真实 Provider 验证

离线未见城市门禁不依赖外部地图接口，验证的是动态目的地 Profile、跨城候选拒绝、候选不足降级和创建/重规划图级契约：

```bash
cd llm_backend
./.venv/bin/python -m scripts.unseen_destination_eval \
  --output-dir reports/unseen-destination-eval/latest
```

它固定覆盖 10 个没有生产静态 bbox/alias 的城市，其中 8 个具备足够的本地候选、2 个必须走候选不足降级。

真实 Provider 探测不调用 LLM，默认只跑 6 个国内未见城市；需要显式确认才会发起网络请求：

```bash
./.venv/bin/python -m scripts.live_destination_grounding_probe \
  --allow-live \
  --output reports/live-destination-grounding-probe.json
```

通过条件是至少 6 个目的地解析成功、至少 4 个目的地获得 3 个以上通过地理校验的候选；任何未通过的城市必须输出 `profile_unresolved` 或 `insufficient_candidates`，而不是交给 LLM 生成串城行程。

## 目的地就绪度矩阵

`destination_readiness_eval` 是离线、可重复的产品安全门禁。它不调用 Provider 或 LLM，而是固定验证“什么候选允许进入最终行程”：

```bash
cd llm_backend
./.venv/bin/python -m scripts.destination_readiness_eval \
  --output-dir reports/destination-readiness-eval/latest
```

当前 12 个案例覆盖深圳、香港、澳门、东京、京都、旧金山，以及景德镇、敦煌、喀什、Tromso、Hobart、Oaxaca。`ready` 案例必须至少有 3 个经过目的地校验且带合法经纬度的本地候选；候选不足案例必须安全降级。图片和证据覆盖会作为质量信号输出，但不会替代地理安全门禁。

真实 Provider probe 的结果会额外输出 `provider_capabilities`、`source_counts`、`evidence_candidate_count`、`image_candidate_count`、`quality_flags` 与 `health_status`。其中每个 Provider 分别报告 `key_configured`、`live_enabled` 与 `cache_enabled`，避免把“SerpAPI 已配但受成本护栏限制为 cache-only”误判为未配置。`ready` 只表示可以安全规划；`degraded` 表示候选足够但 Provider 或媒体质量有告警；只有 `healthy` 才表示该次探测没有这些告警。这能区分“代码泛化逻辑通过”与“当前环境是否真的具备某个海外城市的数据源”，避免 Mock 或离线 fixture 掩盖能力缺口。

2026-07-23 的 Candidate Runtime 验收中，离线 13 Gate 全部通过；真实探针则显示国内 6 城中 4 城 ready，海外 Tromso/Hobart/Valletta 尚未 ready。该结果按 `profile_unresolved` / `insufficient_candidates` 安全降级，不影响离线安全门禁结论，但会作为下一阶段 Provider 泛化目标。

## 边界

这个 Gate 不能替代真实浏览器联调或真实 Provider 就绪度探测。它保证离线决策安全、核心逻辑和前端构建不退化；某个城市是否有足够真实候选，仍需 live probe 验证。

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
