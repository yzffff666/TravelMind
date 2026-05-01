# Structured QP 灰度验证记录

## 1. 目标

本记录验证 `ENABLE_STRUCTURED_QP=true` 时，Structured QP 是否能接入 TravelMind 主链路，并保持现有 SSE、澄清、编辑、问答和 reset 行为稳定。

## 2. 验证环境

- 后端：独立启动 `uvicorn main:app --host 127.0.0.1 --port 8010`
- 环境变量：`ENABLE_STRUCTURED_QP=true`
- 前置代码：`structured_qp.py` 已支持 Pydantic schema 校验、低置信度回退和异常回退
- 验证日期：2026-05-01

## 3. 后端回归

命令：

```powershell
$env:ENABLE_STRUCTURED_QP='true'
py -X utf8 -m pytest tests
```

结果：

- 345 passed
- 1 个 pytest 配置 warning：`asyncio_mode` 未识别，非本轮变更引入

结论：开启 Structured QP 开关后，现有后端回归不受影响。

## 4. API Smoke

### 4.1 缺字段 create

输入：

```text
想去海边玩几天
```

结果：

- HTTP 200
- SSE 先返回 `intent_routed`
- 随后返回 `final_text`
- 进入 guided clarification，提示补充行程天数/预算等信息

结论：Structured QP 可进入 create/guided clarification 链路。

### 4.2 无 itinerary 的上下文式编辑

输入：

```text
第二天别太赶，预算还是 5000
```

结果：

- HTTP 200
- 返回 `intent_routed`
- 因当前会话没有 itinerary，系统没有进入 patch，而是转为澄清/引导文本

结论：无当前行程时不会误执行编辑 patch，行为安全。

### 4.3 Reset

输入：

```text
重置
```

结果：

- HTTP 200
- SSE 返回 `intent_routed`
- 随后返回 `reset_done`

结论：reset 仍走确定性路径，未被 Structured QP 破坏。

### 4.4 有 itinerary 的编辑

验证方式：先在 `travel_conversation_states` 中写入最小 itinerary，再携带同一 `conversation_id` 请求。

输入：

```text
把第2天下午换成东方明珠
```

结果：

- HTTP 200
- SSE 返回 `intent_routed`
- 随后返回 `edit_diff`
- 最后返回 `final_itinerary`
- diff 内容：`第2天下午：「第2天核心景点参观」→「东方明珠」`

结论：Structured QP 开启后，已有行程的 edit patch 主链路可用。

### 4.5 有 itinerary 的 QA

输入：

```text
第2天安排是什么？
```

结果：

- HTTP 200
- SSE 返回 `intent_routed`
- 随后返回 `final_text`
- 文本回答第 2 天上午、下午、晚上的安排

结论：QA 分支可用，不会误触编辑 patch。

## 5. 发现与修复

灰度前的真实中文评测发现 LLM 可能返回表层值：

- `budget="中等"`
- `pace="轻松"` 或 `pace="slow"`

这些值会导致严格 schema 校验失败。已补充归一化：

- 定性预算复用 `extract_budget()`，如“中等”归一化为 `6000.0`
- 节奏同义词归一化，如“轻松”/`slow` 归一化为 `relaxed`

对应回归测试：

- `test_structured_qp_constraints_normalize_llm_surface_values`

## 6. 当前结论

Structured QP 已通过本地灰度 smoke：

- 默认关闭时不影响现有行为。
- 开启后后端全量回归通过。
- create/guided clarification、reset、edit patch、QA 主链路均可用。
- 对上下文编辑和模糊表达的理解优于规则 baseline。

仍不建议立即生产默认开启，原因是样例规模仍有限。建议下一步：

1. 扩充到 60-100 条 query，覆盖更多城市、英文/中英混合、弱约束表达。
2. 前端 dev 环境可尝试默认开启，生产仍保持关闭。
3. 继续观察 `qp_source/confidence/fallback_reason`，确认 fallback 不会掩盖高频失败。
4. 若两轮灰度稳定，再考虑默认开启 `ENABLE_STRUCTURED_QP`。

