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
QP rule eval: 43/43 strict passed; 0/0 tracked known gaps mismatched
```

分类分布：

| 类别 | 用例数 | 通过 | 失败 |
|------|--------|------|------|
| create | 13 | 13 | 0 |
| edit | 10 | 10 | 0 |
| qa | 8 | 8 | 0 |
| qa_evidence | 4 | 4 | 0 |
| reset | 5 | 5 | 0 |
| chat | 3 | 3 | 0 |
| known_gap | 0 | 0 | 0 |

## 已知 gap

当前默认评测集没有 tracked known gap。英文编辑、英文删除、泛问题误路由已经进入 strict gate：

- `Change day 2 afternoon to an indoor activity`：判为 edit。
- `Remove day 1 evening plan`：判为 edit。
- `今天天气怎么样？`：判为 chat。
- `想去海边玩几天，轻松一点`：判为 create，由后续澄清门处理缺失字段。

如果后续发现暂不修的 badcase，可以重新以 `strict: false` 加回 known gap，但需要在 `note` 里写清楚为什么暂不进入门禁。

## 本轮顺手修复

评测集暴露了一个预算区间解析问题：

```text
北京 3天 预算4000-6000 亲子
```

修复前会被解析成 `4000`，因为通用 `预算数字` 正则先命中低位数。现在 `extract_budget()` 会优先识别区间，并使用中位数 `5000` 作为可执行预算。

本轮还补了两个入口规则：

- 英文 mutation verbs：`change / remove / replace / add ...` 会进入 edit，而不是被 `day N` 读成 QA。
- QA topic gate：问号不再自动等于 itinerary QA，只有命中行程/景点/预算/交通/证据等旅行主题时才进入 QA，普通聊天问题保留为 chat。

## 后续用法

新增 badcase 时优先追加到 `qp_rule_eval_cases.jsonl`：

- 如果是必须稳定的行为，保持默认 `strict: true`。
- 如果是已知缺口但暂不修，设置 `strict: false`，并写清楚 `note`。
- 每次改 `qp_rules.py`、`query_processor.py`、`draft_builder.py` 后，都应先跑这套离线评测，再考虑跑真实 smoke。
