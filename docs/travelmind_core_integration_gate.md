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

双语会话内核当前作为独立验收运行，尚未计入 17 个默认 Gate。原因是
完整双语体验还需要前端英文默认界面、语言切换和浏览器双语验证；后端先行
通过不代表整套 UI 已完成。

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

运行后端双语会话内核验收：

```bash
./.venv/bin/python -m scripts.bilingual_conversation_eval \
  --output-dir reports/bilingual-conversation-eval/latest
```

当前基线：

```text
cases=20/20 passed
turns=42
language_drift=0
wrong_language_final_responses=0
state_persistence_failures=0
missing_language_metadata=0
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
| `learned_ranking_eval` | 576 条分级 query-candidate 样本、48 个请求、12 个目的地的 pairwise 排序门禁；训练/验证/测试目的地 ID 隔离，校验 catalog/dataset/model 指纹一致性，并比较 rule/learned NDCG@5、偏好 Top-3、hard gate 安全与推理 P95 |
| `planner_eval` | 12 个约束规划案例，验证不重复、预算、日内距离、室内约束、锁定日期与候选不足降级 |
| `unseen_destination_eval` | 10 个未配置 bbox/alias 的城市，验证动态目的地 Profile、本地候选接受、跨城候选拒绝与候选不足安全降级 |
| `destination_readiness_eval` | 12 个中外混合城市矩阵，验证静态/动态 Profile、坐标必填发布门槛、东京/京都等跨城干扰拒绝，以及证据/图片覆盖质量信号 |
| `overseas_candidate_supply_eval` | 4 个 Geoapify 脱敏快照回放，真实执行目的地消歧与 Places 候选发布，验证 Tromso/Hobart/Valletta 可发布、Oaxaca 候选不足安全降级，以及远距离/近距离邻城与 Mock 零发布 |
| `multi_turn_conversation_eval` | 48 组、144 turn 的自然语言确定性回放；真实经过规则 QP、会话决策、澄清和状态迁移，覆盖目的地切换/提及只读、QA 不误改、灵活回答、闲聊目标保持、连续编辑、reset 恢复与歧义输入 |
| `demo_journey_eval` | 四场景旅程级组合验收连续运行两轮，串联真实 QP、会话决策、目的地发布门禁、线上候选排序选择（学习排序保持默认关闭）、约束规划、revision 与 SSE envelope；要求 8/8 通过且九项安全计数为零 |
| `bilingual_experience_eval` | English-first Vue 界面、EN/中文持久化切换、活跃页面静态中文清单与双语组件测试；后端 20 组、42 turn 双语会话测试同时纳入 backend gate |
| `backend_core_integration_tests` | QP、patch engine、day replan、edit_diff、QA、SSE envelope、候选人工审核、目的地 grounding 契约、runner 自测 |
| `frontend_chat_component_tests` | DiffCard 与 PhaseIndicator，防止编辑结果重复展示、QA 状态误导 |
| `frontend_type_check` | Vue/TypeScript 类型契约 |
| `frontend_production_build` | 前端生产构建可用性 |

## 通过标准

```text
milestone=travelmind-core-integration-gate
status=passed
gates=18/18 passed
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
- 修改界面文案、语言切换、数字格式或 `ui_locale` 请求契约之后。
- 准备演示或 push 前。

## 单独运行多轮会话回放

```bash
cd llm_backend
./.venv/bin/python -m scripts.multi_turn_conversation_eval \
  --output-dir reports/multi-turn-conversation-eval/latest
```

通过标准是 `48/48 cases`、`144/144 turns`、关键类别通过率
`100%`，并且六项状态安全计数均为零。评测集按八类平均分布：

```text
destination_switch
destination_mention_readonly
qa_readonly
flexible_clarification
chat_goal_retention
consecutive_local_edit
reset_recovery
malformed_ambiguous
```

失败报告会给出 `case_id`、类别、具体 turn、原始 query、expected/actual
差异，以及 QP 输出、决策对象、迁移前后状态。普通 turn 不允许在 fixture
中预填 QP 结果，而是从原始自然语言真实调用 `TravelQueryProcessor`，再
复用生产的 `ConversationDecisionService`、状态迁移和澄清服务。该 gate
不调用真实 LLM、地图或搜索 Provider，因此可以稳定地放进本地回归与 CI；
外部服务质量仍由 live probe 和浏览器联调验证。

六项硬安全指标为：QA/chat 零误修改、零误切城市、明确换城市零漏判、
换城市后零旧行程残留、连续编辑零目标偏移、灵活回答后零重复澄清。

## 单独运行四场景旅程验收

```bash
cd llm_backend
./.venv/bin/python -m scripts.demo_journey_eval \
  --repetitions 2 \
  --output-dir reports/demo-journey-eval/latest
```

四个场景分别是：

```text
景德镇：创建 → QA → 整天局部重规划
Tromso：创建 → QA → 英文单时段局部重规划
深圳切香港：创建 → QA → 换目的地 → 连续两次编辑
Oaxaca：候选不足 → 明确降级且不发布行程
```

通过标准是 `8/8 journey runs`、不少于 `24 turns`，并且 QA revision
污染、错误编辑目标、非目标修改、旧城市候选残留、跨城发布、Mock 发布、
降级时错误发布、缺少终态 SSE、revision 链错误九项计数全部为零。

该 Gate 使用脱敏候选快照和内存状态，但真实调用生产 QP、会话状态迁移、
候选发布门禁、排序策略、约束规划器和 SSE envelope。它是稳定的
journey-level 组合回归，不等价于浏览器自动化、MySQL 集成或 live Provider
基准；这些仍需最终演示探针补充。

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

## 单独运行学习排序评估

学习排序的数据、训练和评测都是离线可复现的，不调用 Provider 或 LLM：

```bash
cd llm_backend
./.venv/bin/python -m scripts.build_learned_ranking_dataset
./.venv/bin/python -m scripts.train_poi_ranker
./.venv/bin/python -m scripts.learned_ranking_eval \
  --output-dir reports/learned-ranking-eval/latest
```

数据集包含 576 条样本、48 个 query 和 12 个目的地，按目的地切分为
`8 train / 2 validation / 2 test`。标签来自可审查的
`curated_rubric_v1`，不是线上用户点击或真实 A/B 数据。

当前目的地 ID 隔离的 rubric 测试结果：

```text
rule NDCG@5                 0.693541
learned NDCG@5              1.0
rule preference Top-3       0.416667
learned preference Top-3    1.0
inference P95               < 1ms
unsafe accepted             0
hard-gate rejected          8
```

模型只重排 deterministic hard gate 已接受的候选。通过
`POI_LEARNED_RANKING_MODE=off|shadow|active` 灰度控制，模型缺失、损坏或
feature schema 不兼容时自动回退规则排序。门禁还会拒绝 train/validation/test
目的地交叉、模型训练指纹不一致、catalog 与生成 dataset 不一致以及 test row
被标记为训练输入等情况。上述数字只说明模型在共享 POI archetype 的 rubric
benchmark 上学会了偏好权重，不证明真实城市泛化，也不代表线上用户收益。

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

2026-07-27 起，`overseas_candidate_supply_eval` 使用脱敏后的 Geoapify
Geocoding 与 Places `properties + geometry` 结构回放海外候选供给。它会真实
执行目的地解析，覆盖 Hobart 同名城市与 Oaxaca 州/城市歧义；同时要求 Tromso、
Hobart、Valletta 各有至少 3 个真实结构候选可发布，Oaxaca fixture 明确走候选
不足降级，并固定验证远距离跨城、同州近距离邻城与 Mock 候选零发布。真实
Provider 的当前可用性仍由 live probe 单独验证，外部服务失败不会被离线
fixture 隐藏。

2026-07-27 最终 live probe 在禁用 Amap、SerpAPI 和 LLM 的条件下实现
`4/4 profiles resolved`、`4/4 destinations ready`。其中 Oaxaca 的真实
Provider 候选已经达到 ready；这被视为相对 fixture 安全降级预期的能力升级。

单独运行该门禁：

```bash
./.venv/bin/python -m scripts.overseas_candidate_supply_eval \
  --output-dir reports/overseas-candidate-supply-eval/latest
```

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
