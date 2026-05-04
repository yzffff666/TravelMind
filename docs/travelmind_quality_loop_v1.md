# TravelMind Agent Decision Quality Loop v1

> 从 Backfill 长尾治理到 Agent 决策质量闭环
>
> 版本：v1 | 日期：2026-05-04 | 状态：方案设计 / 下一阶段实施依据

---

## 1. 背景

TravelMind 当前已经完成了旅行规划 Agent 的主链路：

```text
QP -> Provider Recall -> Ranking -> Constraint Filter -> Evidence Builder
   -> LLM Draft -> Postprocess -> Location Backfill -> final_itinerary
```

项目已经具备以下基础能力：

| 能力 | 当前代码位置 | 状态 |
|------|--------------|------|
| Provider 多路召回 | `llm_backend/app/services/providers/orchestrator.py` | 已有并行调用、timeout、degraded、cache |
| 规则排序 | `llm_backend/app/services/ranking_scorer.py` | 已有偏好、预算、评分、热度、证据质量打分 |
| 约束过滤 | `llm_backend/app/services/constraint_filter.py` | 已有预算、节奏、距离过滤与放宽策略 |
| Evidence 映射 | `llm_backend/app/services/evidence_service.py` | 已有 evidence item、refs、coverage 计算 |
| Backfill 观测 | `llm_backend/scripts/observability_summary.py` | 已有 P50/P95、unresolved samples、fallback reasons |
| 性能/质量报告 | `docs/performance-analysis-report.md` | 已记录 unresolved 长尾治理历史 |

下一阶段的重点不是继续堆更复杂模型，而是把这些能力收束为一个可度量、可回归、可门禁、可回滚的 Agent 质量闭环。

从 Agent 系统视角看，TravelMind 当前链路已经具备一个完整的决策层：

| Agent 决策层 | TravelMind 当前对应 |
|--------------|---------------------|
| Tool / Provider Recall | Amap / SerpAPI / Mock Provider |
| Candidate Feature Extraction | `ProviderCandidate.extra` + QP constraints + backfill diagnostics |
| Candidate Ranking | `RankingScorer` |
| Constraint-aware Filtering | `ConstraintFilter` + generic activity skip + quality gate |
| Decision Feedback Loop | `observability_summary.py` + extended smoke + unresolved samples |

这里会借鉴推荐/搜索里的 candidate ranking 与 rerank 思想，但它们服务的是 Agent 的候选决策质量，而不是独立的传统推荐系统目标。

核心叙事：

```text
报告暴露长尾
-> checklist 定义不可上线底线
-> rerank 把高解析成功率、高证据质量的候选顶到前面
-> unresolved 与 P95 一起下降
```

---

## 2. 问题定义

Backfill unresolved 不是单纯的坐标回填问题，而是候选质量、可解析性、证据覆盖和约束过滤没有足够前置导致的系统性问题。

典型失败链路：

```text
Provider 召回候选质量不稳
-> Ranking 没有显式考虑可解析性与证据质量
-> LLM Draft 从弱候选或泛活动中生成 slot
-> Backfill 被迫用昂贵 provider 查询补洞
-> unresolved 仍然存在，同时拉高 P95
```

因此，Backfill 应该被重新定位为兜底路径：

> Backfill should be a fallback path, not the primary quality repair mechanism.

---

## 3. 目标

本阶段目标不是“推荐更聪明”的抽象提升，而是让 Agent 在真实业务约束下做出更稳定、更可解释、更可观测的决策。

目标指标：

| 指标 | 目标 |
|------|------|
| `unresolved_rate` | 下降或持平 |
| `evidence_coverage` | 上升或持平 |
| `generic_activity_ratio` | 下降或持平 |
| `constraint_violation_rate` | 不上升 |
| `backfill_p95` | 下降或持平 |
| `final_e2e_p95` | 不上升 |

门禁原则：

```text
Any ranking change must improve or preserve both quality metrics and latency metrics.
Reducing unresolved at the cost of itinerary feasibility is not accepted.
```

---

## 4. 技术选型取舍

### 4.1 行业路线对比

TravelMind 的核心身份是旅行规划 Agent，而不是独立推荐系统。因此这里的技术选型，应优先围绕 Agent orchestration、candidate selection、validation 和 feedback loop 来做。

| 路线 | 典型做法 | 优点 | 问题 | 当前结论 |
|------|----------|------|------|----------|
| LLM Agent + Tool Calling | 外部地图/搜索 API 召回，规则排序，LLM 组织行程 | 与对话式规划匹配，工程复杂度可控 | 需要做好 provider 质量和证据治理 | 当前主路线 |
| Agent + RAG / Rerank | 检索、重排、validation、context selection | 适合提升送入 LLM 的候选和上下文质量 | 需要评测闭环与质量门禁 | 当前最值得增强的方向 |
| 传统推荐漏斗 | I2I、双塔召回、DSSM、DIN/MMOE、LTR | 适合大规模行为数据和自建 POI 库 | 依赖用户行为、训练样本、特征平台、线上 A/B | 暂不作为主叙事 |
| Learned Ranker | embedding rerank、LTR、RM-style scoring | 可增强候选选择质量 | 当前样本、标签、延迟预算仍不足 | 作为后续增强 |

### 4.1.1 为什么借鉴排序，但不主打推荐系统

TravelMind 当前要解决的问题，不是“提升点击率”或“做个性化推荐”，而是：

```text
给 Agent 一组更可靠、更可解析、更有证据、更加符合约束的候选
-> 减少 LLM 在弱候选上的编造和补洞
-> 降低 unresolved 和长尾延迟
```

因此，这里的 ranking / rerank 更适合被定义为：

- `tool result selection`
- `candidate quality ranking`
- `constraint-aware rerank`
- `agent decision quality optimization`

也就是说，TravelMind 借鉴的是推荐/搜索的多阶段排序思想，但它们在项目里只是 Agent 决策层的一部分，而不是主身份。

### 4.2 为什么先做 Candidate Quality Rerank

当前 unresolved 的主要矛盾不是“语义相关性不够”，而是：

- POI 名称是否明确。
- Provider 是否返回地址、坐标、评分、URL 等证据字段。
- 是否命中 alias。
- 是否是泛活动或相对地点。
- 是否容易被 backfill/geocode 解析。
- 是否违反预算、距离、时间等硬约束。

这些信号都可以显式计算，不需要先把问题包装成独立推荐模型。

因此本阶段选择：

```text
显式 POI feature schema
+ rule-based hard gate
+ candidate quality soft score
+ observability guardrail
```

取舍理由：

| 决策 | 原因 |
|------|------|
| 先规则后模型 | 当前样本量不足，规则特征更可解释、更容易回归 |
| 先质量闭环后 learned ranker | 没有稳定指标前，模型收益无法判断 |
| 先 rerank 后召回升级 | Provider 已能召回候选，当前痛点更靠近候选筛选与排序 |
| 先离线/extended 回归后线上默认 | 避免少量样例优化造成真实 query 退化 |
| Backfill 只做 fallback | 避免把后处理修补变成主路径质量来源 |

### 4.3 Agent 质量优化演进路线

如果目标是往 Agent / post-training 方向靠，比较合理的路线不是“直接跳到重推荐模型”，而是分阶段增强 Agent 的候选决策质量。

建议路线：

| 阶段 | 形态 | 主要输入 | 产出 | 适用目的 |
|------|------|----------|------|----------|
| Stage A | Rule-based Candidate Quality Baseline | 显式特征 + 规则权重 | 可解释 baseline | 定义问题、建立 guardrail |
| Stage B | Semantic Rerank | query / preference embedding + candidate embedding | 语义相似度得分 | 增强候选选择质量 |
| Stage C | Rubric / Eval-driven Ranker | 结构化特征 + checklist / audit 标签 | learned score 或 reward-style score | 用评测结果反哺决策层 |
| Stage D | Post-training Integration | badcase、rubric、偏好数据 | 训练或微调信号 | 把 Agent 评测闭环接到训练优化 |

每一阶段都需要回答三个问题：

```text
比 baseline 好在哪里
-> 带来的延迟成本是多少
-> 退化时如何回滚
```

这也是为什么本方案把 rule-based baseline 放在最前面。它不是终点，而是后续 semantic rerank、rubric scoring、post-training integration 的对照组。

---

## 5. Quality Loop 设计

### Gate 1: POI Quality Report

目的：看清楚问题，而不是立刻优化。

每次 extended run 输出：

```text
run_id
destination
query_type
poi_total
poi_resolved
poi_unresolved
unresolved_rate
alias_hit_count
generic_activity_skipped_count
evidence_coverage
provider_latency_p50
provider_latency_p95
backfill_latency_p50
backfill_latency_p95
final_e2e_latency
```

当前可复用基础：

- `observability_summary.py` 已有 Provider、Backfill、QA、LLM、Cache 汇总。
- Backfill 已有 unresolved samples 表。
- `EvidenceFactory.compute_coverage()` 已有 evidence coverage 的基本计算能力。

待补齐：

- run 级 `unresolved_rate`。
- run 级 `evidence_coverage`。
- run 级 `generic_activity_ratio`。
- run 级 `constraint_violation_rate`。
- baseline vs candidate 对比报告。

### Gate 2: Itinerary Validation Checklist

目的：定义不可上线底线。

建议 checklist v1：

```text
unresolved_rate <= threshold
evidence_coverage >= threshold
duplicate_poi_count == 0
generic_activity_ratio <= threshold
day_slot_count within expected range
distance_jump_count <= threshold
budget_conflict_count == 0
open_time_conflict_count == 0
```

说明：

- TravelMind 不是纯文本 RAG，不应只看 faithfulness。
- 质量需要同时覆盖地理、时间、预算、结构合法性和证据。
- checklist 不负责生成更好内容，只负责判断是否进入 final output、fallback 或质量告警。

### Gate 3: Candidate Quality Rerank Before Backfill

目的：让高解析成功率、高证据质量、明确 POI 名称的候选更早进入 LLM Draft。

建议新增显式特征：

```text
resolvable_score
evidence_score
alias_score
provider_confidence
poi_specificity
generic_activity_penalty
distance_feasibility
budget_match
category_match
```

推荐分层：

```text
Hard Gate:
- city mismatch
- empty POI name
- generic activity
- duplicate POI
- obvious unresolvable candidate
- severe open time conflict

Soft Score:
rank_score =
  0.25 * resolvable_score
+ 0.20 * evidence_score
+ 0.20 * category_match
+ 0.10 * distance_feasibility
+ 0.10 * budget_match
+ 0.10 * provider_confidence
+ 0.05 * diversity_bonus
- 0.30 * generic_activity_penalty
```

与现有 `RankingScorer` 的关系：

| 现有维度 | 保留方式 | 新增方向 |
|----------|----------|----------|
| `preference_match` | 保留 | 可升级为 `category_match` / `interest_match` |
| `budget_fit` | 保留 | 与 checklist 的 budget conflict 区分 |
| `rating` | 保留 | 继续作为质量信号 |
| `popularity` | 保留 | 权重不宜过高，避免热门同质化 |
| `evidence_quality` | 保留 | 升级为更明确的 `evidence_score` |
| 缺失 | 新增 | `resolvable_score`、`alias_score`、`poi_specificity`、`generic_activity_penalty` |

Agent 决策视角下，这一阶段相当于：

```text
Tool / Provider Recall 已完成
-> 通过显式特征做候选质量排序
-> 再通过硬约束和质量门禁做决策前重排
```

也就是说，TravelMind 当前最需要补的是“更强的 Agent 候选质量特征层和决策前重排层”，而不是立刻引入更重的推荐系统叙事。

### Gate 4: Experiment Guardrail

每次 ranking / filtering / provider 策略修改，都必须比较 baseline 与 candidate。

准入规则：

```text
unresolved_rate 下降或持平
backfill_p95 下降或持平
evidence_coverage 上升或持平
generic_activity_ratio 下降或持平
constraint_violation_rate 不上升
final_e2e_p95 不上升
```

失败处理：

| 失败类型 | 处理 |
|----------|------|
| quality 指标退化 | 不合并或关闭 feature flag |
| latency P95 退化 | 回退到 rule baseline |
| Provider 超时上升 | 降低 provider 调用预算或调整 timeout |
| evidence coverage 降低 | 降低该 rerank 权重或加入 hard gate |
| 多样性退化 | 增加 category/day-level diversity constraint |

### 5.5 结合当前项目的落地改进

为了让这套思路不是抽象方法论，而是真正落到 TravelMind 当前代码，我们把下一步改造直接映射到已有模块。

| 当前模块 | 当前状态 | 下一步改进 | 体现的思路 |
|----------|----------|------------|------------|
| `providers/orchestrator.py` | 已有多路 provider 并行召回、timeout、degraded、cache | 补 `provider_confidence`、候选来源质量标记、destination/query 级 decision trace | 把 tool/provider 输出从“原始结果”提升为“可决策输入” |
| `ranking_scorer.py` | 已有偏好、预算、评分、热度、证据质量 | 升级为 candidate quality scorer，新增 `resolvable_score`、`alias_score`、`poi_specificity`、`generic_activity_penalty` | 把排序目标从“看起来相关”改成“对 Agent 更可用” |
| `constraint_filter.py` | 已有预算、节奏、距离规则 | 增加更明确的 reject reason、支持 decision gate 统计 | 把过滤从后处理规则变成可解释的决策门禁 |
| `evidence_service.py` | 已有 evidence mapping 与 coverage 计算 | 输出更明确的 `evidence_coverage`、slot-to-evidence 失败原因 | 把 evidence 从展示层能力前移到决策质量指标 |
| `observability_summary.py` | 已有 backfill/provider/llm 汇总与 unresolved samples | 增加 run 级 `unresolved_rate`、`generic_activity_ratio`、`constraint_violation_rate`、baseline vs candidate 报告 | 把观测从“日志汇总”升级为 Agent eval 闭环 |
| `travel_draft_graph.py` / `travel.py` | 已有 graph 与 SSE 主链路 | 增加 decision summary、quality warning、fallback used 等事件 | 让 Agent 决策质量进入主链路可见范围 |

这组改动的重点不是“再造一个模块”，而是把已经存在的召回、排序、过滤、evidence、观测串成统一的 Agent 决策层。

具体可以按下面方式理解：

```text
Provider 负责拿到候选
-> Candidate Quality Scorer 负责判断哪些候选更适合送进 LLM
-> Constraint Filter 负责阻止明显有问题的候选继续进入主链路
-> Evidence / Checklist 负责决定结果是否足够可信
-> Observability / Eval 负责把 badcase 重新变成下一轮优化输入
```

这正是我们希望体现的思路：

- 不是把 LLM 当作唯一智能来源。
- 而是把 Agent 做成一个由候选选择、约束过滤、质量门禁和 badcase 反馈共同驱动的系统。
- 后续如果进入 post-training，也不是凭空开始，而是基于这套闭环积累 rubric、badcase 和弱监督信号。

---

## 6. Feature Schema

为避免特征散落在 provider extra、prompt、backfill result 和前端字段里，建议新增统一候选特征层。

建议 schema：

```python
class POIFeature(BaseModel):
    poi_id: str
    name: str
    source: str

    # resolvability
    has_canonical_name: bool
    alias_hit: bool
    geocode_confidence: float
    provider_confidence: float

    # evidence
    evidence_count: int
    evidence_quality: float

    # travel constraints
    distance_from_prev_km: float | None
    budget_match: float
    open_time_valid: bool

    # preference
    category_match: float
    semantic_similarity: float | None

    # quality flags
    is_generic_activity: bool
    is_duplicate: bool
```

职责边界：

| 模块 | 职责 | 不应该做什么 |
|------|------|--------------|
| Provider | 召回真实候选 | 不负责最终推荐质量 |
| Feature Extractor | 标准化候选特征 | 不改变用户意图 |
| Ranker | 候选排序和降级 | 不生成新 POI |
| Checklist | 质量底线判断 | 不改写内容 |
| LLM Draft | 组织结构化行程与表达 | 不凭空创造 POI |
| Backfill | 坐标/证据兜底 | 不作为主质量修复路径 |

---

## 7. 评测集设计

不要只做一个 synthetic eval set。建议三层评测集：

| 评测集 | 来源 | 用途 |
|--------|------|------|
| Clean Synthetic Set | LLM 生成标准 query | 快速回归 |
| Messy Synthetic Set | LLM 生成口语化、缺字段、模糊 query | 鲁棒性测试 |
| Human Audit Set | 人工写/改 30-50 条真实风格 query | 防止 synthetic 过于理想 |

每条样例至少包含：

```text
destination
budget
days
interest tags
pace / constraint tags
expected quality assertions
```

不建议本阶段主打 `NDCG@K` 或 `Recall@K`，因为 ground truth 尚不稳定。可以保留这些离线指标作为辅助，但必须绑定产品指标：

```text
offline ranking metric -> unresolved_rate / evidence_coverage / constraint_violation_rate / P95
```

如果后续进入模型阶段，评测可以逐步增加：

| 阶段 | 可用指标 |
|------|----------|
| Rule baseline | unresolved rate、coverage、constraint violation、P95 |
| Semantic rerank | Recall@K、MRR、NDCG@K，加上质量/P95 guardrail |
| Eval-driven ranker | pairwise accuracy、rubric hit rate、badcase audit，加上质量/P95 guardrail |

这里的重点是：离线排序指标永远不能单独成立，必须和 itinerary 质量指标一起看。

---

## 8. Feature Flag 与回滚

所有 rerank 策略必须可关闭。

建议配置：

```env
ENABLE_POI_QUALITY_REPORT=true
ENABLE_ITINERARY_CHECKLIST=false
ENABLE_RULE_RERANK_V2=false
ENABLE_EMBEDDING_RERANK=false
```

建议 timeout / fallback：

| 策略 | 超时 | fallback |
|------|------|----------|
| rule rerank | 50ms | 原排序 |
| checklist | 50ms | log only |
| embedding rerank | 300-800ms | rule rerank |
| LLM judge rerank | 不建议在线使用 | 离线评估 |
| learning-to-rank | 50-100ms | rule rerank |

回滚原则：

```text
If any rerank strategy increases final_e2e_p95 or backfill_p95 beyond the guardrail,
disable it and fall back to the last stable rule-based ranking configuration.
```

---

## 9. 实施顺序

### Stage 1: 文档与指标口径

- 新增本文档。
- 明确 `unresolved_rate`、`evidence_coverage`、`generic_activity_ratio`、`constraint_violation_rate` 的定义。
- 在 `observability_summary.py` 中补 run 级质量指标。

### Stage 2: POIFeature

- 新增 `POIFeature` / `CandidateFeature` schema。
- 从 `ProviderCandidate`、`ScoredCandidate`、backfill diagnostics 中抽取统一特征。
- Ranker 逐步从直接吃 `ProviderCandidate.extra` 改为吃标准特征。

### Stage 3: Checklist v1

- 实现 itinerary validation checklist。
- 初期只 `log only`，不阻断 final output。
- 在 extended report 中输出 pass/fail 和失败原因。

### Stage 4: Candidate Quality Rerank v2

- 增加 `resolvable_score`、`alias_score`、`poi_specificity`、`generic_activity_penalty`。
- 权重配置化。
- 输出 per-candidate breakdown，方便 badcase 分析。

### Stage 5: Baseline vs Candidate Report

- 同一批 extended cases 跑 baseline 与 candidate。
- 输出质量 + 延迟对比表。
- 只有 guardrail 通过才允许默认开启。

### Stage 6: Semantic Rerank v1

- 在 `POIFeature` 稳定后，引入 query / preference 与 candidate 的 embedding 相似度。
- 初期只作为 candidate quality 附加分，不替代 rule baseline。
- 使用 feature flag 控制，timeout 后回退 rule rerank。
- 对比 `rule baseline` 与 `rule + semantic rerank` 的质量和 P95。

### Stage 7: Eval-driven Ranker / Rubric Scoring

满足以下条件后再考虑：

- Human Audit Set 稳定。
- badcase 已分类。
- rule rerank v2 收益进入平台期。
- semantic rerank 的 P95 可控。
- 每个离线指标都能映射到产品指标。

建议起步方案：

- pointwise：Logistic Regression / XGBoost，用显式特征预测 candidate quality。
- rubric-style：用 checklist、人工 audit、badcase 标签构造弱监督评分。
- 训练标签先从人工 audit、checklist 结果和弱标注 badcase 中构建，不急于追求大规模。

### Stage 8: Post-training Integration

只有在以下条件成立时再考虑把这一闭环接到训练或微调侧：

- 有稳定 query 分布。
- 有足够多的 badcase、rubric、偏好或弱标注数据。
- 当前 rerank 已经把显式规则收益压到平台期。
- 已经明确哪些错误适合靠训练优化，而不是靠系统规则修复。

---

## 10. 面试/简历表述

质量闭环：

```text
针对 POI backfill unresolved 导致的质量长尾与尾延迟问题，构建 POI Quality Report 与 itinerary validation checklist，量化 unresolved rate、evidence coverage、generic activity ratio、constraint violation rate 和 backfill P95，将“生成结果不稳定”转化为可观测、可回归的质量指标。
```

Agent 决策优化：

```text
设计 candidate quality rerank 策略，将可解析性、证据质量、alias 命中、Provider 置信度、兴趣匹配、距离与预算约束纳入 Agent 决策层，在 backfill 前优先提升高解析成功率与高证据质量候选，降低 unresolved 与尾延迟风险。
```

技术取舍：

```text
没有把项目包装成独立推荐系统，而是基于 Agent 场景中的 tool/provider 候选选择问题，先搭建 Provider 召回 + 显式特征排序 + checklist 门禁 + fallback 的 Agent 决策 baseline；在 baseline、评测集和 guardrail 稳定后，再逐步演进到 semantic rerank、rubric scoring 与 post-training integration。
```

---

## 11. 参考

- Google for Developers: Recommendation systems overview
  - https://developers.google.com/machine-learning/recommendation/overview/types
- Google SRE: Service Level Objectives
  - https://sre.google/sre-book/service-level-objectives/
- Ragas Metrics: component-wise evaluation ideas
  - https://docs.ragas.io/en/v0.1.21/concepts/metrics/
- TravelMind 下层能力流水线技术方案
  - `docs/下层能力流水线技术方案.md`
- TravelMind 性能优化与技术选型综合分析报告
  - `docs/performance-analysis-report.md`
