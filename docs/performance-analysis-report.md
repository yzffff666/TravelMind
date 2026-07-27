# TravelMind Agentic POI Ranking 与性能/质量综合分析报告

> 版本：v5.16（Agentic Candidate Decision Runtime v1） | 日期：2026-07-22 | 作者：TravelMind Dev Team
>
> 说明：本文是“当前状态型”报告，保留核心数据、阶段演进和下一步判断；完整历史长文已归档到 [performance-analysis-report-v5.6-full-history.md](archive/performance-analysis-report-v5.6-full-history.md)。

---

## 1. 当前结论

TravelMind 的主线已经从单纯的“性能优化项目”收束为“旅行规划 Agent 中的 POI 候选排序与决策质量系统”。

新的定位是：

```text
TravelMind = Agentic POI Ranking for Travel Planning
```

也就是说，性能、缓存、Provider 成本治理仍然重要，但它们现在是 guardrail；当前更核心的价值是把 Amap / SerpAPI / Mock Provider 返回的 POI 候选，变成可解释、可排序、可观测、可回归的 Agent 决策输入。当前已经完成的关键变化：

- LangGraph 从单节点重构为 `extract -> recall -> llm_draft -> postprocess` 四节点图，缺字段可毫秒级早退。
- Provider 检索和坐标回填已并行化，并补充 `provider_call`、`location_backfill`、`itinerary_quality_summary` 结构化日志。
- 前端已支持 SSE 渐进式展示，用户感知首屏从约 75s 降到约 8-15s。
- Structured QP 已落地并默认关闭，通过真实中文 30 条评测和本地灰度 smoke。
- LLM 调用已补 timeout、bounded retry 和 latency logging。
- Redis 语义缓存已从 `KEYS + Python 全扫` 升级为 `L1 exact + L2 FAISS + SCAN fallback`。
- 基于已有行程的 QA 已增加本地 fast path，明确问“第 N 天安排”时可跳过 Structured QP LLM。
- 双语链路已完成首轮闭环：`observability_smoke.py` 增加 `bilingual` 用例集，`original_query` 与 `recall_query` 分层，英文 create / QA 可按英文输出并进入 `response_language` 观测。
- `POIRankingPolicy` 已从固定 shadow 升级为 `legacy / shadow / candidate` 三档运行模式；candidate 模式可真实驱动创建与局部重规划，legacy 可即时回滚。
- 创建和局部重规划已复用共享 Candidate Publishability Gate：合法坐标、目的地一致、禁止生产 Mock、候选数量充足后才允许进入排序与规划。
- 候选服务异常、目的地未解析或候选不足时改为 fail-closed，不再调用 LLM 生成未经验证的地点。
- 排序评测已扩到 20 个目的地、63 个候选决策：candidate good-hit 100%，legacy 约 95.45%，unsafe accepted 0，evidence coverage 100%，规则排序 P95 远低于 50ms 门槛（以每次本地报告为准）。
- `observability_summary.py` 已能汇总 POI Ranking Shadow 的 accepted/rejected 数量、reject reasons、Top-K overlap 和 rejected samples，为后续排序策略迭代提供数据入口。
- Provider HTTP 失败已能被结构化诊断：SerpAPI live probe 复测确认当前 SerpAPI 失败是 HTTP `429` 额度耗尽（`Your account has run out of searches`），不是 query、bbox 或 ranking 策略问题。
- 低成本海外 Provider 已接入第一版：新增 Geoapify geocoding / places adapter，注册顺序调整为 `Amap -> Geoapify -> SerpAPI -> Mock`，让海外日常调试先走 `low_cost` provider，再用 SerpAPI 做 expensive fallback。
- Geoapify 已补本地 live 预算阀门：cache miss 才消耗 live；达到 `GEOAPIFY_DAILY_LIVE_LIMIT` 会返回 `budget_exhausted`；收到 HTTP 429 后进入 `budget_cooldown`，避免继续撞额度。

当前最重要的后续工作不是继续零散修 POI alias，而是用 shadow ranking 观测把“哪些候选该进入 LLM”这件事量化清楚：

- `poi_ranking_shadow` 的 Top-K overlap：新策略和旧策略到底差多少。
- reject reasons：主要是在拒绝泛地点、bbox invalid、duplicate，还是误伤真实 POI。
- rejected samples：把被拒候选变成人工 audit 的最小样本集。
- accepted/rejected rate 与 Backfill unresolved、LLM draft 质量之间的关系。
- 双语/海外 POI 的 alias、bbox、evidence coverage 是否应该进入 ranking feature，而不是继续散落在 backfill 小修里。
- LLM retry、cache_source、response_language、QA fast path 等性能指标继续保留为质量系统的成本/稳定性 guardrail。
- Provider 成本与可用性也要继续作为 guardrail：当 SerpAPI 额度不可用时，Amap 对海外 POI 的 recall 质量不足会让 ranking 没有候选可排；Geoapify 的作用是先补一个便宜的海外候选来源，让后续 ranking / backfill 评估有数据可用。

---

## 2. 当前架构快照

```text
用户浏览器(Vue 3)
  -> FastAPI / SSE
  -> QP: rule baseline + optional Structured QP
  -> LangGraph: extract -> recall -> llm_draft -> postprocess
  -> Provider: Amap / SerpAPI / fallback
  -> Publishability Gate: destination / geo / mock / candidate count
  -> POI Ranking Runtime: legacy / shadow / candidate
  -> Constraint Planner -> verified plan skeleton -> LLM Draft
  -> Cache: Redis 真源 + L1 exact + FAISS L2 index
  -> MySQL: 用户、会话、行程状态
```

### 2.1 技术栈状态


| 模块            | 当前状态                                          | 主要剩余风险                            |
| ------------- | --------------------------------------------- | --------------------------------- |
| FastAPI / SSE | 主链路可用，支持渐进事件                                  | 前端对 `tool_result`、错误态和进度细节展示仍可增强  |
| LangGraph     | 四节点图，支持缺字段早退和节点级 perf                         | 仍未切到 `astream_events` 原生节点事件      |
| QP            | 规则 baseline + Structured QP feature flag      | Structured QP 样例量仍小，生产默认开启需继续观察   |
| DeepSeek LLM  | 已补 timeout/retry/latency logging，并完成 draft 输出瘦身 | 远程 API 仍是尾延迟核心来源，后续继续验证更多真实样例 |
| Provider      | 并行调用、timeout、结构化日志                            | Provider 调用已较快，剩余风险集中在长尾 POI 质量和 evidence URL |
| POI Ranking   | 三档灰度模式已接入 create/replan；20 城离线门禁通过 | 真实 Provider 覆盖和自然分布 badcase 仍需持续积累 |
| Redis / FAISS | Redis 存 response/vector/meta，FAISS 做进程内 L2 检索 | 多进程下 FAISS index 不共享，后续可评估 Qdrant |
| Embedding     | 仍使用 Ollama embedding                          | `EMBEDDING_TYPE` 配置尚未真正生效         |


---

## 3. 关键指标

### 3.1 性能指标


| 指标          | 优化前       | 当前状态                    | 说明                    |
| ----------- | --------- | ----------------------- | --------------------- |
| 用户感知首屏      | ~75s      | ~8-15s                  | SSE 渐进式展示带来主要体验收益     |
| 完整草案 E2E    | ~85s      | ~40-70s 估算              | 仍受远程 LLM 波动影响         |
| Pipeline 检索 | ~12s      | ~3s 估算                  | Provider 并行化后下降明显     |
| 缺字段早退       | ~75s      | <2ms                    | LangGraph 条件边 + QP 门槛 |
| 已有行程 QA      | ~2.3-2.5s 单轮观测 | 23.5ms E2E / 6.04ms 本地回答 | 跳过 Structured QP LLM，直接复用 itinerary |
| Extended backfill | attempted 8 / filled 3 / skipped 1 / unresolved 5 | attempted 7 / filled 4 / skipped 2 / unresolved 3 | 目的地清洗、POI alias、泛地点跳过后，unresolved 从 5 降到 3 |
| Extended LLM latency | N/A | P50 16.15s / P95 18.53s / avg 12.16s | 2026-05-03 extended smoke，当前主耗时来源 |
| LLM draft 输出瘦身 | output p50 3370 / p95 4535，LLM P50 15112ms / P95 20091ms | output p50 1327 / p95 1787，LLM P50 6007ms / P95 8066ms | slot 输出仅保留 `slot/activity/place`，预算/证据/校验交给后处理 |
| mock 图节点开销  | N/A       | ~6ms                    | 说明本地图执行不是瓶颈           |
| 完全重复 query  | 原无缓存      | exact hit 可跳过 embedding | Redis response key 命中 |
| 相似 query    | Python 全扫 | FAISS L2 检索             | Redis 仍是真源，FAISS 可重建  |


### 3.2 质量与回归数据


| 验证项                    | 结果                                             |
| ---------------------- | ---------------------------------------------- |
| 后端全量回归                 | 最近一次：355 passed                                |
| Structured QP 真实中文评测   | rule baseline 26/30，Structured QP 30/30        |
| Structured QP 灰度 smoke | create / clarification / reset / edit / QA 均通过 |
| 国内 POI smoke           | 上海/北京核心样例 6/6 可回填                              |
| 海外 POI smoke           | 东京/大阪/普吉岛核心样例从 2/9 提升到 9/9                     |
| 缓存单测                   | exact hit、FAISS hit、FAISS fallback、cleanup 均覆盖 |


---

## 4. 优化演进时间线


| 阶段                 | 目标               | 核心改动                                                      | 结果                           |
| ------------------ | ---------------- | --------------------------------------------------------- | ---------------------------- |
| v5.0 基线分析          | 找出主链路瓶颈          | 记录单节点图、串行 Provider、LLM 一次性生成问题                            | 明确用户空等约 75s，Draft E2E 约 85s  |
| v5.1 图重构与渐进渲染      | 降低感知等待           | LangGraph 四节点、Provider 并行、SSE day_ready、缺字段早退             | 首屏降至约 8-15s，缺字段 <2ms         |
| v5.3 E2E 联调        | 修复真实链路阻断         | 地图渲染、编辑 diff、QA 路由、预算冲突、局部回填                              | 国内/海外地图主链路可展示                |
| v5.4 Provider 评测   | 提升 POI 精度与可观测性   | SerpAPI `place_results`、普吉老镇别名、provider/backfill 日志       | 海外核心样例 2/9 -> 9/9            |
| v5.5 Structured QP | 提升自然语言理解         | LLM structured output、Pydantic schema、confidence/fallback | 30 条真实中文 query 30/30，默认关闭    |
| v5.6 LLM 稳定性       | 降低远程 API 失败影响    | timeout、bounded retry、latency logging、请求去重                | 后端回归通过，具备观测重试恢复率能力           |
| v5.7 缓存稳定性         | 降低重复/相似 query 成本 | Redis SCAN、L1 exact、FAISS L2、cache_source 日志              | 消除 `KEYS`，相似检索不再常规 Python 全扫 |
| v5.8 观测闭环与 QA 复用   | 用真实观测驱动下一步优化      | observability smoke/summary、QA local fast path              | QA 从约 2.3s 降至 23.5ms E2E |
| v5.9 Backfill 诊断与 POI 清洗 | 用 unresolved 样例驱动质量优化 | Backfill unresolved samples、目的地清洗、POI alias、泛地点跳过、provider list/dict 字段兼容 | Extended backfill 从 `8/3/1/5` 改善到 `7/4/2/3`，海外 create smoke 通过 |
| v5.10 LLM draft 输出瘦身 | 降低远程 LLM 生成成本 | draft prompt 增加 output 约束，slot 只让 LLM 生成 `slot/activity/place`，补 `response_language` 诊断字段 | Extended create 明显下降：国内约 18.0s -> 10.2s，海外约 33.8s -> 16.0s |
| v5.11 双语观测闭环 | 验证英文/中英混合输入输出 | 新增 `bilingual` smoke，传递 `original_query` 保护语言判断，QA fast path 和 draft explanation 支持英文输出 | bilingual smoke 4/4 通过，draft language `{"en": 1, "zh-CN": 1}`，英文 QA 约 17ms |
| v5.12 Agentic POI Ranking shadow | 把 Provider 候选排序变成可观测决策问题 | 新增 `POIRankingPolicy`、`CandidateFeature`、`poi_ranking_shadow` 日志和 summary 汇总 | 新策略先只旁路观测，不改变主链路，下一步用 rejected samples 和 overlap 决定是否收紧规则 |
| v5.13 Provider HTTP 诊断 | 区分 Provider 失败是额度、认证、限流、参数还是服务不可用 | SerpAPI HTTP 错误包装为结构化异常，Provider 日志补 `http_status_code` / `error_response_snippet`，summary 汇总 HTTP 状态与响应片段 | live probe 确认 SerpAPI 当前为 HTTP 429 额度耗尽；ranking 无候选不是策略问题，而是 upstream recall 不可用 |
| v5.14 低成本海外 Provider | 减少海外 smoke / 数据集积累对 SerpAPI 的依赖 | 新增 `GeoapifySearchProvider` / `GeoapifyMapProvider`、响应缓存、HTTP 诊断与 factory 注册顺序 | `PROVIDER_COST_MODE=cheap` 下仍可使用 Geoapify，SerpAPI 被跳过；新增单测覆盖解析、缓存、factory 顺序和 429 映射 |
| v5.15 Provider 额度阀门 | 防止低成本 Provider 也被调试流量用爆 | Geoapify 增加每日 live 上限、429 冷却状态和 `budget_exhausted` / `budget_cooldown` cache source | API 用完时系统进入可观测降级，不继续打 live；cache 命中不消耗预算 |
| v5.16 Candidate Decision Runtime | 让候选安全和排序策略真实进入 create/replan | 共享 publishability gate、fail-closed、三档排序模式、20 城排序评测 | 13/13 milestone 通过；真实国内 probe 4 城 ready，海外 probe 暴露召回/城市归一化缺口且均安全停止 |

### 4.1 2026-07-23 真实 Provider 就绪度

预算受控 live probe 不调用 LLM，也不允许 Mock 候选：

- 国内 6 城：4 城达到 `ready`，景德镇和喀什 `profile_unresolved`；ready 城市因 Geoapify timeout 或图片覆盖不足标记为 `degraded`。
- 海外 4 城：Tromso 0 个、Hobart 2 个可发布候选，Valletta Profile 未解析，Oaxaca 按预期候选不足。
- 海外主要拒绝原因为 `outside_destination_radius` 与 `candidate_city_mismatch`，说明下一阶段优先修 Provider 召回与城市字段归一化，不应先调排序权重。
- 所有 not-ready 案例均在 LLM 前 fail-closed，没有用 Mock 或自由生成掩盖数据源缺口。


---

## 5. 已完成优化细节

### 5.1 LangGraph 与 SSE

优化前，行程生成逻辑集中在一个长函数里，检索、生成、后处理、异常兜底耦合在一起。优化后拆成四个节点：

```text
extract -> recall -> llm_draft -> postprocess
```

收益：

- 缺字段请求直接早退，不进入 Provider 和 LLM。
- 每个节点可单测、可记录 `perf`。
- 前端能基于 SSE 逐步展示 intent、stage、day、final itinerary。

保留的历史数据：mock 环境下完整图 4 节点平均约 6.25ms，说明本地图编排不是主要延迟来源。

### 5.2 Provider 与 POI 回填

Provider 层已从串行调用改为有限预算下的并行调用，并补齐真实 Provider smoke：


| 样例                       | 修复前 | 修复后 | 说明                                      |
| ------------------------ | --- | --- | --------------------------------------- |
| 上海：外滩 / 豫园 / 东方明珠        | 3/3 | 3/3 | 国内高德链路稳定                                |
| 北京：故宫 / 天坛 / 颐和园         | 3/3 | 3/3 | 国内 POI 坐标均可回填                           |
| 东京：浅草寺 / 涩谷 / 东京晴空塔      | 2/3 | 3/3 | `place_results` 解析后补齐涩谷                 |
| 大阪：环球影城 / 大阪城公园 / 道顿堀    | 0/3 | 3/3 | 精确地点查询恢复有效坐标                            |
| 普吉岛：芭东海滩 / 普吉老镇 / 普吉国际机场 | 2/3 | 3/3 | 增加 Old Phuket Town / Phuket Old Town 别名 |

近期基于 `observability-summary.md` 的 `Backfill Unresolved Samples` 表继续补齐了 backfill 闭环：

- `location_backfill_service.py` 在 provider 前清洗目的地，避免 `普吉岛轻松`、`成都亲子三天` 这类污染文本进入地图查询。
- 对 `普吉老城`、`普吉周末夜市`、`Phuket Weekend Market`、`The Boathouse Wine & Grill` 增加稳定别名。
- 对 `酒店泳池/附近海滩` 等相对泛地点跳过 provider，避免无意义查询拖慢尾延迟。
- 对 provider 返回 `address` 为 list/dict 的情况做防御性归一化，避免候选打分阶段异常。

最新 extended smoke（2026-05-03，本地真实链路）：

| 指标 | 优化前诊断轮 | POI 清洗后 |
| --- | --- | --- |
| 海外创建 | 通过 / 曾暴露一次 provider 字段类型异常 | 通过，11 个 SSE 事件完整返回 |
| Backfill | attempted 8 / filled 3 / skipped 1 / unresolved 5 | attempted 7 / filled 4 / skipped 2 / unresolved 3 |
| 主要剩余样例 | `普吉老城`、`The Boathouse`、`酒店泳池/附近海滩` 等 | `Central Phuket Florist`、`普吉周末夜市 或 Chillva Market`、`查龙寺` |

结论：Backfill 已从“看不清失败原因”推进到“可按样例定点修复”。剩余 3 个 unresolved 仍可继续优化，但相对 LLM draft 主耗时，优先级已下降。


### 5.3 Structured QP

Structured QP 解决的是规则 intent router 过硬、上下文编辑和模糊表达不自然的问题。当前状态：

- 默认 `ENABLE_STRUCTURED_QP=false`。
- 开启后低置信度、异常、超时、JSON/schema 校验失败都会回退 rule baseline。
- `travel.py` 已记录 `qp_source/confidence/fallback_reason`。

真实中文评测结果：


| 指标         | rule baseline | Structured QP |
| ---------- | ------------- | ------------- |
| Intent 准确率 | 26/30（86.67%） | 30/30（100%）   |
| 低置信度       | 不适用           | 0/30          |
| 调用失败       | 不适用           | 0/30          |


保留结论：Structured QP 有明显收益，但样例量仍小，不建议直接生产默认开启。

### 5.4 LLM 稳定性

已补齐：

- 草案生成 LLM 的 timeout / retry / backoff。
- 澄清/闲聊 LLM 的 timeout / retry。
- `llm_attempts`、`llm_status`、latency logging。
- `/travel/query` 和 `/travel/resume` 的进程内 5s 请求指纹去重。
- `llm_draft_call` 已补 `prompt_chars`、`candidate_section_chars`、`candidate_count`、`output_chars`、`days_count`、`destination`、`parse_status`、`response_language`。
- draft 输出已瘦身：LLM 只生成核心行程骨架和 POI，预算细分、证据、校验、坐标由后处理补齐。

输出瘦身验证（2026-05-03，本地 extended smoke）：

| 指标 | 瘦身前 | 瘦身后 |
| --- | --- | --- |
| 国内创建 E2E | 17993.36 ms | 10191.42 ms |
| 海外创建 E2E | 33845.56 ms | 15956.85 ms |
| LLM latency | P50 15112.07 ms / P95 20091.28 ms | P50 6006.58 ms / P95 8066.29 ms |
| Draft output chars | P50 3370 / P95 4535 | P50 1327 / P95 1787 |
| Draft prompt chars | P50 2005 / P95 2200 | P50 1482 / P95 1677 |

结论：当前 LLM 主耗时更受输出生成长度影响，而不是 prompt 或候选注入体积。先瘦身输出比继续压 prompt 更有效。

注意：文档里的 `tenacity` 是已安装依赖，但当前实现没有强依赖 tenacity，而是使用显式 bounded retry 和 `asyncio` timeout。后续可以保留现状，除非需要更复杂的 retry policy。

### 5.5 Redis / FAISS 缓存

当前缓存层已经从“能用”进入“可观测、可扩展”的阶段：

```text
lookup(messages)
  -> L1 exact response key
  -> embedding
  -> FAISS IndexFlatIP search
  -> Redis GET response by hash_id
  -> fallback semantic_scan if FAISS unavailable
```

关键设计：

- Redis 是真源：保存 `resp / vec / meta`。
- FAISS 是进程内加速层：可懒加载、可重建。
- exact hit 不调用 embedding。
- FAISS 不可用不影响主链路，会回退 `semantic_scan`。
- 日志区分 `cache_source=exact|faiss|semantic_scan|miss`。

### 5.6 Agentic POI Ranking Shadow

当前新增的 POI Ranking 不是直接替换旧逻辑，而是先以 shadow mode 运行：

```text
Provider candidates
  -> legacy RankingScorer + ConstraintFilter
  -> shadow POIRankingPolicy
  -> poi_ranking_shadow structured log
  -> observability_summary POI Ranking Shadow section
```

关键设计：

- `CandidateFeature` 把原始 Provider 候选归一成可比较特征，例如 `alias_hit`、`bbox_valid`、`has_geo`、`evidence_score`、`provider_confidence`、`is_generic_activity`。
- `POIRankingPolicy` 分两层判断：hard gate 先拒绝明显不该进入候选池的项，soft score 再给剩余候选排序。
- `build_ranking_shadow_report` 对比 legacy ranking 和 policy ranking，记录 Top-K overlap、reject reasons、accepted/rejected 数量和 rejected samples；rejected samples 会保留坐标、地址和 `score_breakdown`，便于人工 audit。
- `travel_draft_graph.py` 当前仍使用旧 ranking 结果进入后续链路，shadow policy 只写日志，因此改动风险低。

这一步的长期意义是：把“LLM 为什么选了这个 POI”前移到可解释的候选排序层，而不是等到 Backfill unresolved 后再补洞。

---

## 6. 当前剩余 Gap


| 优先级 | Gap                   | 原因                                   | 推荐动作                                                             |
| --- | --------------------- | ------------------------------------ | ---------------------------------------------------------------- |
| 高   | POI Ranking shadow 样本不足 | 已有 `poi_ranking_shadow` 日志，但还缺少真实 smoke 下的稳定对比 | 跑 mini/extended/bilingual smoke，优先看 Top-K overlap、reject reasons、误伤样例 |
| 高   | Geoapify 真实链路尚未跑完整 smoke | 低成本 provider 已通过 Phuket 小探针，且有预算阀门；但还未进入完整 SSE / backfill / ranking 链路评估 | 在预算保护开启下跑 `live_probe` 或小型 bilingual smoke，观察 `geoapify_*` 的 filled、bbox/score rejected、budget 状态和 cost tier |
| 高   | CandidateFeature 仍偏规则化 | 当前特征覆盖 bbox、alias、evidence、provider confidence，但还不够表达偏好和约束 | 从 rejected samples 中补充 preference、budget、transport、evidence URL 等特征 |
| 中   | LLM draft 长尾仍需更多真实样例 | 已完成输出瘦身，但样本仍少，远程 LLM 波动存在 | 持续记录 `prompt_chars/output_chars/response_language`，作为 ranking 改造的成本 guardrail |
| 中   | EmbeddingProvider 未解耦 | `EMBEDDING_TYPE` 声明尚未接入缓存路径          | Stage B 语义 rerank 前再抽象 embedding provider，支持 Ollama / sentence-transformers fallback |
| 中   | FAISS 多进程不共享          | 当前是进程内索引                             | 个人项目可接受；多实例部署时评估 Qdrant                                          |
| 中   | 请求去重非分布式              | 进程内 TTL guard                        | 多 worker 时改 Redis `SET NX`                                       |
| 中   | Provider / Backfill 双语长尾仍明显 | 最新 bilingual smoke 中 backfill attempted 10 / filled 4 / unresolved 6；SerpAPI 已受成本模式保护 | 默认 cache-only，关键回归再设 `PROVIDER_COST_MODE=full` 或 `SERPAPI_LIVE_ENABLED=true` 跑真实海外 smoke |
| 中   | 前端进度透明度不足             | SSE 事件有了，但 UI 未充分展示 tool/provider 过程 | 展示 tool_result、阶段耗时、低置信度提示                                       |
| 中   | Structured QP 样例量不足   | 30 条不足以默认开启                          | 扩展到 60-100 条再决定默认策略                                              |
| 低   | QA fast path 覆盖面有限     | 当前优先覆盖 itinerary 结构内的天数、预算、某天安排        | 扩展交通/住宿/证据类本地回答，未命中再走 LLM                                      |


---

## 7. 下一步建议

推荐顺序：

1. **跑一轮 POI Ranking Shadow 观测回归**
   - 使用同一批 mini/extended/bilingual smoke，收集 `poi_ranking_shadow`。
   - 优先看 `top_k_overlap_rate`、`reject_reason_counts`、`policy_accepted_count`、`policy_rejected_count` 和 `POI Ranking Rejected Samples`。
   - 如果 overlap 很低，要先人工 audit rejected samples，不能直接把新 policy 切成主路径。
2. **基于 rejected samples 调整 CandidateFeature**
   - 如果误伤来自 alias/bbox，就补 alias 或 bbox 策略。
   - 如果误伤来自偏好/预算/交通语义，就补 feature，而不是继续在 backfill 里硬编码。
   - 如果拒绝确实合理，再考虑把对应 hard gate 从 shadow 推进到主链路 guardrail。
3. **继续观测型性能分析测试**
   - `observability_summary.py` 已能统计 LLM、Provider、Backfill、QP、QA，并展示 `Backfill Unresolved Samples` 与 `POI Ranking Shadow`。
   - `observability_smoke.py` 已能按 `mini/extended/bilingual` 调用 `/travel/query` 并保存 SSE 事件与单次 structured log 窗口。
   - Geoapify 是低成本海外 provider，SerpAPI 默认 cache-only；真实 expensive smoke 需显式打开 `PROVIDER_COST_MODE=full` 或 `SERPAPI_LIVE_ENABLED=true`，避免日常调试误烧额度。
   - 新增 `live_probe` 单用例集，用最小真实海外请求验证 SerpAPI / Amap / LLM / POI Ranking Shadow 链路。
   - 如果 Provider summary 出现 SerpAPI `HTTP status counts: {"429": ...}` 且响应包含 `Your account has run out of searches`，应先处理额度/供应商可用性，不要把问题误判为 ranking 或 alias。
   - 推荐命令：`python -m scripts.observability_smoke --base-url http://127.0.0.1:8000 --user-id 1 --case-set bilingual`。
   - 详细说明见 [观测型性能分析测试](evaluation/观测型性能分析测试.md)。
4. **扩展更多城市的双语 Provider 样例**
   - 优先修 `查龙寺/Wat Chalong`、`Maya Bay/玛雅湾` 等明确 POI alias 和 bbox 拒绝样例。
   - 在普吉岛外扩展巴黎、伦敦、新加坡、纽约等英文/中英混合目的地，避免只对单城过拟合。
5. **EmbeddingProvider 解耦**
  - 让 `EMBEDDING_TYPE` 真正生效。
  - Ollama 不可用时可走 `sentence-transformers` fallback。
6. **前端进度与错误态优化**
  - 展示“正在理解需求 / 检索资料 / 生成行程 / 坐标回填”。
  - 错误发生时避免旧 itinerary 让用户误以为成功。
7. **Structured QP 扩样**
  - 从 30 条扩到 60-100 条。
  - 加入中英混合、反悔表达、多城市、弱约束。
8. **再考虑 Qdrant / 分布式缓存**
  - 只有当缓存规模、多 worker、持久化索引需求出现时再做。

---

## 8. 历史数据附录

### 8.1 性能基线


| 接口 / 阶段       | 优化前 P50 | 优化前 P95 | 备注             |
| ------------- | ------- | ------- | -------------- |
| `GET /health` | <5ms    | <10ms   | 无 I/O          |
| 多轮澄清          | ~2s     | ~3.5s   | 含短 LLM         |
| Draft 端到端     | ~75s    | ~90s    | 主要瓶颈           |
| Pipeline 检索   | ~12s    | ~20s    | 优化前串行 Provider |
| LLM 生成        | ~63s    | ~70s    | 远程 API 主导      |


### 8.2 核心 E2E 联调样例


| 用例                         | 结果                              |
| -------------------------- | ------------------------------- |
| 上海 4 天，预算 6000，情侣，文化+美食    | 完整行程、地图和逐天渲染正常                  |
| 想去海边玩几天，轻松一点               | 进入澄清，不误生成                       |
| 北京 3 天，预算 1500，亲子，市中心+热门景点 | 生成预算冲突并结构化展示                    |
| 普吉岛 5 天，预算 12000，情侣，海边+美食  | 海外地图切到 OpenStreetMap 并正常显示      |
| 上海行程中途修改：第 2 天下午换东方明珠      | 返回 `edit_diff`，changed day 局部回填 |
| 第 2 天安排是什么？                | 正确走 QA，不修改 revision             |


### 8.3 关键设计取舍


| 问题          | 选择                                         | 理由                          |
| ----------- | ------------------------------------------ | --------------------------- |
| 图重构方式       | 一体化重构 + 优化                                 | 避免无价值中间态，四节点图释放条件边和 perf 能力 |
| 流式方案        | `ainvoke` 后逐天推送，而非立即切 `astream_events`     | 用户体验足够接近，测试和兼容风险更低          |
| Provider 并行 | `asyncio.gather`                           | Provider 已是 async 接口，不引入队列  |
| QP 增强       | rule baseline + Structured QP feature flag | 保留可解释兜底，模型路径可灰度             |
| 缓存索引        | Redis 真源 + FAISS 加速                        | 零新增服务，先验证收益，再考虑 Qdrant      |


### 8.4 历史归档

完整历史版文档保留了更细的推导、阶段计划、行业对标和长表格：

- [performance-analysis-report-v5.6-full-history.md](archive/performance-analysis-report-v5.6-full-history.md)
- [Structured-QP真实中文评测记录.md](evaluation/Structured-QP真实中文评测记录.md)
- [Structured-QP灰度验证记录.md](evaluation/Structured-QP灰度验证记录.md)
- [E2E-smoke-验证记录.md](evaluation/E2E-smoke-验证记录.md)

---

## 9. 快速引用

```text
核心结论：TravelMind 已从“完整生成但等待长”优化到“可渐进展示、可观测、可缓存复用、可控制 LLM 输出成本、可观测双语输入输出”的阶段；当前主线进一步收束为 Agentic POI Ranking，即把 Provider 候选变成可解释、可排序、可回归的 Agent 决策输入。

已完成：
- 四节点 LangGraph + 条件边早退
- Provider 并行 + POI 回填质量修复
- SSE 渐进式展示
- Structured QP MVP + 真实中文评测 + 灰度 smoke
- LLM timeout/retry + 请求去重
- Redis L1 exact + FAISS L2 语义缓存
- Backfill unresolved samples 诊断表
- 目的地清洗、POI alias、泛地点跳过与 provider 字段健壮性修复
- LLM draft prompt/output 诊断与输出瘦身
- `response_language` 诊断字段与 `original_query` 语言链路
- bilingual smoke 样例覆盖英文 create / QA / edit 和中英混合 POI
- `POIRankingPolicy` rule-based baseline
- `poi_ranking_shadow` 旁路观测与 summary 汇总
- Provider HTTP 状态、错误响应片段与 SerpAPI 额度耗尽诊断
- Geoapify 低成本海外 Provider、缓存与 factory 注册顺序

剩余重点：
- 跑 POI Ranking Shadow 观测回归，人工 audit rejected samples
- 用真实 `GEOAPIFY_KEY` 跑最小 overseas smoke，验证低成本 provider 是否能给 ranking 提供可用候选
- 基于误伤样例补 CandidateFeature，再决定哪些 hard gate 能进入主链路
- 用日志统计真实 P50/P95、retry 恢复率、cache hit 分布
- 解耦 EmbeddingProvider
- 扩展 Structured QP 和 Provider 真实样例
- 优化前端进度和错误态可见性
```
