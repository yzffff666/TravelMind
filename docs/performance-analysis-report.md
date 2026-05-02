# TravelMind 性能优化与技术选型综合分析报告

> 版本：v5.8（观测闭环、QA 本地复用） | 日期：2026-05-02 | 作者：TravelMind Dev Team
>
> 说明：本文是“当前状态型”报告，保留核心数据、阶段演进和下一步判断；完整历史长文已归档到 [performance-analysis-report-v5.6-full-history.md](archive/performance-analysis-report-v5.6-full-history.md)。

---

## 1. 当前结论

TravelMind 的性能优化已经从“主链路可用”进入“成本、稳定性与缓存收益验证”阶段。当前已经完成的关键变化：

- LangGraph 从单节点重构为 `extract -> recall -> llm_draft -> postprocess` 四节点图，缺字段可毫秒级早退。
- Provider 检索和坐标回填已并行化，并补充 `provider_call`、`location_backfill`、`itinerary_quality_summary` 结构化日志。
- 前端已支持 SSE 渐进式展示，用户感知首屏从约 75s 降到约 8-15s。
- Structured QP 已落地并默认关闭，通过真实中文 30 条评测和本地灰度 smoke。
- LLM 调用已补 timeout、bounded retry 和 latency logging。
- Redis 语义缓存已从 `KEYS + Python 全扫` 升级为 `L1 exact + L2 FAISS + SCAN fallback`。
- 基于已有行程的 QA 已增加本地 fast path，明确问“第 N 天安排”时可跳过 Structured QP LLM。

当前最重要的后续工作不是继续大幅改架构，而是用真实样例和日志验证：

- LLM retry / timeout 的真实恢复率。
- `cache_source=exact|faiss|semantic_scan|miss` 的命中分布。
- Provider / backfill 的 P50/P95 与 fallback 原因。
- QA `qa_source=local_itinerary` 的命中率与未命中原因。
- Structured QP 从 30 条扩到 60-100 条后的稳定性。

---

## 2. 当前架构快照

```text
用户浏览器(Vue 3)
  -> FastAPI / SSE
  -> QP: rule baseline + optional Structured QP
  -> LangGraph: extract -> recall -> llm_draft -> postprocess
  -> Provider: Amap / SerpAPI / fallback
  -> Cache: Redis 真源 + L1 exact + FAISS L2 index
  -> MySQL: 用户、会话、行程状态
```

### 2.1 技术栈状态


| 模块            | 当前状态                                          | 主要剩余风险                            |
| ------------- | --------------------------------------------- | --------------------------------- |
| FastAPI / SSE | 主链路可用，支持渐进事件                                  | 前端对 `tool_result`、错误态和进度细节展示仍可增强  |
| LangGraph     | 四节点图，支持缺字段早退和节点级 perf                         | 仍未切到 `astream_events` 原生节点事件      |
| QP            | 规则 baseline + Structured QP feature flag      | Structured QP 样例量仍小，生产默认开启需继续观察   |
| DeepSeek LLM  | 已补 timeout/retry/latency logging              | 远程 API 仍是尾延迟核心来源                  |
| Provider      | 并行调用、timeout、结构化日志                            | 长尾海外 POI、evidence URL 缺失仍需扩样      |
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

---

## 6. 当前剩余 Gap


| 优先级 | Gap                   | 原因                                   | 推荐动作                                                             |
| --- | --------------------- | ------------------------------------ | ---------------------------------------------------------------- |
| 高   | 真实流量观测不足              | 已有日志但缺少汇总统计                          | 汇总 LLM P50/P95、retry 恢复率、cache hit 分布                            |
| 高   | EmbeddingProvider 未解耦 | `EMBEDDING_TYPE` 声明尚未接入缓存路径          | 抽象 embedding provider，支持 Ollama / sentence-transformers fallback |
| 中   | FAISS 多进程不共享          | 当前是进程内索引                             | 个人项目可接受；多实例部署时评估 Qdrant                                          |
| 中   | 请求去重非分布式              | 进程内 TTL guard                        | 多 worker 时改 Redis `SET NX`                                       |
| 中   | Provider 长尾样例不足       | 核心样例已过，长尾城市未统计                       | 扩展巴黎、伦敦、新加坡、纽约等样例集                                               |
| 中   | 前端进度透明度不足             | SSE 事件有了，但 UI 未充分展示 tool/provider 过程 | 展示 tool_result、阶段耗时、低置信度提示                                       |
| 中   | Structured QP 样例量不足   | 30 条不足以默认开启                          | 扩展到 60-100 条再决定默认策略                                              |
| 低   | QA fast path 覆盖面有限     | 当前优先覆盖 itinerary 结构内的天数、预算、某天安排        | 扩展交通/住宿/证据类本地回答，未命中再走 LLM                                      |


---

## 7. 下一步建议

推荐顺序：

1. **观测型性能分析测试**
   - 已新增 `llm_backend/scripts/observability_summary.py`，从 `logs/structured.log` 或兼容的 `logs/app.log` 文本日志统计 `llm_status`、`llm_attempts`、`cache_source`、Provider `elapsed_ms`。
   - 已新增 `llm_backend/scripts/observability_smoke.py`，按 `mini/extended` 用例集调用 `/travel/query` 并保存 SSE 事件。
   - 推荐命令：`python -m scripts.observability_smoke --base-url http://127.0.0.1:8000 --user-id 1 --case-set mini`，默认调用 `/api/travel/query`。
   - 详细说明见 [观测型性能分析测试](evaluation/观测型性能分析测试.md)。
   - 目标是从“功能完成”进入“真实数据驱动”。
2. **EmbeddingProvider 解耦**
  - 让 `EMBEDDING_TYPE` 真正生效。
  - Ollama 不可用时可走 `sentence-transformers` fallback。
3. **前端进度与错误态优化**
  - 展示“正在理解需求 / 检索资料 / 生成行程 / 坐标回填”。
  - 错误发生时避免旧 itinerary 让用户误以为成功。
4. **Structured QP 扩样**
  - 从 30 条扩到 60-100 条。
  - 加入中英混合、反悔表达、多城市、弱约束。
5. **再考虑 Qdrant / 分布式缓存**
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
核心结论：TravelMind 已从“完整生成但等待长”优化到“可渐进展示、可观测、可缓存复用”的阶段。

已完成：
- 四节点 LangGraph + 条件边早退
- Provider 并行 + POI 回填质量修复
- SSE 渐进式展示
- Structured QP MVP + 真实中文评测 + 灰度 smoke
- LLM timeout/retry + 请求去重
- Redis L1 exact + FAISS L2 语义缓存

剩余重点：
- 用日志统计真实 P50/P95、retry 恢复率、cache hit 分布
- 解耦 EmbeddingProvider
- 扩展 Structured QP 和 Provider 真实样例
- 优化前端进度和错误态可见性
```
