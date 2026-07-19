# Hybrid Structured QP v1

## 1. Problem

TravelMind 的后半段已经能对候选 POI 做地理校验、排序与约束规划；但如果入口把用户问题理解错，后续的确定性规划只会在错误约束上优化。

典型高风险边界：

```text
第三天下午去哪里              -> QA，不能修改 itinerary
第二天改成室内了吗？           -> QA，不能修改 itinerary
住宿预算降一点，景点不要变     -> 有历史状态的上下文编辑
Paris 3 days budget 5000 food -> 英文城市抽取不足的 create
```

## 2. Decision

不将所有输入直接交给 DeepSeek，也不在缺少标注数据时提前训练意图小模型。

采用三段式 Hybrid QP：

```text
Rule baseline
  -> 明确、低风险请求：直接执行
  -> 上下文编辑 / 英文城市缺失：Structured QP
  -> 低置信、异常或安全校验失败：保留 Rule 结果并安全降级
```

`reset`、明确 QA、完整 create、明确日程 slot 修改保持 Rule fast path。Structured QP 只输出 schema，不调用 Provider，也不直接修改 itinerary。

## 3. Rollout Modes

| Mode | 行为 | 使用场景 |
| --- | --- | --- |
| `off` | 完全使用 Rule baseline | 默认与紧急回滚 |
| `shadow` | 调用 Structured QP 并记录结果，但用户行为保留 Rule | 灰度对比 |
| `selective` | 仅在规则难例采用通过安全检查的 Structured QP 结果 | 受控启用 |

配置位于 `.env`：

```env
STRUCTURED_QP_MODE=off  # off / shadow / selective
STRUCTURED_QP_TIMEOUT_SECONDS=4.0
STRUCTURED_QP_CONFIDENCE_THRESHOLD=0.65
```

旧的 `ENABLE_STRUCTURED_QP=true` 保留兼容，等价于 `selective`；新配置优先使用 `STRUCTURED_QP_MODE`。

## 4. Safety Policy

Structured QP 的 `confidence` 只是一个特征，不是唯一决策依据。模型结果必须同时通过：

```text
- reset 只能由确定性 Rule 触发
- 只读 QA 不能被重分类为 create/edit
- edit 必须有明确 mutation 语义
- 无 itinerary 的 edit 不得执行状态修改
- 有 itinerary 的编辑请求不能被模型重分类为全新 create
- target_day 只能出现在 edit
```

失败时输出 `qp_source=fallback` 与 `safety_level=blocked/caution`，最终采用 Rule 结果。API 结构化日志新增：

```text
structured_qp_mode
route_reason
safety_level
shadow_intent
fallback_reason
```

## 5. Evaluation

评测分为两层：

| Gate | 内容 | 是否消耗模型额度 |
| --- | --- | --- |
| `qp_eval` | 96 条 Rule regression | 否 |
| `hybrid_qp_eval` | 30 条 Hybrid holdout，含 17 条安全关键样例 | 否，使用 fixture Structured QP |
| shadow replay | 真实 DeepSeek 调用，与 Rule 输出对比 | 是，手动灰度 |

离线通过标准：

```text
30/30 holdout passed
17/17 critical safety passed
router P95 < 50ms
```

当前 v1 离线结果：`30/30`，critical safety `17/17`，router P95 `0.338ms`。

真实 DeepSeek shadow replay 使用独立的 12 条小集，避免纳入 CI 消耗额度：

```bash
cd llm_backend
./.venv/bin/python -m scripts.structured_qp_shadow_eval \
  --output reports/structured-qp-shadow/manual-run.json
```

2026-07-18 完成两轮回放：两轮均 `12/12` 通过，均为 7 次模型调用，模型 P95 分别为 `2427ms`、`2622ms`。两轮没有 QA -> Edit 状态污染，也没有超时或 schema 回退。

## 6. Technical Trade-off

DeepSeek Structured QP 适合当前阶段，因为它能结合 itinerary 上下文完成意图与 slot 联合理解，且已有 JSON schema、超时和 fallback。代价是调用延迟与成本，所以只处理困难输入。

小模型更适合后续承担低延迟路由器，而不是立即替代整个 QP：

```text
Rule fast path -> small intent/risk model -> DeepSeek fallback -> clarification
```

当前 96 条规则回归与 30 条灰度样例足以做评测，但不足以训练可靠的小模型。先积累人工审核的真实 badcase，再决定是否训练。

## 7. Go / No-Go

离线门禁通过后仍保持 `off`。只有满足以下条件才进入 `shadow`，再评估 `selective`：

```text
两轮 shadow replay 无 QA -> Edit 状态污染
模型异常/超时全部安全回退
Structured QP P95 <= 4s
复杂上下文样例的 intent 与约束抽取不低于 Rule baseline
```

**v1 decision：Go for controlled `selective`; No-Go for unconditional default enable。**

上述两轮 shadow 已满足进入受控 `selective` 的门槛。默认仍是 `off`，因为当前真实模型样本规模只覆盖 12 条高风险输入；下一阶段应通过日志积累更多人工审核 badcase，再决定是否扩大默认流量。

## 8. Structured Edit Execution

对于通过安全校验且具有明确 day/slot/constraint 的 edit，系统会将结构化字段转换为受限 `REPLAN_DAY` 命令，再走候选召回、排序和约束规划。模型不能把任意 POI 或活动文本直接写入 itinerary；候选不足、Provider 异常或规划不可行时不会产生新 revision。

详细设计、验收和技术取舍见 [Structured Edit-to-Plan v1](structured_edit_to_plan_v1.md)。
