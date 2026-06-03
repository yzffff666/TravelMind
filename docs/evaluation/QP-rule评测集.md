# QP Rule 评测集

## 目标

这套评测用于验证 `TravelQueryProcessor` 的确定性 rule baseline，不调用 LLM、不启动后端、不消耗 Provider/API 额度。

它的作用是把入口路由从“凭感觉改规则”变成“改完能量化回归”：

- 创建行程、编辑行程、行程 QA、证据 QA、reset、chat 是否能被正确分类。
- 目的地、天数、预算、人群、节奏等核心约束是否能被稳定抽取。
- 英文编辑、泛问题误路由等暂未修的点先作为 known gap 跟踪，不阻塞主门禁。

## 文件位置

| 用途 | 路径 |
|------|------|
| 评测数据集 | `llm_backend/evaluation/qp_rule_eval_cases.jsonl` |
| 离线评测脚本 | `llm_backend/scripts/evaluate_qp_rules.py` |
| 回归测试 | `llm_backend/tests/test_qp_rule_evaluation.py` |

## 运行方式

```powershell
cd llm_backend
py -X utf8 -m scripts.evaluate_qp_rules `
  --output reports/qp-rule-eval/latest.json `
  --markdown-output reports/qp-rule-eval/latest.md
```

如果严格门禁用例失败，脚本默认返回非 0，适合作为本地回归或 CI gate。

## 当前基线

最近一次本地结果：

```text
QP rule eval: 39/39 strict passed; 3/4 tracked known gaps mismatched
```

分类分布：

| 类别 | 用例数 | 通过 | 失败 |
|------|--------|------|------|
| create | 12 | 12 | 0 |
| edit | 8 | 8 | 0 |
| qa | 8 | 8 | 0 |
| qa_evidence | 4 | 4 | 0 |
| reset | 5 | 5 | 0 |
| chat | 2 | 2 | 0 |
| known_gap | 4 | 1 | 3 |

## 已知 gap

当前跟踪但不阻塞门禁的问题：

- 英文编辑：`Change day 2 afternoon to an indoor activity` 当前会被 rule baseline 判成 QA，目标应是 edit。
- 英文删除：`Remove day 1 evening plan` 当前会被判成 QA，目标应是 edit。
- 泛问题：`今天天气怎么样？` 当前会被问号规则判成 QA，目标应是普通 chat。

这些 gap 正好对应下一阶段 rule-based 优化优先级：先补英文 mutation hints，再收紧 QA 问句触发条件，避免非旅行问题误入 itinerary QA。

## 本轮顺手修复

评测集暴露了一个预算区间解析问题：

```text
北京 3天 预算4000-6000 亲子
```

修复前会被解析成 `4000`，因为通用 `预算数字` 正则先命中低位数。现在 `extract_budget()` 会优先识别区间，并使用中位数 `5000` 作为可执行预算。

## 后续用法

新增 badcase 时优先追加到 `qp_rule_eval_cases.jsonl`：

- 如果是必须稳定的行为，保持默认 `strict: true`。
- 如果是已知缺口但暂不修，设置 `strict: false`，并写清楚 `note`。
- 每次改 `qp_rules.py`、`query_processor.py`、`draft_builder.py` 后，都应先跑这套离线评测，再考虑跑真实 smoke。
