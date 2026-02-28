# TravelMind 开发任务拆解 v1.1（M1~M4，面向 small PR）

## 0. 使用说明

- 本清单用于把 `requirement.md` + `design.md` 落地为可执行开发任务。
- 目标：你每次让我完成一个任务，都能形成一个小的、可 review 的变更集（10~20 分钟可 review）。
- 保持原结构：里程碑 `M1~M4` 与任务域 `A~F` 不变。
- **任务编号说明**：同一里程碑内任务按「编号升序」排列；M1 中 008（迁移）、009（DeepAgents）为后续补充，执行顺序以第 3 节「建议执行顺序」为准。

---

## 0.1 单任务交付规范（用于 PR review）

每完成一个任务，必须输出以下内容：

1. **任务目标与范围**
2. **改动文件清单（新增/修改）**
3. **实现说明（仅本任务）**
4. **本地验证步骤（1~3 条命令 + 预期结果）**
5. **风险点（2~3 条）与回滚方式**
6. **后续建议（可选，不阻断本任务）**

补充规则：
- 涉及 DB/契约变更时，必须写明迁移回滚或兼容回退方式。
- 禁止改目录结构、禁止大重构、禁止改与本任务无关的 API。

---

## 1. 总体拆解结构

### 1.1 任务域（A~F）
- A. 契约与数据模型（schema / revision / evidence）
- B. 控制面与流程编排（LangGraph 主控 + SSE + DeepAgents/DeepResearch 可选增强）
- C. Provider 抽象与证据流水线
- D. 前端可视化与交互（行程面板、证据、Edit Day N）
- E. 工程化与质量保障（测试、指标、稳定性）
- F. 前端 UX 对齐 Agent 产品体验（交互骨架、流式体验、响应式、无障碍）

### 1.2 优先级约定
- P0：MVP 必须完成，阻断后续主链路
- P1：增强项，可在主链路稳定后并行推进

### 1.3 DeepAgents 接入约束（对齐 design）
- LangGraph 始终是唯一控制面与状态真值。
- DeepAgents 只允许作为节点执行器，不得单独维护会话状态。
- DeepAgents 节点输入输出必须回写 LangGraph state。
- 禁止引入并行控制面或旁路状态写入。
- 默认关闭：M1 不作为主链必选项，主链稳定后再评估启用。

### 1.4 DeepResearch 接入约束（对齐 design）
- DeepResearch 仅作为复杂问题增强子流，不得替代主链路。
- 必须复用同一控制面（LangGraph）与同一状态源，不新增并行控制面。
- 结果必须回写统一证据与校验字段（`evidence`、`validation.assumptions/conflicts`）。
- 受调用上限 N 与时延预算约束，超限必须降级回标准检索。
- 默认关闭：M1 不启用，M2 在触发条件满足后灰度试点。

---

## 2. 里程碑任务清单

## M1：主链路打通（首次生成结构化行程）

**M1 任务编号说明**：008（数据库迁移）、009（DeepAgents 试点）为后续补充任务，在文档中排在 002 之后；执行顺序以第 3 节「建议执行顺序」为准（008 建议在 003 前完成）。

### M1 最小回归输入（每次 M1 任务都跑）

以下 3 条固定输入建议作为 M1 每次提交的最小回归集：
- 用例 1（标准输入）：`上海 4 天，预算 6000，情侣，自由行，偏好文化+美食`
- 用例 2（缺字段追问）：`想去海边玩几天，轻松一点`
- 用例 3（预算冲突）：`北京 3 天，预算 1500，亲子，想住市中心+热门景点`

最小回归期望：
- 用例 1：可输出结构化 `final_itinerary`（或对应成功终态）。
- 用例 2：必须触发澄清，不直接输出完整行程。
- 用例 3：可输出风险/假设/降级说明，不应静默失败。

### M1-A 契约与状态地基

#### T-M1-001（P0）定义 itinerary v1 单一契约
- 优先级：P0
- 依赖：无
- 主要输出：
  - `itinerary v1` 统一 schema（含 `schema_version`）
  - 字段必填等级（P0/P1/P2）与降级规则的文档化
- 验收标准：
  - 返回结构包含 `schema_version`
  - 前后端字段定义一致，无分叉
- 建议改动范围：
  - `llm_backend/app/schemas/`
  - `frontend/DsAgentChat_web/src/`（如需共享 schema）

#### T-M1-002（P0）新增 revision 基础模型
- 优先级：P0
- 依赖：T-M1-001
- 主要输出：
  - itinerary/revision 最小数据模型
  - `revision_id` 与 `base_revision_id` 语义定义
- 验收标准：
  - 首次生成可分配 `revision_id`
  - 首版 `base_revision_id` 规则明确并可解释
- 建议改动范围：
  - `llm_backend/app/models/`
  - `llm_backend/app/services/`

#### T-M1-008（P0）数据库迁移/版本管理（新增地基）
- 优先级：P0
- 依赖：T-M1-002
- 主要输出：
  - itinerary/revision/diff/evidence 表的 migration
  - 初始化策略、回滚策略
  - 本地可重复拉起验证说明
- 验收标准：
  - 空库可初始化成功
  - 迁移可回滚到上一版本
  - 同步骤重复执行结果稳定
- 建议改动范围：
  - `llm_backend/` 下迁移目录（以仓库现状为准）
  - `llm_backend/app/core/database.py`（如需最小适配）
  - `README.md` 或 `docs/`（迁移说明）

### M1-B 控制面与首次生成流程

#### T-M1-003（P0）路由语义迁移（电商 -> 旅行）
- 优先级：P0
- 依赖：无
- 主要输出：
  - 路由分类与 guardrails 迁移到旅行语义
  - 缺失约束优先追问
- 验收标准：
  - 典型旅行 query 不误路由到电商语义
  - 缺失关键约束时进入追问分支
- 建议改动范围：
  - `llm_backend/app/lg_agent/`
  - `llm_backend/app/prompts/`（如存在）

#### T-M1-004a（P0）澄清阶段闭环（缺字段追问 -> resume）
- 优先级：P0
- 依赖：T-M1-003
- 主要输出：
  - 澄清问题输出与 resume 闭环
  - 硬门槛/软门槛识别（硬门槛缺失追问，软门槛缺失仅记录 assumptions）
  - 澄清阶段事件输出（stage_start/stage_progress）
- 验收标准：
  - 缺字段时稳定追问
  - 硬门槛补齐后进入规划主链，软门槛缺失不阻断
  - 用户补充后能继续同一流程
- 建议改动范围：
  - `llm_backend/main.py`
  - `llm_backend/app/services/travel_clarification_service.py`
  - `llm_backend/app/lg_agent/lg_builder.py`

#### T-M1-004b（P0）草案结构化输出（不接 provider）
- 优先级：P0
- 依赖：T-M1-001, T-M1-004a
- 主要输出：
  - days/slots 最小结构草案输出
- 验收标准：
  - 可返回 `itinerary v1` 最小结构（含 days/slots）
  - 不依赖 provider 也可跑通
- 建议改动范围：
  - `llm_backend/app/lg_agent/`
  - `llm_backend/app/schemas/`

#### T-M1-004c（P0）Schema 校验与自动修复；P0 缺失走 final_text
- 优先级：P0
- 依赖：T-M1-004b
- 主要输出：
  - Pydantic/Schema 校验
  - 轻量自动修复
  - P0 缺失时只输出 `final_text`
- 验收标准：
  - P0 缺失时不输出 `final_itinerary`
  - 输出可读澄清文本而非硬错误
- 建议改动范围：
  - `llm_backend/app/schemas/`
  - `llm_backend/app/lg_agent/`
  - `llm_backend/main.py`

#### T-M1-004d（P0）final_itinerary + explanation 双输出
- 优先级：P0
- 依赖：T-M1-004c
- 主要输出：
  - 成功态输出：`final_itinerary` + `explanation`
  - 证据可为空或占位
- 验收标准：
  - 成功分支输出结构与说明文本
  - 前端可消费并展示
- 建议改动范围：
  - `llm_backend/main.py`
  - `llm_backend/app/lg_agent/`
  - `frontend/DsAgentChat_web/src/services/`

#### T-M1-009（P1）DeepAgents 节点执行器试点（澄清环节）
- 优先级：P1
- 依赖：T-M1-004a, T-M1-004d
- 主要输出：
  - 在澄清环节引入 DeepAgents 节点执行器（试点）
  - 保持 LangGraph state 为唯一状态源
- 启用触发条件（满足任意 2 条）：
  - 澄清轮次常态 >3 轮；
  - 长对话中上下文丢失/漂移明显；
  - 单节点提示词维护复杂度显著上升。
- 验收标准：
  - 多轮澄清可持续推进，不丢上下文
  - 无并行控制面，状态流转可追踪
- 建议改动范围：
  - `llm_backend/app/lg_agent/`
  - `llm_backend/main.py`
  - `docs/`（接入约束说明）

### M1-C SSE 与前端最小承接

#### T-M1-005（P0）统一 SSE 事件 envelope
- 优先级：P0
- 依赖：T-M1-004d
- 主要输出：
  - 事件类型统一：`stage_start/stage_progress/tool_result/final_itinerary/final_text/error`
  - 统一 envelope（request/conversation/revision/timestamp/payload）
- 验收标准：
  - 新前端可按事件消费
  - 旧前端可降级消费文本
- 建议改动范围：
  - `llm_backend/main.py`
  - `frontend/DsAgentChat_web/src/services/api.ts`

#### T-M1-006（P0）TravelPlanner 主页面骨架
- 优先级：P0
- 依赖：T-M1-005
- 主要输出：
  - 旅行规划主页面
  - 阶段状态 + 终态渲染
- 验收标准：
  - 可完成“输入 -> 输出草案”
  - 页面可见 `schema_version/revision_id`
- 建议改动范围：
  - `frontend/DsAgentChat_web/src/views/`
  - `frontend/DsAgentChat_web/src/stores/`

#### T-M1-007（P1）旧页面兼容路由
- 优先级：P1
- 依赖：T-M1-006
- 主要输出：
  - 兼容旧页面入口，不阻断新入口
- 验收标准：
  - 旧路由可访问
  - 新入口作为默认主流程
- 建议改动范围：
  - `frontend/DsAgentChat_web/src/router/index.ts`

M1 分层约束补充（不新增重任务，仅明确边界）：
- M1 允许实现 **QP 最小职责**（意图识别 + 关键约束抽取），实现方式可为规则、LLM 抽取或混合。
- M1 不要求完整召回/排序系统；召回/排序在 M2 baseline 再落地。
- M1 所有能力仍由 LangGraph 单一控制面编排，不新增并行状态源。

---

## M2：对话共创 + 证据驱动（主线里程碑）

M2 主线优先级说明（对齐 Mindtrip 风格目标）：
- 优先打通“同会话连续编辑”闭环：`会话态 -> 意图路由 -> patch -> diff SSE -> 前端同屏联动`；
- Provider/证据增强在不阻塞主线的前提下并行推进；
- 多智能体增强保持 P1，可插拔、可开关，不抢主流程。

**M2 任务编号与段落顺序**：任务编号按数字顺序为 T-M2-000a～000e → 001～002c → 003～006 → 007～008 → 009a～009d → 010～014 → 015～017；段落按模块分组（M2-0 → M2-D 对话共创 → M2-E 前端 UX → M2-A Provider → M2-C 检索增强 → M2-B Evidence），执行顺序以第 3 节「建议执行顺序」为准。

### M2-0 下层搜索能力 baseline（QP → Recall → Ranking → Rule Filter → Evidence Builder）

#### T-M2-000a（P0）QP baseline（意图识别 + 约束抽取）
- 优先级：P0
- 依赖：T-M1-004d
- 主要输出：
  - QP 统一输出结构（可对接 trip_profile 语义）
  - 意图识别（首次生成 / Edit Day N / 证据问答 / 局部问答）
  - 关键约束抽取（城市、天数、预算、偏好、节奏、同伴类型）
- 验收标准：
  - QP 输出可驱动后续召回输入
  - 缺失硬约束可回到澄清分支
- 建议改动范围：
  - `llm_backend/app/domain/travel/`
  - `llm_backend/app/services/`
  - `llm_backend/app/lg_agent/`

#### T-M2-000b（P0）候选召回 baseline（关键词/标签/多路聚合）
- 优先级：P0
- 依赖：T-M2-000a, T-M2-001
- 主要输出：
  - 基于 QP 输出的多路召回聚合（先规则与配置驱动）
  - 候选池标准字段（候选ID/来源/基础评分/标签）
- 验收标准：
  - 候选召回可复现且可配置
  - provider 不可用时有 mock/fixture 降级路径
- 建议改动范围：
  - `llm_backend/app/services/providers/`
  - `llm_backend/app/services/`
  - `llm_backend/tests/fixtures/`

#### T-M2-000c（P0）可解释排序 baseline（规则打分）
- 优先级：P0
- 依赖：T-M2-000b
- 主要输出：
  - 排序打分函数（偏好/预算/通勤/评分/证据质量）
  - 分项得分与总分（可解释）
- 验收标准：
  - 排序结果稳定、可解释
  - 可通过配置开关切换排序策略
- 建议改动范围：
  - `llm_backend/app/domain/travel/`
  - `llm_backend/app/services/`
  - `llm_backend/app/lg_agent/`

#### T-M2-000d（P0）规则过滤 baseline（硬约束过滤）
- 优先级：P0
- 依赖：T-M2-000c
- 主要输出：
  - 预算/通勤/冲突/闭馆等硬约束过滤
  - 过滤原因标准化输出（供 assumptions/risk 使用）
- 验收标准：
  - 违反硬约束候选不会进入最终草案
  - 过滤原因可在输出中追踪
- 建议改动范围：
  - `llm_backend/app/domain/travel/`
  - `llm_backend/app/services/`
  - `llm_backend/app/lg_agent/`

#### T-M2-000e（P0）证据组织与映射 baseline（Evidence Builder）
- 优先级：P0
- 依赖：T-M2-000d, T-M2-003
- 主要输出：
  - 候选 -> `evidence + evidence_refs` 映射流水线
  - `provider/url/fetched_at/attribution` 组织与降级策略
- 验收标准：
  - 最终行程可定位 evidence refs
  - evidence 字段缺失时可降级且可解释
- 建议改动范围：
  - `llm_backend/app/services/`
  - `llm_backend/app/schemas/`
  - `llm_backend/app/lg_agent/`

### M2-D 对话式行程共创（P0，贴近 GPT/Mindtrip 体验）

#### T-M2-010（P0）会话级 itinerary 状态持久化
- 优先级：P0
- 依赖：T-M1-002, T-M1-005
- 主要输出：
  - 在 conversation 维度维护 `current_itinerary/current_revision_id/trip_profile`
  - 每轮请求可读取并更新同一会话状态
- 验收标准：
  - 同一 `conversation_id` 连续多轮可基于上轮结果继续编辑
  - 非同会话状态隔离正确
- 建议改动范围：
  - `llm_backend/app/services/conversation_service.py`
  - `llm_backend/app/services/revision_service.py`
  - `llm_backend/main.py`

#### T-M2-011（P0）对话意图路由（create/edit/qa/reset）
- 优先级：P0
- 依赖：T-M2-010, T-M2-000a
- 主要输出：
  - 对每轮用户输入执行意图识别并路由
  - 将 `edit` 路径接入现有 revision 流程
- 验收标准：
  - 同一对话中可混合“提问 + 修改 + 重置”
  - 路由可解释（至少可输出命中意图）
- 建议改动范围：
  - `llm_backend/app/lg_agent/`
  - `llm_backend/app/domain/travel/`
  - `llm_backend/main.py`

#### T-M2-012（P0）Patch 编辑引擎（最小操作集）
- 优先级：P0
- 依赖：T-M2-011
- 主要输出：
  - 自然语言编辑 -> 结构化操作：`replace_slot / delete_slot / insert_slot / update_constraint`
  - apply_patch 后触发校验与降级说明
- 验收标准：
  - 不依赖整单重算即可完成常见编辑
  - 输出包含 `change_summary + changed_days`
- 建议改动范围：
  - `llm_backend/app/domain/travel/`
  - `llm_backend/app/services/revision_service.py`
  - `llm_backend/app/lg_agent/`

#### T-M2-013（P0）SSE 扩展：编辑结果与差异事件
- 优先级：P0
- 依赖：T-M2-012
- 主要输出：
  - 在现有 envelope 下补充编辑相关 payload（可复用 `final_itinerary/stage_progress`）
  - 前端可实时看到“本轮改动摘要”
- 验收标准：
  - 新前端可显示本轮 diff，旧前端不崩溃
  - 事件序列可复现（request_id/revision_id 连贯）
- 建议改动范围：
  - `llm_backend/main.py`
  - `frontend/DsAgentChat_web/src/services/api.ts`

#### T-M2-014（P0）前端对话+行程同屏联动
- 优先级：P0
- 依赖：T-M2-013, T-M1-006
- 主要输出：
  - 在同一页面支持连续对话输入与当前行程展示
  - 支持“继续修改”而非仅“重新生成”
- 验收标准：
  - 用户可在单会话内完成“生成 -> 多轮修改 -> 确认”
  - 每轮修改后行程区与摘要区同步更新
- 建议改动范围：
  - `frontend/DsAgentChat_web/src/views/TravelPlanner.vue`
  - `frontend/DsAgentChat_web/src/stores/`
  - `frontend/DsAgentChat_web/src/components/`

### M2-E 前端 UX 对齐 Agent 产品体验

#### T-M2-015（P0）前端交互骨架与双栏联动
- 优先级：P0
- 依赖：T-M2-014
- 主要输出：
  - 页面重构为 Chat Panel + Itinerary Panel 双栏布局（响应式降级到 Tab 切换）
  - InputBar 常驻底部，支持多行输入 + 发送状态 + 快捷操作（重置/滚动定位）
  - PhaseIndicator 组件：根据 SSE 事件展示当前阶段（澄清中/规划中/校验中/完成）
  - EmptyState 组件：首次进入 & 重置后引导态
  - ErrorState 组件：网络异常/超时/降级场景展示 + 重试入口
  - DiffCard 组件：每轮编辑后在 Chat 区展示变更摘要（changed_days + budget_diff）
- 验收标准：
  - 桌面端可同屏查看对话与行程，窄屏可 Tab 切换
  - SSE 各阶段事件均有对应 UI 反馈，无"黑屏等待"
  - Empty/Error 状态覆盖完整，用户始终有可操作入口
- 建议改动范围：
  - `frontend/DsAgentChat_web/src/views/TravelPlanner.vue`
  - `frontend/DsAgentChat_web/src/components/chat/`（新建）
  - `frontend/DsAgentChat_web/src/components/itinerary/`（新建）

#### T-M2-016（P1）流式体验与视觉精修
- 优先级：P1
- 依赖：T-M2-015, T-M2-003
- 主要输出：
  - 骨架屏 / shimmer 占位（行程区规划中状态）
  - 流式逐字渲染（Chat 区系统回复）
  - slot 渐显动画（行程区证据逐步填充）
  - EvidenceDrawer 组件：证据抽屉/面板（来源、评分、归因、跳转）
  - BudgetBar 组件：预算可视化条（分类占比、超限警告）
  - RiskBadge 组件：风险标签（高/中/低，hover 展开详情）
  - 动效统一（150~300ms ease 过渡，避免装饰性动效）
- 验收标准：
  - 规划等待期有明确视觉反馈（非空白），用户感知延迟降低
  - 证据可展开查看、来源可跳转
  - 动效不干扰信息获取，可关闭或降级
- 建议改动范围：
  - `frontend/DsAgentChat_web/src/components/`
  - `frontend/DsAgentChat_web/src/views/TravelPlanner.vue`
  - `frontend/DsAgentChat_web/src/assets/`（设计 Token / CSS Variables）

#### T-M2-017（P1）响应式适配与无障碍基础
- 优先级：P1
- 依赖：T-M2-015
- 主要输出：
  - 三档响应式断点（桌面双栏 / 平板 Tab / 移动单栏）
  - 关键交互路径键盘可操作（Tab/Enter/Esc）
  - 对比度 >= 4.5:1（AA 级），焦点环可见
- 验收标准：
  - 主流宽度下布局无溢出/重叠
  - 键盘可完成"输入 -> 发送 -> 查看结果"核心路径
- 建议改动范围：
  - `frontend/DsAgentChat_web/src/views/TravelPlanner.vue`
  - `frontend/DsAgentChat_web/src/assets/`

### M2-A Provider 抽象与调用策略

#### T-M2-001（P0）定义 Provider 抽象接口
- 优先级：P0
- 依赖：T-M1-004d
- 主要输出：
  - Search/Map/Weather/Review 抽象接口
  - 标准错误语义与降级标识
- 验收标准：
  - 上层流程不依赖厂商字段
  - 可替换 provider 实现
- 建议改动范围：
  - `llm_backend/app/services/`（provider 抽象目录）
  - `llm_backend/app/lg_agent/`

#### T-M2-002a（P0）策略配置与调用上限 N（可配置）
- 优先级：P0
- 依赖：T-M2-001
- 主要输出：
  - 调用顺序配置
  - 调用上限 N 的配置化
- 验收标准：
  - 单请求调用次数受限
  - 超限后流程可继续（不崩溃）
- 建议改动范围：
  - `llm_backend/app/core/config.py`
  - `llm_backend/app/services/`

#### T-M2-002b（P0）降级路径与 assumptions/risk 提升规则
- 优先级：P0
- 依赖：T-M2-002a
- 主要输出：
  - 降级路径落地
  - `assumptions` 与风险提升规则
- 验收标准：
  - provider 不可用时仍可给出可解释结果
  - 输出中可见降级痕迹
- 建议改动范围：
  - `llm_backend/app/lg_agent/`
  - `llm_backend/app/services/`

#### T-M2-002c（P1）条件并行（可选增强）
- 优先级：P1
- 依赖：T-M2-002b
- 主要输出：
  - 条件并行拉取策略
- 验收标准：
  - 延迟改善且不破坏降级路径
  - 不突破调用上限 N
- 建议改动范围：
  - `llm_backend/app/services/`
  - `llm_backend/app/lg_agent/`

#### T-M2-007（P1）DeepAgents 多轮对话策略增强
- 优先级：P1
- 依赖：T-M1-009, T-M2-002b
- 主要输出：
  - 多轮任务拆解与上下文压缩策略（由 DeepAgents 节点执行）
  - 澄清轮次上限、超限收敛策略
- 验收标准：
  - 长对话轮次下回复稳定性提升
  - 超轮次时可收敛到可执行问题清单或建议方案
- 建议改动范围：
  - `llm_backend/app/lg_agent/`
  - `llm_backend/app/services/`
  - `docs/`（多轮策略规则）

#### T-M2-008（P1）DeepResearch 深度研究子流试点（复杂问题）
- 优先级：P1
- 依赖：T-M2-001, T-M2-002b, T-M2-003, T-M2-004
- 主要输出：
  - DeepResearch 可选子流（复杂问题触发）
  - 多来源核验与冲突对比结果回写 `evidence/validation`
  - 超时/超限回退标准检索的降级路径
- 启用触发条件（满足任意 2 条）：
  - 证据覆盖率持续低于目标阈值；
  - 高时效/高不确定问题比例上升；
  - 标准检索结果冲突率上升或可解释性不足。
- 验收标准：
  - 复杂问题可输出更完整证据链与冲突说明
  - 调用上限 N 内运行，超限可稳定降级
  - 不引入新控制面，不旁路状态写入
- 建议改动范围：
  - `llm_backend/app/lg_agent/`
  - `llm_backend/app/services/providers/`
  - `llm_backend/app/services/`
  - `llm_backend/tests/fixtures/`（深度研究样例）

### M2-C 检索增强（可选/P1，不阻塞主链路）

#### T-M2-009a（P1）BERT/小模型意图识别策略（可插拔）
- 优先级：P1
- 依赖：T-M2-000a
- 主要输出：
  - 与 baseline QP 并存的意图分类策略
  - A/B 或开关对比能力
- 验收标准：
  - 可开关，不影响 baseline 回退
  - 线上/离线指标可对比

#### T-M2-009b（P1）向量召回策略（可插拔）
- 优先级：P1
- 依赖：T-M2-000b
- 主要输出：
  - 向量召回通道（可与关键词召回融合）
- 验收标准：
  - 可开关，不影响关键词召回路径
  - 失败可降级回 baseline

#### T-M2-009c（P1）Learning-to-Rank（LTR）试点
- 优先级：P1
- 依赖：T-M2-000c
- 主要输出：
  - LTR 排序策略及与规则排序的对比
- 验收标准：
  - 可开关，不影响规则排序回退
  - 指标口径稳定

#### T-M2-009d（P1）DeepSearch 检索增强（网页）
- 优先级：P1
- 依赖：T-M2-008
- 主要输出：
  - 深度网页研究的可选召回通道
- 验收标准：
  - 有调用上限与超时回退
  - 不引入第二控制面或并行状态源

### M2-B Evidence 流水线

交付分层说明（避免口径歧义）：
- P0 先完成后端证据可用与可统计（`T-M2-003`、`T-M2-004`）。
- P1 再完成前端证据可视化增强（`T-M2-005`）。

#### T-M2-003（P0）Evidence v1 结构与归因落地
- 优先级：P0
- 依赖：T-M2-001
- 主要输出：
  - Evidence 字段标准化
  - 来源归因与跳转规则
- 验收标准：
  - 主推荐项可映射证据
  - 归因信息可见
- 建议改动范围：
  - `llm_backend/app/schemas/`
  - `llm_backend/app/services/`
  - `frontend/DsAgentChat_web/src/components/`

#### T-M2-004（P0）证据覆盖率统计口径实现
- 优先级：P0
- 依赖：T-M2-003
- 主要输出：
  - 覆盖率统计（按 slot 主 POI）
  - 只统计成功 `final_itinerary`
- 验收标准：
  - 可输出覆盖率结果，口径稳定
- 建议改动范围：
  - `llm_backend/app/services/`
  - `llm_backend/app/lg_agent/`

#### T-M2-005（P1）前端证据面板与关联展示
- 优先级：P1
- 依赖：T-M2-003, T-M1-006
- 主要输出：
  - 证据卡片与推荐项关联视图
- 验收标准：
  - 用户可快速定位证据来源
- 建议改动范围：
  - `frontend/DsAgentChat_web/src/views/`
  - `frontend/DsAgentChat_web/src/components/`

#### T-M2-006（P0）Provider mock/fixture（离线可跑主链路）
- 优先级：P0
- 依赖：T-M2-001
- 主要输出：
  - 固定样例输入输出 fixture
  - 离线 mock provider 路径
  - 回归数据
- 验收标准：
  - 断网可跑通主链路
  - 回归输出结构可复现
- 建议改动范围：
  - `llm_backend/app/services/providers/`
  - `llm_backend/tests/fixtures/` 或 `docs/fixtures/`

---

## M3：Edit Day N + 修订链

### M3-A 后端修订能力

#### T-M3-001a（P0）Edit Day N 最小 API + 只改 Day N（不扩散）
- 优先级：P0
- 依赖：T-M1-002, T-M1-004d
- 主要输出：
  - Edit Day N 最小请求/响应接口
  - 仅 Day N 重写能力
- 验收标准：
  - 产生新 revision
  - 非目标天默认不变
- 建议改动范围：
  - `llm_backend/main.py`
  - `llm_backend/app/services/`

#### T-M3-001b（P0）影响域扩散规则落地（dayN±邻接段）
- 优先级：P0
- 依赖：T-M3-001a
- 主要输出：
  - DayN 邻接扩散规则
- 验收标准：
  - 扩散行为可解释、可追踪
- 建议改动范围：
  - `llm_backend/app/services/revision_service.py`（建议）
  - `llm_backend/app/lg_agent/`

#### T-M3-001c（P1）稳定性保护（锁定日不可改、超阈值建议全局重规划）
- 优先级：P1
- 依赖：T-M3-001b
- 主要输出：
  - 锁定日保护
  - 超阈值建议逻辑
- 验收标准：
  - 锁定日不被误改
  - 超阈值返回建议而非静默应用
- 建议改动范围：
  - `llm_backend/app/services/`
  - `frontend/DsAgentChat_web/src/views/`

#### T-M3-002（P0）diff 与 change_summary
- 优先级：P0
- 依赖：T-M3-001b
- 主要输出：
  - day/slot 级差异
  - 预算差额与风险变化摘要
- 验收标准：
  - 返回 `changed_days` 与变更摘要完整
- 建议改动范围：
  - `llm_backend/app/services/revision_service.py`
  - `llm_backend/app/schemas/`

#### T-M3-003（P0）请求幂等与回滚能力
- 优先级：P0
- 依赖：T-M3-001a
- 主要输出：
  - `request_id` 幂等
  - 回滚到指定 revision 能力
- 验收标准：
  - 重试不重复创建 revision
  - 回滚行为有记录
- 建议改动范围：
  - `llm_backend/main.py`
  - `llm_backend/app/services/revision_service.py`

### M3-B 前端编辑交互

#### T-M3-004（P0）changed_days 阈值确认交互
- 优先级：P0
- 依赖：T-M3-002
- 主要输出：
  - 阈值分支交互（自动/确认/建议）
  - 影响摘要弹窗
- 验收标准：
  - 用户可理解并确认影响范围
- 建议改动范围：
  - `frontend/DsAgentChat_web/src/views/TravelPlanner.vue`
  - `frontend/DsAgentChat_web/src/components/`

#### T-M3-005（P1）修订链可视化
- 优先级：P1
- 依赖：T-M3-003, T-M3-004
- 主要输出：
  - revision 列表、差异对比、回滚入口
- 验收标准：
  - 可回看并恢复历史版本
- 建议改动范围：
  - `frontend/DsAgentChat_web/src/views/`
  - `frontend/DsAgentChat_web/src/stores/`

---

## M4：工程化与稳定性

### M4-A 导出与保存

#### T-M4-001（P0）JSON 导出最小集
- 优先级：P0
- 依赖：T-M1-001, T-M3-002
- 主要输出：
  - JSON 导出（schema/revision/trip_profile/days/budget/evidence/change_summary）
- 验收标准：
  - 导出结构可再次校验解析
- 建议改动范围：
  - `llm_backend/main.py`
  - `llm_backend/app/services/`

#### T-M4-002（P0）Markdown 导出最小集
- 优先级：P0
- 依赖：T-M4-001
- 主要输出：
  - 可读导出（总览、按天、预算风险、变更、证据链接）
- 验收标准：
  - 业务评审可直接使用
- 建议改动范围：
  - `llm_backend/app/services/`
  - `frontend/DsAgentChat_web/src/views/`

### M4-B 测试与回归

#### T-M4-003a（P0）后端契约测试（itinerary schema + SSE envelope）
- 优先级：P0
- 依赖：M1/M2 核心任务完成
- 主要输出：
  - 后端 schema 契约测试
  - SSE envelope 契约测试
- 验收标准：
  - 核心后端契约测试通过
- 建议改动范围：
  - `llm_backend/tests/`
  - `llm_backend/app/schemas/`（必要修正）

#### T-M4-003b（P0）前端 SSE 解析测试（事件兼容）
- 优先级：P0
- 依赖：T-M4-003a
- 主要输出：
  - 新事件流解析测试
  - 旧文本兼容测试
- 验收标准：
  - 新旧协议都可稳定消费
- 建议改动范围：
  - `frontend/DsAgentChat_web/src/services/`
  - `frontend/DsAgentChat_web/tests/`

#### T-M4-003c（P1）端到端回归样例（5 条典型输入快照）
- 优先级：P1
- 依赖：T-M4-003a, T-M4-003b, T-M2-006
- 主要输出：
  - 5 条典型输入的回归快照样例
- 验收标准：
  - 样例可重复通过，输出结构稳定
- 建议改动范围：
  - `tests/e2e/`（以仓库现状为准）
  - `docs/fixtures/`

### M4-C 指标与发布准备

#### T-M4-004（P1）核心指标看板
- 优先级：P1
- 依赖：T-M4-003a
- 主要输出：
  - JSON valid rate、约束满足率、工具成功率/降级可用率、Edit Day N 稳定性、P50/P95 延迟/成本
- 验收标准：
  - 指标可按版本追踪
- 建议改动范围：
  - `llm_backend/app/services/`
  - `docs/`

#### T-M4-005（P1）发布前稳定性清单
- 优先级：P1
- 依赖：T-M4-003a
- 主要输出：
  - 限流/重试/回滚清单
  - 发布演练记录
  - 最小 CI 基线（至少 lint + test）与失败回退策略说明
- 验收标准：
  - 发布演练通过
  - CI 基线可执行且对关键分支生效
- 建议改动范围：
  - `docs/`
  - `README.md`
  - `.github/workflows/`（如仓库使用 GitHub Actions）

---

## 3. 建议执行顺序（small PR 优先）

1. `T-M1-001` -> `T-M1-002` -> `T-M1-008` -> `T-M1-003` -> `T-M1-004a`
2. `T-M1-004b` -> `T-M1-004c` -> `T-M1-004d`（首次落库前必须完成 `T-M1-008`）
3. `T-M1-005` -> `T-M1-006`（`T-M1-007` 可后置）
4. `T-M2-000a` -> `T-M2-010` -> `T-M2-011` -> `T-M2-012` -> `T-M2-013` -> `T-M2-014`（先打通对话式连续编辑）
5. `T-M2-015`（前端交互骨架，紧跟 T-M2-014 后落地）-> `T-M2-016`、`T-M2-017`（P1 体验精修，可与 Provider/Evidence 并行）
6. `T-M2-001` -> `T-M2-002a` -> `T-M2-002b` -> `T-M2-006` -> `T-M2-003` -> `T-M2-000e` -> `T-M2-004`（`T-M2-005` 后置）
7. 触发条件满足后：`T-M1-009` -> `T-M2-007` -> `T-M2-008`（`T-M2-002c` 可后置）
8. `T-M3-001a` -> `T-M3-001b` -> `T-M3-002` -> `T-M3-003` -> `T-M3-004`（`T-M3-001c`、`T-M3-005` 后置）
9. `T-M4-001` -> `T-M4-002` -> `T-M4-003a` -> `T-M4-003b`（`T-M4-003c` 后置）

---

## 4. 完成定义（DoD）

单任务完成需满足：
- 对齐需求：可映射 `requirement.md`
- 对齐设计：可映射 `design.md`
- 达成任务验收标准
- 输出“单任务交付规范”6 个小标题

