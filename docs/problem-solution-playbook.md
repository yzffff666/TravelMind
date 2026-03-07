# TravelMind 重点问题复盘手册（面试向，可持续更新）

> 目标：沉淀复杂问题/高价值业务问题的排查与修复过程，用于面试时讲真实工程能力。
>
> 更新规则：
> - 只收录复杂问题（架构、状态一致性、业务误判、协作流程阻断）。
> - 简单语法错误、低价值拼写问题不收录。
> - 每条必须有：现象、根因链路、方案取舍、代码落点、验证结果、可复用经验。

---

## 1. 面试讲述框架（统一模板）

每个问题建议按以下顺序讲：

1. 发生了什么（用户影响/业务影响）
2. 怎么定位的（先看日志、再缩小范围、再做假设）
3. 根因是什么（技术根因 + 机制根因）
4. 怎么修的（短期止血 + 长期可演进）
5. 怎么验证（自动化 + 场景回归）
6. 学到了什么（可迁移方法）

---

## 2. 当前收录问题（重点版）

| ID | 问题 | 类型 | 严重度 | 状态 |
|---|---|---|---|---|
| C-001 | 单次生成架构无法支撑“对话中连续改行程” | 架构/业务 | 高 | 已分阶段落地 |
| C-002 | 澄清规则误判目的地（“上海 4 天”被判缺城市） | 业务逻辑 | 高 | 已修复 |
| C-003 | 意图识别误判（`prefer` 被 `ref` 子串命中） | 算法规则 | 中高 | 已修复+测试 |
| C-004 | reset 只清前端不清后端状态，导致会话脏数据回流 | 状态一致性 | 高 | 已修复 |
| C-005 | 仓库根目录推错 + PR 无法创建（无共同历史） | 工程流程 | 中高 | 已修复 |

---

## C-001 单次生成架构无法支撑“对话中连续改行程”

### 1) 发生了什么

项目早期主链路是“输入一段需求 -> 生成一份行程草案”。
用户真实需求变成了“像 ChatGPT/Mindtrip 一样，在同一会话里持续修改”。
这导致两个直接问题：

- 修改请求没有稳定的“当前真值行程”可依赖；
- 每轮可能被当成重新生成，无法保证连续编辑体验。

### 2) 根因链路

根因不是单点 bug，而是能力缺口：

- 缺会话级行程状态真值（current itinerary / revision）；
- 缺统一意图路由（create/edit/qa/reset）；
- 缺最小编辑闭环（先路由，再 patch，再回写）。

### 3) 方案取舍

做了“保留现有主链 + 渐进增强”的取舍，而不是推翻重写：

- 保留 LangGraph 单控制面；
- 先补状态（T-M2-010）、再补路由（T-M2-011）、再补 patch（T-M2-012）。

这样做的好处是：风险可控，small PR 可 review，不阻断已有可用链路。

### 4) 代码落点（关键）

`travel.py` 中先 QP、再意图分流，create 路径保持可用，edit/qa/reset 有独立分支：

```258:275:llm_backend/app/api/travel.py
thread_id = conversation_id if conversation_id else new_uuid()
request_id = new_uuid()
qp_output = query_processor.process(query)
...
intent = qp_output["intent"]
intent_detail = qp_output["intent_detail"]
```

```290:332:llm_backend/app/api/travel.py
if intent == "reset":
    ...

if intent in {"edit", "qa"}:
    ...
```

### 5) 验证

- `create` 路径继续可生成行程（不回退）；
- `reset` 路径可真正清状态；
- `edit/qa` 可正确命中并返回对应分支（后续接 patch/qa 执行器）。

### 6) 可复用经验（面试可讲）

遇到“产品体验升级”时，不要直接重构全链路；优先识别控制面、状态真值、执行器三个层级，按层增量落地。

---

## C-002 澄清规则误判目的地（“上海 4 天”）

### 1) 发生了什么

用户输入“上海 4 天，预算 6000，情侣”时，系统仍提示“请补充目的地城市”。
这是直接影响核心转化的业务 bug（用户会觉得系统理解能力差）。

### 2) 根因链路

澄清规则库里 destination 的 pattern 没覆盖“城市 + 天数”这种高频表达。
因此约束抽取层把 destination 判为 False，误触发澄清门槛。

### 3) 解决思路

不是改 service 逻辑，而是补规则库（数据层）——保持“规则与流程解耦”。

### 4) 代码落点

在 `clarification_rules.py` 的 destination pattern 增加城市+时长直连表达：

```37:43:llm_backend/app/domain/travel/clarification_rules.py
"destination": [
    r"(去|到|前往|飞往|想去|目的地)\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z\s\-\.'/]{1,40})",
    # 支持“上海 4 天”“北京3天”这类直接城市+时长表达
    r"([\u4e00-\u9fa5A-Za-z]{2,20})\s*\d+\s*(天|日|晚|夜)",
    ...
]
```

### 5) 验证

回归用例“上海 4 天”“北京 3 天”不再误报缺目的地。

### 6) 可复用经验

规则系统上线后，优先维护“高频自然表达”的覆盖，而不是盲目加复杂模型。

---

## C-003 意图识别误判：`prefer` 误命中 `ref`

### 1) 发生了什么

测试中 `create` 场景被识别成 `qa`：
`travel to shanghai ... prefer ...` 被判成 `qa_evidence`。

### 2) 根因链路

QP 意图识别采用了简单“字符串包含”策略，英文 hint 里有 `ref`，而 `prefer` 包含子串 `ref`。

### 3) 解决思路

做了语言特征分策略：

- 中文 hint：继续用包含匹配（更符合中文短词习惯）；
- 英文 hint：改为单词边界匹配（避免子串误伤）。

### 4) 代码落点

```88:107:llm_backend/app/domain/travel/query_processor.py
def _detect_intent(self, query: str) -> tuple[IntentType, IntentDetailType]:
    lower_q = query.lower()
    if any(self._contains_hint(query, lower_q, word) for word in QP_RULES.reset_hints):
        return "reset", "reset_all"
    ...

@staticmethod
def _contains_hint(raw_query: str, lower_query: str, hint: str) -> bool:
    """Chinese hints use substring; ASCII hints use whole-word match."""
    if hint.isascii():
        return bool(re.search(rf"\b{re.escape(hint.lower())}\b", lower_query))
    return hint in raw_query
```

### 5) 验证

- 相关单测从失败恢复；
- 全量测试通过：`22 passed`。

### 6) 可复用经验

规则分类器最容易在“字符串匹配边界”出问题；先把匹配边界设计清楚，再谈词表扩充。

---

## C-004 reset 前后端状态不一致（脏状态回流）

### 1) 发生了什么

用户点“重新开始”或输入 reset 后，如果只清前端展示，不清后端会话状态，会出现：

- 新请求被旧 itinerary 污染；
- 澄清 pending 继续生效，用户体验像“没重置成功”。

### 2) 根因链路

系统状态分散在两处：

- DB 的 conversation state；
- 内存中的 clarification pending。

任何一处没清理，都会造成“重置后仍带旧上下文”。

### 3) 解决思路

把 reset 做成后端事务化动作，而不是 UI 视觉动作：

1. 清理 clarification pending；
2. 清空 conversation state 的 itinerary/revision/trip_profile；
3. 返回明确 `reset_done` 事件与文案。

### 4) 代码落点

`travel.py` reset 路由：

```290:309:llm_backend/app/api/travel.py
if intent == "reset":
    clarification_service.clear_pending(thread_id)
    await ConversationService.reset_travel_conversation_state(
        conversation_id=thread_id,
        user_id=user_id,
        last_user_query=query,
    )
    response = StreamingResponse(
        _stream_intent_text_response(..., event_name="reset_done"),
        media_type="text/event-stream",
    )
    return response
```

`ConversationService` 状态清空：

```133:182:llm_backend/app/services/conversation_service.py
async def reset_travel_conversation_state(...):
    ...
    state.current_revision_id = None
    state.trip_profile_json = None
    state.current_itinerary_json = None
    ...
```

### 5) 验证

- reset 后 `/travel/state/{conversation_id}` 返回的 current_itinerary 为 null；
- 后续新 query 按“全新会话语义”执行。

### 6) 可复用经验

重置类需求必须先定义“状态边界”，再实现 UI；否则很容易出现“看起来重置了、实际上没重置”。

---

## C-005 仓库结构与 PR 流程阻断

### 1) 发生了什么

- 首次推送把 `backend/deepseek_agent` 当根目录推到远端，缺少 `frontend`；
- 后续 `re-root` 用 orphan 分支，GitHub 提示 `There isn't anything to compare`，无法直接创建 PR。

### 2) 根因链路

- 根目录选择错误是仓库策略问题；
- orphan 分支与 `main` 无共同历史，GitHub 无法做常规 compare。

### 3) 解决思路

采用安全修复，不直接破坏 `main`：

1. 新建重根分支承载正确结构；
2. 再创建可比较分支 `re-root-pr`（挂接到 `main` 历史），恢复 PR 通路。

### 4) 结果

- 已生成可创建 PR 的分支与链接；
- 可以走标准 `Create PR -> Merge` 流程完成重根。

### 5) 可复用经验

Git 问题本质是“提交图谱问题”，不是“文件内容问题”。
在团队协作中，优先保证 `main` 安全，使用可审查分支做结构迁移。

---

## 3. 验证与质量闭环（当前）

- 本地测试：`py -3.11 -m pytest tests -v`，结果 `22 passed`。
- 本轮关键验证：
  - QP 路由准确性（含子串误判回归）
  - SSE 事件结构
  - schema 合法性

---

## 4. 后续新增记录要求（简版模板）

```md
## C-XXX 问题标题（复杂问题）

### 发生了什么（用户/业务影响）
- ...

### 根因链路（不是一句话）
- ...

### 方案取舍（短期止血 + 长期可演进）
- ...

### 代码落点（至少 1 个关键文件）
- ...

### 验证与结果
- ...

### 面试可讲亮点
- ...
```

---

## 5. 更新记录

- 2026-02-05：首版（重点问题版）初始化，收录 C-001 ~ C-005。
