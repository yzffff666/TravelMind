# Provider 观测字段清单

## 1. 目标

本清单定义 TravelMind 在真实 Provider 调用、坐标回填与地图渲染链路中需要记录的最小观测字段。目标是让每一次质量问题都能回答三个问题：

1. 慢在哪里。
2. 降级在哪里。
3. 点位为什么不准。

## 2. 事件粒度

建议先按三类事件记录：

- `provider_call`：一次 Search / Map Provider 调用。
- `location_backfill`：一次 slot 坐标回填尝试。
- `itinerary_quality_summary`：一次行程生成或编辑完成后的质量摘要。

个人项目阶段可以先写入结构化日志；等稳定后再接入指标平台或文件化报表。

## 3. Provider 调用字段

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `event_type` | string | `provider_call` | 固定事件类型 |
| `request_id` | string | `req_xxx` | 单次请求 ID |
| `conversation_id` | string | `conv_xxx` | 会话 ID |
| `provider_name` | string | `amap` / `serpapi` / `mock` | Provider 名称 |
| `provider_kind` | string | `search` / `map` | Provider 类型 |
| `destination` | string | `东京` | 目标目的地 |
| `query` | string | `东京 美食 景点` | 实际查询词 |
| `timeout_ms` | number | `3000` | 本次调用超时预算 |
| `elapsed_ms` | number | `812` | 实际耗时 |
| `status` | string | `success` / `timeout` / `empty` / `error` | 调用结果 |
| `result_count` | number | `12` | 返回候选数量 |
| `error_type` | string | `TimeoutError` | 异常类型，无异常为空 |
| `degraded` | boolean | `false` | 是否进入降级 |

## 4. 坐标回填字段

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `event_type` | string | `location_backfill` | 固定事件类型 |
| `request_id` | string | `req_xxx` | 单次请求 ID |
| `itinerary_id` | string | `iti_xxx` | 行程 ID |
| `revision_id` | string | `rev_xxx` | 修订 ID |
| `day_index` | number | `2` | 第几天 |
| `slot_label` | string | `下午` | slot 标签 |
| `activity` | string | `东京晴空塔看夜景` | 用户可见活动名 |
| `destination` | string | `东京` | 目标目的地 |
| `candidate_title` | string | `东京晴空塔` | 匹配到的候选名 |
| `lat` | number | `35.7101` | 最终纬度 |
| `lng` | number | `139.8107` | 最终经度 |
| `source` | string | `provider` / `unresolved` / `skipped` | 坐标来源或处理结果 |
| `confidence` | string | `high` / `medium` / `low` | 粗略置信度 |
| `elapsed_ms` | number | `430` | 回填耗时 |
| `fallback_reason` | string | `provider_empty` | fallback 原因 |
| `bbox_valid` | boolean | `true` | 是否落在目标城市/国家范围 |
| `variants_tried` | array | `["普吉老城", "Old Phuket Town"]` | 本次尝试过的查询变体 |
| `provider_status_counts` | object | `{"success": 2, "empty": 1}` | 回填内部 provider 调用状态分布 |
| `best_candidate_title` | string | `Old Phuket Town` | 未成功时也记录最接近候选，便于判断别名/打分问题 |
| `best_match_score` | number | `0.6667` | 最佳候选文本匹配分 |
| `candidate_count` | number | `9` | provider 返回并进入评估的候选数 |
| `rejected_bbox_count` | number | `2` | 因目的地 bbox 不符被拒的候选数 |
| `rejected_score_count` | number | `3` | 因文本匹配分不足被拒的候选数 |
| `rejected_missing_coord_count` | number | `0` | 因缺坐标被拒的候选数 |
| `cache_hit_count` | number | `1` | 回填缓存命中次数 |
| `cache_negative_hit_count` | number | `1` | 负缓存命中次数 |
| `variant_limit_reached` | boolean | `false` | 查询变体是否被数量上限截断 |

## 5. 行程质量摘要字段

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `event_type` | string | `itinerary_quality_summary` | 固定事件类型 |
| `request_id` | string | `req_xxx` | 单次请求 ID |
| `conversation_id` | string | `conv_xxx` | 会话 ID |
| `intent` | string | `create` / `edit` / `qa` / `reset` | 本轮意图 |
| `destination` | string | `普吉岛` | 目的地 |
| `days_count` | number | `5` | 天数 |
| `total_slots` | number | `15` | slot 总数 |
| `slots_with_location` | number | `13` | 有坐标 slot 数 |
| `fallback_slots` | number | `2` | fallback slot 数 |
| `bbox_invalid_slots` | number | `0` | 明显越界 slot 数 |
| `coverage_score` | number | `0.86` | 当前 coverage |
| `provider_elapsed_ms` | number | `2800` | Provider 阶段总耗时 |
| `backfill_elapsed_ms` | number | `900` | 坐标回填总耗时 |
| `backfill_attempted` | number | `7` | 本轮实际进入 provider backfill 的 slot 数 |
| `backfill_filled` | number | `4` | 本轮成功回填的 slot 数 |
| `backfill_skipped` | number | `2` | 本轮因泛活动/相对地点跳过的 slot 数 |
| `backfill_unresolved` | number | `3` | 本轮仍未解析的 slot 数 |
| `degraded` | boolean | `false` | 是否整体降级 |

## 6. 日志示例

```json
{
  "event_type": "location_backfill",
  "request_id": "req_20260429_001",
  "itinerary_id": "iti_001",
  "revision_id": "rev_002",
  "day_index": 2,
  "slot_label": "晚上",
  "activity": "东京晴空塔看夜景",
  "destination": "东京",
  "candidate_title": "东京晴空塔",
  "lat": 35.7101,
  "lng": 139.8107,
  "source": "provider",
  "confidence": "high",
  "elapsed_ms": 430,
  "fallback_reason": "",
  "bbox_valid": true,
  "variants_tried": ["东京晴空塔"],
  "provider_status_counts": {"success": 1},
  "best_candidate_title": "东京晴空塔",
  "best_match_score": 1.0,
  "candidate_count": 1,
  "rejected_bbox_count": 0,
  "rejected_score_count": 0,
  "rejected_missing_coord_count": 0,
  "cache_hit_count": 0,
  "cache_negative_hit_count": 0,
  "variant_limit_reached": false
}
```

## 7. 最小落地建议

第一阶段不需要上复杂监控系统，建议先做三件事：

1. 在 Provider 调用处打结构化日志，至少记录 `provider_name/status/elapsed_ms/result_count`。
2. 在坐标回填处记录 `source/fallback_reason/bbox_valid/elapsed_ms`，并保留 `best_candidate_title/best_match_score/provider_status_counts` 方便 unresolved 样例诊断。
3. 在 final itinerary 输出前记录一次质量摘要，至少包含 `backfill_attempted/backfill_filled/backfill_skipped/backfill_unresolved`，便于人工评测时对照。

## 8. 后续扩展

当样例集跑稳定后，可以把这些字段升级为自动化指标：

- Provider P50/P95。
- fallback 触发率。
- unresolved samples：按 `elapsed_ms` 排序展示 `place/reason/provider_status/best_candidate/best_score`。
- 海外 bbox invalid 比例。
- changed slot 坐标更新成功率。
- evidence/source 缺失率。

这些指标直接服务于后续优化优先级判断：先修高频失败，再修低频体验问题。
