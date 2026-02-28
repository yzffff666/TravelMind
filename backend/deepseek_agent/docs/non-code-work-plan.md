# TravelMind 个人项目非代码工作清单（对齐 M1~M4）

## 1. 文档目的

本清单用于补齐「除纯代码开发之外」的关键工作，确保项目能从“能跑”走到“可演示、可验证、可上线”。

适用范围：当前个人项目（非大厂团队），强调小步快跑、低成本、可复用。

---

## 2. 个人项目优先原则

1. 先做最小闭环，再做精细化优化。  
2. 先保证可验证，再追求高指标。  
3. 能复用公开数据与模板，不重复造轮子。  
4. 每项非代码工作都要绑定一个可交付物（文档/表格/样例集）。  
5. 与 `task.md` 节奏对齐：M2 主线优先，不让增强项阻塞主链路。

---

## 3. 非代码工作总览（按主题）

## 3.1 数据与样例资产
- 旅行请求样例池（标准输入、缺字段、冲突约束、连续编辑、多轮问答）。
- Evidence 样例池（有来源/无来源/冲突来源/时效过期）。
- 回归 fixtures（与 `T-M2-006` 对齐，离线可复现）。

交付物建议：
- `docs/fixtures/regression-cases.md`
- `docs/fixtures/evidence-cases.md`
- `docs/fixtures/mock-provider-data.json`

## 3.2 评测与验收口径
- 功能口径：是否完成 create/edit/qa/reset 主流程。
- 质量口径：约束满足率、证据覆盖率、非目标天稳定率、对话连续编辑稳定性。
- 体验口径：空态/异常态可达、SSE 阶段反馈完整、差异回显可理解。

交付物建议：
- `docs/evaluation/eval-plan.md`
- `docs/evaluation/eval-scorecard-template.md`

## 3.3 Prompt 与策略资产
- 系统提示词版本管理（澄清、路由、patch 生成、降级说明）。
- Prompt 变更日志（改了什么、为什么改、影响哪些用例）。
- 规则配置资产（排序权重、过滤阈值、降级策略）。

交付物建议：
- `docs/prompt/prompt-changelog.md`
- `docs/prompt/prompt-regression-cases.md`
- `docs/config/strategy-baseline.md`

## 3.4 Provider 账号与配额治理
- Provider 清单（Search/Map/Weather/Review）与账号状态。
- 配额预算（每日上限、单请求上限 N、超限降级策略）。
- 监控台账（失败率、超时率、费用波动）。

交付物建议：
- `docs/ops/provider-account-matrix.md`
- `docs/ops/provider-quota-budget.md`

## 3.5 演示与对外材料
- Demo 脚本（3~5 分钟版本，覆盖生成+连续编辑+证据查看）。
- Demo 数据包（固定对话脚本 + 固定截图/GIF）。
- 对外说明页（项目价值、边界、路线图、已知限制）。

交付物建议：
- `docs/demo/demo-script.md`
- `docs/demo/demo-cases.md`
- `docs/demo/known-limitations.md`

## 3.6 测试与发布准备
- 测试计划（冒烟、回归、异常、降级、兼容）。
- 发布清单（配置检查、密钥检查、回滚预案）。
- 运行手册（本地/测试环境启动步骤、常见故障处理）。

交付物建议：
- `docs/release/test-plan.md`
- `docs/release/release-checklist.md`
- `docs/release/runbook.md`

---

## 4. 按里程碑对齐的非代码任务

## M1：主链路打通阶段（当前基础）

目标：让“输入 -> 澄清 -> 结构化输出”可复现、可演示。

必须完成（P0）：
- 建立最小回归样例集（至少 3 条，已与 `task.md` M1 对齐）。
- 建立 M1 验收记录模板（每次提交记录通过/失败原因）。
- 建立 Prompt v1 台账（澄清提示词、输出约束提示词）。
- 完成本地环境说明（Python 版本、依赖、启动命令、常见报错）。

建议完成（P1）：
- 录制一次 2 分钟 M1 演示（用于后续对比）。

---

## M2：对话共创 + 证据驱动（当前主线）

目标：支撑“同会话连续编辑”与证据链路可验证。

必须完成（P0）：
- 多轮对话评测样例集（至少 20 条）：
  - create 5 条、edit 8 条、qa 4 条、reset 3 条。
- Patch 回归集（针对 `replace/delete/insert/update_constraint`）。
- Evidence 口径台账：覆盖率计算样本、统计周期、异常样本说明。
- Provider 配额预算表：
  - 每日预算、单请求上限 N、触发降级阈值。
- 演示脚本 v2（5 分钟）：
  - 首次生成 -> 连续修改 -> 差异回显 -> 证据查看。
- UX 验收清单（对齐 `T-M2-015~017`）：
  - 双栏联动、空态/异常态、阶段反馈、DiffCard。

建议完成（P1）：
- Prompt A/B 记录：至少做 1 轮澄清策略对比（轮次/命中率）。
- 维护“失败对话库”（错误路由、误澄清、冲突修订）用于复盘。

---

## M3：修订链与稳定性阶段

目标：让局部编辑行为“可控、可解释、可回滚”。

必须完成（P0）：
- 变更影响评估模板（changed_days、预算变化、风险变化）。
- 回滚演练记录（至少 3 次成功回滚用例）。
- 非目标天稳定性月报（样本数、均值、异常案例）。
- 用户操作手册（如何编辑 Day N、如何回滚、如何理解 diff）。

建议完成（P1）：
- 版本时间线演示材料（截图 + 变更故事线）。

---

## M4：工程化与上线准备阶段

目标：形成可持续迭代与可对外展示的最小发布能力。

必须完成（P0）：
- 发布前检查清单（配置、密钥、数据库迁移、回滚方案）。
- 冒烟测试脚本（核心链路 10 分钟内跑完）。
- 上线后观测表（错误率、延迟、费用、降级触发次数）。
- 对外 README 更新（项目能力、边界、运行方式、已知问题）。

建议完成（P1）：
- 周报模板（本周变更、指标变化、下周计划）。
- 版本公告模板（新增能力/破坏性变更/迁移提示）。

---

## 5. 你现在就可以做的 7 项非代码动作（按优先级）

1. 建立 `M2 多轮评测样例集`（20 条起步）。  
2. 建立 `Provider 配额预算表`（先按日预算 + 上限 N）。  
3. 建立 `Prompt 变更日志`（从今天起每次改动都记录）。  
4. 建立 `Demo 脚本 v2`（固定 5 分钟流程）。  
5. 建立 `UX 验收清单`（对齐双栏联动与 SSE 反馈）。  
6. 建立 `失败对话库`（每次 bug 追加一条复盘记录）。  
7. 建立 `发布检查清单` 草稿（提前做，不等 M4）。

---

## 6. 推荐目录结构（非代码资产）

```text
docs/
  fixtures/
    regression-cases.md
    evidence-cases.md
    mock-provider-data.json
  evaluation/
    eval-plan.md
    eval-scorecard-template.md
  prompt/
    prompt-changelog.md
    prompt-regression-cases.md
  ops/
    provider-account-matrix.md
    provider-quota-budget.md
  demo/
    demo-script.md
    demo-cases.md
    known-limitations.md
  release/
    test-plan.md
    release-checklist.md
    runbook.md
```

---

## 7. 完成判定（非代码）

满足以下 5 条，即可认为“非代码工作到位”：
- 有固定评测样例集，且每次迭代可重复执行；
- 有 Provider 配额与成本边界，超限有降级说明；
- 有 Prompt 版本台账，能追溯策略变化；
- 有可复用 Demo 脚本，可稳定演示核心价值；
- 有上线/回滚/故障处理文档，不依赖临场记忆。

