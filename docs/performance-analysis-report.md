# TravelMind 性能优化分析报告

> 版本：v2.0 | 日期：2026-04-03 | 作者：TravelMind Dev Team

---

## 目录

1. [Situation — 现状与背景](#1-situation--现状与背景)
2. [Task — 优化目标与约束](#2-task--优化目标与约束)
3. [Action — 架构重构 + 性能优化一体化方案](#3-action--架构重构--性能优化一体化方案)
4. [Result — 预期优化效果](#4-result--预期优化效果)
5. [附录 — 技术细节与执行计划](#5-附录--技术细节与执行计划)

---

## 1. Situation — 现状与背景

### 1.1 系统架构概览

```
用户 ──→ Vue 3 前端 (SSE) ──→ FastAPI 后端 ──→ LangGraph 单节点图
                                    │
                    ┌───────────────┼───────────────────┐
                    ▼               ▼                   ▼
              意图路由(QP)    多轮对话(Chat)       行程草案(Draft)
              ~10ms           2-3s                 70-90s ❌
                                                     │
                                          ┌──────────┼──────────┐
                                          ▼          ▼          ▼
                                    Pipeline     LLM 生成    后处理
                                    10-20s       63-68s      <1s
```

### 1.2 技术栈

| 层级 | 技术选型 | 备注 |
|------|---------|------|
| 前端 | Vue 3 + Vite + TypeScript | SSE 流式接收 |
| 后端框架 | FastAPI + Uvicorn | 异步 Python |
| 工作流引擎 | LangGraph (StateGraph) | **单节点图 ← 核心架构问题** |
| LLM | DeepSeek Chat API (远程) | `deepseek-chat` 模型, temperature=0.7 |
| 搜索 | 高德 Amap + SerpAPI + Mock | 串行调用 |
| 数据库 | MySQL (SQLAlchemy) + Redis | 会话/缓存 |

### 1.3 关键接口性能基线（实测数据）

基于 API 实测，排除本地代理干扰后的真实延迟数据：

| 接口 / 阶段 | P50 | P90 | P95 | 备注 |
|------------|-----|-----|-----|------|
| `GET /health` | <5ms | <10ms | <10ms | 健康检查，无 I/O |
| `GET /travel/state/{id}` | ~5ms | ~12ms | ~15ms | MySQL 单行查询 |
| `POST /conversations` | ~8ms | ~15ms | ~20ms | MySQL 写入 |
| 多轮澄清 (Guided) | ~2s | ~3s | ~3.5s | 含 1 次 LLM 短生成 |
| **行程草案 (Draft) 端到端** | **~75s** | **~85s** | **~90s** | **核心瓶颈** |
| ├─ Pipeline (QP→Recall→Rank→Filter→Evidence) | ~12s | ~18s | ~20s | 检索+重排 |
| ├─ LLM 生成 (ainvoke) | ~63s | ~68s | ~70s | 远程 API 单次调用 |
| └─ 后处理 (evidence link + coverage) | <0.5s | <1s | <1s | 纯内存运算 |

### 1.4 问题严重度分析

**行程草案端到端耗时 70-90 秒，远超用户可接受阈值（目标 < 20 秒首屏）。**

耗时分布：

```
Pipeline 检索阶段    ████████████░░░░░░░░░░░░░░░░░░░░░░░░░  15%  (~12s)
LLM 草案生成        ████████████████████████████████████░░  80%  (~65s)
后处理              ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   1%  (<0.5s)
前端渲染+网络       ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   4%  (~3s)
```

**用户等待体验**：用户发送请求后，除一个 `stage_start(draft_plan)` 骨架屏事件外，需等待约 75 秒才能看到任何实质内容。整个等待期间前端只显示加载状态，没有渐进式反馈。

### 1.5 架构瓶颈：单节点 LangGraph 图

当前行程草案生成的 LangGraph 图结构为**单一巨型节点**：

```
当前：START → [ generate_travel_draft ] → END
                     │
                     ├── 约束提取 (extract_*)
                     ├── QP 处理 (query_processor)
                     ├── 检索召回 (recall_service)
                     ├── 排序过滤 (ranking + filter)
                     ├── 证据构建 (evidence_builder)
                     ├── LLM 调用 (ainvoke, 阻塞 65s)
                     ├── JSON 解析 (_parse_llm_itinerary)
                     └── 后处理 (_postprocess_with_pipeline)
                     
                     140 行逻辑，5 个串行阶段，全部塞在一个函数里
```

`generate_travel_draft` 函数包含约 140 行业务逻辑，涵盖从约束提取到最终行程输出的全部阶段。这种设计将 LangGraph 退化为普通函数调用器，**封死了所有关键优化路径**：

| 被阻塞的优化 | 原因 |
|-------------|------|
| **节点级流式输出** | LangGraph 的 `astream_events` 在每个节点完成时才推送事件，单节点 = 全部完成才推送 |
| **阶段并行** | Pipeline 与 LLM 大纲在架构上可以并行，但单节点内只能串行 |
| **条件路由** | 缓存命中跳过 recall、短行程走轻量 Prompt 等分支逻辑无法在图级别实现 |
| **独立重试** | LLM 节点超时只能在函数内 try-catch，无法用 LangGraph 的 retry 机制 |
| **细粒度监控** | 无法按节点统计耗时，只能手动在函数内打埋点 |
| **中间状态观测** | 无法在 Pipeline 完成后、LLM 开始前暂停/观测图状态 |

**关键结论**：单节点不是延迟的直接原因，但它是**性能优化的天花板**。不改架构，后续所有优化只能在函数内部"绕路"实现，代码复杂度高且收益打折。

---

## 2. Task — 优化目标与约束

### 2.1 性能目标

| 指标 | 当前值 | 阶段一目标 | 阶段二目标 |
|------|--------|-----------|-----------|
| 首屏内容时间 (TTFC) | ~75s | < 15s | < 8s |
| 完整草案时间 (E2E) | ~85s | < 30s | < 20s |
| Pipeline 检索阶段 | ~12s | < 3s | < 1s |
| LLM 生成阶段 | ~65s | < 25s | < 15s |
| 用户感知等待时间 | ~75s | < 10s | < 5s |

### 2.2 约束条件

1. **预算约束**：当前使用 DeepSeek 远程 API，无自建 GPU 资源
2. **架构约束**：保持 FastAPI + LangGraph 框架不变，增量优化
3. **功能约束**：不降低行程质量（景点真实性、预算分配合理性）
4. **人力约束**：1 人 2 天冲刺周期

### 2.3 核心策略

**图重构与性能优化一体化实施**。拆节点的过程即实施优化的过程——每拆出一个独立节点，就同步带入该阶段对应的性能优化。一次改动完成两件事，避免"先优化再重构"或"先重构再优化"的重复劳动。

```
一体化策略示意：

拆出 [extract] 节点  ──→  顺手完成：消除重复 QP 解析
拆出 [recall]  节点  ──→  顺手完成：Provider 并行化 + 缓存判断
拆出 [llm_draft] 节点 ──→ 顺手完成：流式生成 + Prompt 压缩
保留 [postprocess] 节点 ──→ 原有逻辑不变（已足够快）
```

---

## 3. Action — 架构重构 + 性能优化一体化方案

### 3.0 图重构：从单节点到多节点（前置工作，贯穿全过程）

#### 目标架构

```
              ┌─────────────────────────────────────────────────────┐
              │            TravelDraftState（共享状态）              │
              │  query, destination, days, budget, traveler_type,   │
              │  preferences, pipeline_result, raw_llm, itinerary,  │
              │  explanation, assumptions, perf_metrics             │
              └─────────────────────────────────────────────────────┘

START → [extract_node] → [recall_node] → [llm_draft_node] → [postprocess_node] → END
              │                │                │                      │
         约束提取+校验    并行检索+排序     流式LLM生成           证据链接+覆盖
         ~10ms             ~3s              ~35s (流式)           ~0.5s
```

#### 新 State Schema 设计

```python
class TravelDraftState(TypedDict):
    # ── 输入 ──
    query: str

    # ── extract_node 写入 ──
    destination: str | None
    days_count: int | None
    total_budget: float | None
    traveler_type: str | None
    preferences: list[str]
    pace: str | None
    assumptions: list[str]
    missing_p0: list[str]          # 非空时，后续节点全部跳过

    # ── recall_node 写入 ──
    pipeline_result: dict | None   # PipelineResult 序列化
    recall_degraded: bool

    # ── llm_draft_node 写入 ──
    raw_llm_content: str | None
    itinerary: dict | None         # ItineraryV1 序列化

    # ── postprocess_node 写入 ──
    final_itinerary: dict | None
    explanation: str | None
    final_text: str | None

    # ── 性能指标（每个节点写入自身耗时）──
    perf: dict
```

#### 条件路由能力

多节点架构使以下条件分支成为可能：

```python
def should_skip_remaining(state: TravelDraftState) -> str:
    """P0 字段缺失时，跳过 recall/LLM/postprocess，直接返回提示文本。"""
    if state.get("missing_p0"):
        return "early_exit"
    return "recall_node"

def should_skip_recall(state: TravelDraftState) -> str:
    """缓存命中时跳过 recall，直接进入 LLM。"""
    if state.get("pipeline_result"):  # 已有缓存结果
        return "llm_draft_node"
    return "recall_node"

builder.add_conditional_edges("extract_node", should_skip_remaining, {
    "early_exit": END,
    "recall_node": "recall_node",
})
```

#### 重构对 LangGraph 能力的释放

| LangGraph 能力 | 单节点时 | 多节点后 |
|---------------|---------|---------|
| `graph.astream_events()` | 只在全部完成后发出 1 个事件 | 每个节点完成即发出事件，实现分阶段 SSE 推送 |
| 并行节点 | 不可用 | 可将 recall 与 LLM 大纲并行（远期） |
| 条件边 (conditional_edges) | 不可用 | 缓存命中跳过 recall、P0 缺失提前退出 |
| 节点级 retry | 不可用 | LLM 节点单独 retry，不影响已完成的 recall |
| State checkpoint | 无中间状态 | recall 完成后可恢复，避免 LLM 失败重跑 recall |
| 性能观测 | 手动在函数内 `time.perf_counter()` | 自动按节点统计耗时 |

---

### 3.1 extract_node — 约束提取 + 消除重复解析

#### 当前问题

用户查询被解析两次：
- `travel.py` L641：API 入口处 `query_processor.process(query)` 用于意图分类
- `travel_draft_graph.py` L309-319：图节点内重新调用 `extract_*` 函数做约束提取

两次解析同一查询，CPU 浪费 + 延迟增加。

#### 优化方案

将 `extract_node` 设计为接收上游已解析的约束（通过 State 传入），节点内只做校验和默认值填充，不重复调用 `extract_*`：

```python
async def extract_node(state: TravelDraftState) -> dict:
    t0 = time.perf_counter()
    query = state["query"]

    destination = state.get("destination") or extract_destination(query)
    days_count = state.get("days_count") or extract_days(query)
    total_budget = state.get("total_budget") or extract_budget(query)
    traveler_type = state.get("traveler_type") or extract_traveler_type(query)

    missing_p0 = []
    if not destination: missing_p0.append("目的地")
    if not days_count: missing_p0.append("天数")
    if total_budget is None: missing_p0.append("预算")

    assumptions = []
    if not traveler_type:
        assumptions.append(DRAFT_CONFIG.traveler_default_assumption)

    preferences = [kw for kw in QP_RULES.preference_keywords if kw in query]
    pace = next((v for k, v in QP_RULES.pace_keywords.items() if k in query), None)

    return {
        "destination": destination,
        "days_count": days_count,
        "total_budget": total_budget,
        "traveler_type": traveler_type,
        "preferences": preferences,
        "pace": pace,
        "assumptions": assumptions,
        "missing_p0": missing_p0,
        "perf": {**state.get("perf", {}),
                 "extract_ms": (time.perf_counter() - t0) * 1000},
    }
```

**预计收益**：-0.5s（消除重复解析）+ 架构清晰度提升。

---

### 3.2 recall_node — 并行检索 + 缓存快路径

#### 当前问题

**瓶颈 1：Provider 串行调用**

`ProviderOrchestrator.recall()` 中搜索和地图 Provider 是逐个串行 `await` 调用：

```86:103:TravelMind-main/llm_backend/app/services/providers/orchestrator.py
        if self._policy.is_enabled(ProviderType.SEARCH):
            for sp in self._registry.search_providers:
                if result.calls_made >= self._policy.max_calls_per_request:
                    result.assumptions.append(
                        "已达到单次请求调用上限，部分搜索源未调用。"
                    )
                    break
                await self._call_search(sp, query, context, result)

        if self._policy.is_enabled(ProviderType.MAP):
            kw = keywords or [query]
            for mp in self._registry.map_providers:
                if result.calls_made >= self._policy.max_calls_per_request:
                    result.assumptions.append(
                        "已达到单次请求调用上限，部分地图源未调用。"
                    )
                    break
                await self._call_map(mp, city, kw, context, result)
```

Amap Search + SerpAPI Search + Amap Map + SerpAPI Map + Mock Search + Mock Map = 最多 6 个 Provider，各自 10 秒超时。串行排列后理论最差 60 秒，实测 ~12 秒。

#### 优化方案

**Provider 并行化（预计收益 -8~12s）**：将串行 `for...await` 改为 `asyncio.gather`。

```python
# orchestrator.py 优化后
async def recall(self, *, query, city, keywords, context):
    key = _cache_key(query, city, keywords)
    cached = _recall_cache.get(key)
    if cached:
        ts, cached_result = cached
        if time.time() - ts < _RECALL_CACHE_TTL:
            return cached_result
        del _recall_cache[key]

    tasks = []
    if self._policy.is_enabled(ProviderType.SEARCH):
        for sp in self._registry.search_providers[:self._policy.max_calls_per_request]:
            tasks.append(self._call_search_safe(sp, query, context))

    if self._policy.is_enabled(ProviderType.MAP):
        kw = keywords or [query]
        remaining = self._policy.max_calls_per_request - len(tasks)
        for mp in self._registry.map_providers[:remaining]:
            tasks.append(self._call_map_safe(mp, city, kw, context))

    responses = await asyncio.gather(*tasks, return_exceptions=True)

    result = OrchestratorResult()
    result.calls_made = len(tasks)
    for resp in responses:
        if isinstance(resp, Exception):
            result.degraded = True
            result.assumptions.append(f"Provider 调用异常：{resp}")
        elif resp is not None:
            self._merge_response(resp, result, "parallel")

    result.candidates = self._dedup(result.candidates)
    if not result.degraded and result.candidates:
        _recall_cache[key] = (time.time(), result)
    return result
```

改造前：`t(Amap_S) + t(Serp_S) + t(Amap_M) + t(Serp_M)` ≈ 12s
改造后：`max(t(Amap_S), t(Serp_S), t(Amap_M), t(Serp_M))` ≈ 3s

**recall_node 封装**：

```python
async def recall_node(state: TravelDraftState) -> dict:
    t0 = time.perf_counter()

    if state.get("missing_p0"):
        return {}  # 条件边已处理 early_exit，此处兜底

    qp, recall_svc, scorer, flt, eb = _get_pipeline()
    qp_output = qp.process(state["query"])
    recall_result = await recall_svc.recall_from_qp(qp_output)
    ranked = scorer.rank_from_qp(recall_result.candidates, qp_output, top_k=15)
    filter_result = flt.apply_from_qp(ranked, qp_output)
    pipeline_result = eb.build(filter_result, recall_result)

    return {
        "pipeline_result": pipeline_result,
        "recall_degraded": pipeline_result.degraded,
        "perf": {**state.get("perf", {}),
                 "recall_ms": (time.perf_counter() - t0) * 1000},
    }
```

**预计收益**：Pipeline 阶段从 ~12s 降至 ~3s（-75%）。

---

### 3.3 llm_draft_node — 流式生成 + Prompt 压缩

#### 当前问题

**瓶颈 1：单次长生成，无流式输出**

当前使用 `llm.ainvoke(messages)` 做一次性同步生成，等待 LLM 返回完整 JSON 后才开始处理：

```400:406:TravelMind-main/llm_backend/app/lg_agent/travel_draft_graph.py
        messages = [
            {"role": "system", "content": TRAVEL_DRAFT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        logger.info(f"Calling LLM for travel draft: {destination} {days_count}天 预算{int(total_budget)}")
        response = await llm.ainvoke(messages)
```

用户在整个 LLM 生成期间（~65s）看不到任何内容，未设置 `max_tokens` 限制。

**瓶颈 2：Prompt 冗余**

User Prompt 包含完整 JSON 模板定义（~800+ 字符），每天 3 个 slot 的完整 `cost_breakdown` 结构重复展示。输入 ~1500-2000 token，输出 ~3000-5000 token。

#### 优化方案

**LLM 流式生成 + 前端渐进渲染（最高性价比优化）**

这是对用户体验影响最大的单项优化。不改变 LLM 总生成时间，但通过流式输出极大改善用户感知：

1. 后端将 `ainvoke` 改为 `astream`，边接收 token 边通过 SSE 推送
2. 后端实时解析流中的 JSON 片段，每完成一天的行程发送 `day_ready` SSE 事件
3. 前端收到 `day_ready` 立即渲染该天卡片

```
当前体验（无流式 + 单节点）：

  用户发送 ──── Pipeline 12s ──── LLM 65s ──── 一次性看到全部行程
           └── 空白等待 75s ───────────────────┘

优化后体验（流式 + 多节点 astream_events）：

  用户发送 ── "搜索中..."(3s) ── "找到15个地点" ── 第1天(10s) ── 第2天 ── ... ── 完成
               ↑ recall_node      ↑ recall完成      ↑ llm_draft_node 流式推送
               完成时推送          事件推送           逐天推送
```

**llm_draft_node 核心实现**：

```python
async def llm_draft_node(state: TravelDraftState) -> dict:
    t0 = time.perf_counter()
    t_first_token = None

    llm = _get_llm()  # 添加 max_tokens=4096
    user_prompt = build_compressed_prompt(state)
    candidates_section = _format_candidates_for_prompt(state.get("pipeline_result"))
    if candidates_section:
        user_prompt += candidates_section

    messages = [
        {"role": "system", "content": TRAVEL_DRAFT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    buffer = ""
    async for chunk in llm.astream(messages):
        if chunk.content:
            if t_first_token is None:
                t_first_token = time.perf_counter()
            buffer += chunk.content

    itinerary = _parse_llm_itinerary(buffer, ...)

    return {
        "raw_llm_content": buffer,
        "itinerary": itinerary.model_dump(mode="json") if itinerary else None,
        "perf": {**state.get("perf", {}),
                 "llm_ms": (time.perf_counter() - t0) * 1000,
                 "llm_ttft_ms": (t_first_token - t0) * 1000 if t_first_token else None},
    }
```

**Prompt 压缩 + max_tokens 限制（预计收益 -10~20s 实际延迟）**

1. 精简 JSON 模板：去掉完整示例，改用极简指令
2. 添加 `max_tokens=4096`：防止模型生成冗余内容
3. 简化 cost_breakdown：4 字段压缩为单一 `estimated_cost`（减少 ~60% 输出 token）

压缩前：~1800 token input + ~4000 token output
压缩后：~800 token input + ~2000 token output → 输出减半 ≈ 生成时间减半

**预计综合收益**：
- 用户感知等待：从 ~75s 降至 ~10s（流式首屏）
- LLM 实际生成：从 ~65s 降至 ~35-45s（Prompt 压缩）

---

### 3.4 postprocess_node — 不变

当前后处理逻辑耗时 < 0.5s，无需优化。直接从单节点中拆出：

```python
async def postprocess_node(state: TravelDraftState) -> dict:
    t0 = time.perf_counter()

    itinerary_data = state.get("itinerary")
    pipeline_result = state.get("pipeline_result")

    if not itinerary_data:
        fallback_text = DRAFT_CONFIG.missing_p0_template.format(
            missing_fields="、".join(state.get("missing_p0", ["未知"]))
        )
        return {"final_itinerary": None, "explanation": None, "final_text": fallback_text}

    itinerary = ItineraryV1(**itinerary_data)
    _postprocess_with_pipeline(itinerary, pipeline_result, _get_pipeline()[4])

    explanation = _build_explanation(state)

    return {
        "final_itinerary": itinerary.model_dump(mode="json"),
        "explanation": explanation,
        "final_text": None,
        "perf": {**state.get("perf", {}),
                 "postprocess_ms": (time.perf_counter() - t0) * 1000},
    }
```

---

### 3.5 SSE 渐进式推送协议

多节点架构使外层 `travel.py` 可以使用 `graph.astream_events()` 监听每个节点的完成，自动推送分阶段 SSE 事件：

```
event: draft_plan_start     → 前端展示骨架屏
event: pipeline_progress    → "正在搜索 东京 相关景点..."     ← recall_node 开始
event: pipeline_complete    → "找到 15 个推荐地点"           ← recall_node 完成
event: llm_generating       → "正在为你规划行程..."          ← llm_draft_node 开始
event: day_ready            → { day_index: 1, ... }         ← 流式解析到第1天
event: day_ready            → { day_index: 2, ... }         ← 流式解析到第2天
...
event: budget_ready         → { budget_summary: {...} }      ← LLM 完成
event: draft_complete       → "行程生成完成"                 ← postprocess_node 完成
```

单节点时这些事件只能在函数内用回调/队列模拟，多节点后由 LangGraph 原生支持。

---

### 3.6 缓存体系优化

#### 问题根因

**Redis 语义缓存 O(n) 线性扫描**

当前 `RedisSemanticCache.lookup()` 使用 `redis.keys(pattern)` 获取所有缓存键，逐一计算余弦相似度：

```164:173:TravelMind-main/llm_backend/app/services/redis_semantic_cache.py
            pattern = f"{self.prefix}:vec:*"
            all_vectors = [key.decode('utf-8') for key in self.redis.keys(pattern)]
            max_similarity = 0
            most_similar_key = None
            for vec_key in all_vectors:
                cached_vector = json.loads(self.redis.get(vec_key.encode('utf-8')).decode('utf-8'))
                similarity = np.dot(current_vector, cached_vector) / (
                    np.linalg.norm(current_vector) * np.linalg.norm(cached_vector)
                )
```

- `redis.keys()` 是 **O(n) 全库扫描**，生产环境禁止使用
- 逐条取向量 + 计算相似度 = **O(n) 线性复杂度**
- 缓存条目增多后性能急剧恶化

#### 优化方案

**多级缓存体系**

```
L1: 精确命中缓存（Python dict, TTL 5min）
    ↓ miss
L2: 语义相似度缓存（Redis + HNSW 向量索引, TTL 1h）
    ↓ miss
L3: 热门行程模板缓存（Redis, TTL 24h）
    ↓ miss
    Full Pipeline + LLM 生成
```

- **L1**：内存字典，相同查询精确命中，延迟 < 1ms
- **L2**：将 `redis.keys()` + 线性扫描替换为 Redis Stack 的 `FT.SEARCH` 向量搜索（HNSW 索引），延迟 < 10ms
- **L3**：Top-50 热门目的地预生成行程模板，命中后直接返回或微调

---

### 3.7 远期方案：分步生成策略

将"一次生成全部天数"拆分为"大纲 + 按天并行生成"：

```python
# 策略：先生成行程大纲，再并行生成每天详情
outline = await llm.ainvoke(outline_prompt)  # ~5s: 返回每天的主题和关键景点

day_tasks = [
    llm.ainvoke(day_detail_prompt.format(day=d))
    for d in outline.days
]
day_results = await asyncio.gather(*day_tasks)  # 并行 ~10s (而非串行 ~50s)
```

注意事项：
- 需先确认 DeepSeek API rate limit
- 多次调用可能增加成本
- 需要合并逻辑保证上下文一致性
- 建议在阶段一优化见效后再考虑

---

### 3.8 方案汇总与优先级矩阵

| 优先级 | 方案 | 节点归属 | 描述 | 预计收益 | 实现复杂度 |
|-------|------|---------|------|---------|-----------|
| **P0** | 图重构 | 全局 | 单节点 → 4 节点 | 释放所有优化路径 | 中 |
| **P0** | Provider 并行化 | recall_node | `asyncio.gather` 替换串行循环 | Pipeline -8~12s | 低 |
| **P0** | LLM 流式生成 | llm_draft_node | `ainvoke` → `astream` | 用户感知 -50~60s | 中 |
| **P0** | Prompt 压缩 + max_tokens | llm_draft_node | 精简模板 + 限制输出 | LLM -10~20s | 低 |
| **P1** | SSE 渐进式协议 | travel.py + 前端 | 多节点事件 → SSE 分阶段推送 | 用户感知 -40s | 中 |
| **P1** | 消除重复 QP | extract_node | State 传递已解析约束 | -0.5s | 低 |
| **P2** | 热门查询预缓存 | recall_node 条件边 | 缓存命中跳过 recall | 命中时 -10s | 中 |
| **P2** | 多级缓存体系 | 全局 | L1/L2/L3 三级缓存 | 长期收益 | 高 |
| **P3** | 分步并行天生成 | llm_draft_node | 大纲 + 按天并行 | LLM -15~30s | 高 |

与 v1.0 报告的核心区别：**图重构不再是独立任务，而是每个优化方案的实施载体**。

---

## 4. Result — 预期优化效果

### 4.1 阶段一优化后预期（Day 1-2, 图重构 + P0/P1 方案）

| 指标 | 优化前 | 优化后 | 改善幅度 |
|------|--------|--------|---------|
| Pipeline 耗时 | 12s | 3s | **-75%** |
| LLM 实际生成耗时 | 65s | 35-45s | **-35~45%** |
| 用户首屏内容时间 | 75s | 8-12s | **-85%** |
| 完整草案时间 | 85s | 40-50s | **-45~55%** |
| 用户感知等待时间 | 75s | 8-12s | **-85%** |

**关键改善**：用户在 ~10 秒内即可看到第一天行程内容（recall 完成 + LLM 首天输出），而非空等 75 秒。

### 4.2 阶段二优化后预期（Day 3+, P2/P3 方案）

| 指标 | 阶段一后 | 阶段二后 | 改善幅度 |
|------|---------|---------|---------|
| Pipeline 耗时（缓存命中） | 3s | <0.5s | **-83%** |
| LLM 生成耗时（分步并行） | 35-45s | 15-20s | **-55%** |
| 用户首屏内容时间 | 8-12s | 3-5s | **-60%** |
| 完整草案时间 | 40-50s | 18-25s | **-50%** |

### 4.3 优化效果对比图

```
端到端延迟 (秒)

优化前(单节点)  ████████████████████████████████████████████████████████  85s
阶段一(多节点)  ██████████████████████████████                            45s  (-47%)
阶段二(+缓存)   █████████████████                                         22s  (-74%)
目标             ████████████████                                         20s

用户首屏时间 (秒)

优化前(单节点)  ████████████████████████████████████████████████████████  75s
阶段一(多节点)  ███████                                                   10s  (-87%)
阶段二(+缓存)   ███                                                        4s  (-95%)
目标             ██████                                                    8s
```

### 4.4 架构收益对比

| 维度 | 优化前（单节点） | 优化后（多节点） |
|------|----------------|-----------------|
| 代码结构 | 140 行单函数，职责混杂 | 4 个 30-50 行的聚焦函数 |
| 可测试性 | 只能端到端测试 | 每个节点可独立单测 |
| 可观测性 | 手动埋点 | LangGraph 自动按节点统计 |
| 扩展性 | 新增阶段需改大函数 | 新增节点，原有逻辑不动 |
| 故障隔离 | LLM 失败需在函数内处理 | 节点级 retry / fallback |
| 缓存集成 | 需在函数内 if-else | 条件边跳过整个节点 |

---

## 5. 附录 — 技术细节与执行计划

### 5.1 两天冲刺执行计划（重构 + 优化一体化）

#### Day 1 上午：搭建多节点骨架 + extract_node + recall_node

| 步骤 | 任务 | 预计耗时 |
|------|------|---------|
| 1 | 定义 `TravelDraftState` 新 schema，创建 4 个空节点函数 | 30min |
| 2 | 实现 `extract_node`：迁移约束提取 + 接收上游 QP 结果 | 30min |
| 3 | 实现 `recall_node`：迁移 Pipeline 逻辑 | 30min |
| 4 | **在 orchestrator.py 中实施 Provider 并行化** | 1h |
| 5 | 连接图 `extract → recall`，本地验证 Pipeline 阶段延迟 | 30min |

Day 1 上午交付物：Pipeline 阶段从 ~12s 降至 ~3s。

#### Day 1 下午 + 晚上：llm_draft_node + 流式输出

| 步骤 | 任务 | 预计耗时 |
|------|------|---------|
| 6 | 实现 `llm_draft_node`：迁移 LLM 调用 + `ainvoke` → `astream` | 2h |
| 7 | **Prompt 压缩**：精简 `draft_prompts.py` + 添加 `max_tokens` | 1h |
| 8 | 实现 `postprocess_node`：迁移后处理逻辑 | 30min |
| 9 | 完整图连接 + 条件边（missing_p0 提前退出） | 30min |
| 10 | **修改 `travel.py`**：用 `astream_events` 替换 `ainvoke`，按节点推送 SSE | 2h |
| 11 | **前端适配**：`TravelPlanner.vue` 监听 `day_ready` 事件渐进渲染 | 2h |

Day 1 交付物：首屏时间从 75s 降至 ~10s，多节点图全部连通。

#### Day 2：巩固 + 缓存 + 回归测试

| 步骤 | 任务 | 预计耗时 |
|------|------|---------|
| 12 | 热门查询预缓存 + recall 条件边 | 2h |
| 13 | Redis 语义缓存优化（L1 内存 + L2 改进） | 2h |
| 14 | 性能回归测试：重跑测试矩阵，验证 P50/P90/P95 | 2h |
| 15 | 性能监控埋点：确认 `perf` 字段在每个节点正确记录 | 1h |
| 16 | 修复测试中发现的问题 | 1h |

Day 2 交付物：缓存命中场景 < 5s，E2E P90 < 45s，全量回归通过。

---

### 5.2 验证方案

每完成一个节点，运行以下验证：

```bash
# 1. 单节点功能验证（Python 交互式）
python -c "
import asyncio
from app.lg_agent.travel_draft_graph import travel_draft_graph
result = asyncio.run(travel_draft_graph.ainvoke({'query': '去东京玩5天预算8000'}))
print(result.keys())
print(result.get('perf'))
"

# 2. 流式事件验证
python -c "
import asyncio
from app.lg_agent.travel_draft_graph import travel_draft_graph
async def test():
    async for event in travel_draft_graph.astream_events(
        {'query': '去东京玩5天预算8000'}, version='v2'
    ):
        if event['event'] == 'on_chain_end':
            print(f'Node: {event[\"name\"]}, Output keys: {list(event[\"data\"][\"output\"].keys())}')
asyncio.run(test())
"

# 3. 端到端 SSE 验证
curl -X POST http://127.0.0.1:8000/travel/query \
  -F 'query=去东京玩5天预算8000' -F 'user_id=1' \
  --no-buffer
```

---

### 5.3 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 多节点 State 序列化开销 | 每个节点边界增加几 ms | State 中 `pipeline_result` 使用 dict 而非 Pydantic model |
| 流式 JSON 解析不完整 | 逐天渲染失败 | 增加 JSON 修复逻辑 + fallback 到完整解析 |
| Prompt 压缩后质量下降 | 行程推荐不够详细 | A/B 测试对比压缩前后质量，逐步收紧 |
| Provider 并行后超频触发限流 | Amap/SerpAPI 返回 429 | 保留 `max_calls_per_request` 预算 + backoff |
| `astream_events` 事件格式与预期不符 | SSE 推送逻辑需调整 | 先用 `version='v2'` 测试事件结构 |
| 图重构期间影响现有功能 | 非 Draft 的接口（chat/edit/qa）受影响 | 重构范围限于 `travel_draft_graph.py`，不改 API 路由逻辑 |

---

### 5.4 长期演进路线

```
当前 (v1.0)              阶段一 (v1.1)              阶段二 (v1.2)           远期 (v2.0)
────────────            ────────────              ────────────           ────────────
单节点图                 4 节点图                   4+ 节点 + 并行          DAG 编排
E2E ~85s                E2E ~45s                  E2E ~22s               E2E <10s
无流式                   astream + 逐天推送         逐天渐进渲染            实时生成
串行检索                 并行检索                   向量缓存+条件跳过       预计算+增量
无缓存                   内存+Redis缓存             多级缓存               智能预取
全量Prompt               压缩Prompt+max_tokens      分步生成               小模型草案+大模型精修
手动埋点                 节点自动统计               全链路 tracing          APM 集成
```
