# Structured QP 真实中文评测记录

## 1. 目标

本记录用于评估 `Structured QP` 是否比现有规则 baseline 更适合承担 TravelMind 的自然语言理解入口，重点验证：

- `create / edit / qa / reset / chat` 意图识别是否稳定。
- 目的地、天数、预算、节奏等约束抽取是否更自然。
- `confidence`、schema 校验和 fallback 机制是否能支撑后续灰度开启。

## 2. 评测配置

- 规则 baseline：`TravelQueryProcessor.process()`
- Structured QP：`LLMStructuredQPStrategy.classify()`
- 模型：当前 `.env` 配置的 `DEEPSEEK_MODEL`
- 样例数：30 条真实中文 query
- 上下文：编辑/问答样例提供 `has_itinerary=true` 和最小 `trip_profile`
- 置信度阈值：`0.65`

## 3. 样例覆盖

样例覆盖以下类型：

- 首次规划：明确目的地、天数、预算、偏好。
- 缺字段规划：如“想去海边玩几天”。
- 多轮编辑：如“第二天别太赶，预算还是 5000”。
- 整体风格调整：如“整体节奏改轻松一点”。
- 行程问答：某天安排、门票、交通、适老性。
- 证据问答：为什么推荐、来源链接。
- 重置：中文 reset 与英文 restart。
- 闲聊：非旅行或泛助手问题。

## 4. 结果摘要

| 指标 | 规则 baseline | Structured QP |
|------|---------------|---------------|
| Intent 准确率 | 26/30（86.67%） | 30/30（100%） |
| Structured QP 低置信度 | 不适用 | 0/30 |
| Structured QP 调用失败 | 不适用 | 0/30 |
| 主要短板 | 上下文编辑误判为 chat；部分目的地/预算浅层抽取不准 | 首轮发现定性预算/节奏值需要 schema 归一化，已修复 |

## 5. 规则 baseline 主要误判

本轮规则 baseline 主要误判集中在上下文编辑类表达：

- “把那个海边项目换掉，安排轻松一点” → 被识别为 `chat`。
- “住宿预算降一点，景点不要变” → 被识别为 `chat`。
- “预算提高到 15000，酒店住好一点” → 被识别为 `chat`。
- “不要寺庙，多安排亲子互动” → 被识别为 `create`。

此外，规则抽取仍有一些浅层实体问题：

- “东京五天自由行...” 未稳定抽出目的地。
- “伦敦 6 天，预算 2 万...” 中规则 budget 抽取为 `2.0`。
- “从酒店到第一个景点多久” 被抽出目的地噪声。
- “第1天和第2天会不会太赶？” 被抽出目的地噪声。

## 6. Structured QP 发现与修复

首轮 Structured QP 调用中，模型意图判断基本正确，但出现 3 条 schema 校验失败：

- `budget` 返回 “中等”。
- `pace` 返回 “轻松”。
- `pace` 返回 “slow”。

已在 `StructuredQPConstraints` 中补充归一化：

- 定性预算复用 `extract_budget()`，如 “中等” → `6000.0`。
- 节奏同义词归一化，如 “轻松” / `slow` → `relaxed`。

修复后复测结果：

- Intent 准确率：30/30。
- 低置信度：0/30。
- 调用失败：0/30。

## 7. 结论

Structured QP 对 TravelMind 当前最薄弱的“自然语言入口理解”有明显收益，尤其是多轮上下文编辑和模糊表达。

但本轮样例量仍较小，不建议立即默认开启。建议下一步：

1. 扩充到 60-100 条 query，加入更多城市、英文/中英混合、弱约束和反事实表达。
2. 在本地或灰度环境打开 `ENABLE_STRUCTURED_QP=true` 做 E2E smoke。
3. 观察 `qp_source/confidence/fallback_reason`，确认 fallback 不会掩盖高频失败。
4. 若连续两轮评测稳定，再考虑灰度默认开启。

