# TravelMind E2E Smoke 验证记录

## 1. 目标

本记录用于沉淀 TravelMind 主链路的最小端到端验证，覆盖登录、行程生成、SSE 渐进渲染、地图展示和编辑 diff。

## 2. 启动方式

后端：

```bash
cd llm_backend
.\.venv\Scripts\python.exe run.py
```

前端：

```bash
cd frontend/DsAgentChat_web
npm run dev -- --host 127.0.0.1
```

常用验证命令：

```bash
cd frontend/DsAgentChat_web
npm run type-check
npm run build

cd ../../llm_backend
py -X utf8 -m pytest tests/test_patch_engine.py tests/test_travel_m2_011.py -q
```

## 3. Smoke 样例

### 3.1 国内生成

输入：

```text
帮我规划 3 天成都亲子游，预算中等，节奏轻松
```

期望：

- 登录后进入 Planner 工作台。
- 输入提交后显示生成中状态，SSE 阶段持续更新。
- 最终出现 3 天成都行程。
- `TripOverview` 展示目的地、天数、人群标签。
- `BudgetCard` 展示约 6000 元预算与分类条。
- `ItineraryTimeline` 展示逐天 slot、地图点位、费用和 evidence 状态。
- `MapPanel` 展示地图引擎、点位数量、Day tabs；无坐标时显示非阻塞提示。

### 3.2 编辑行程

输入：

```text
把第二天下午改成更轻松的室内活动
```

期望：

- 请求返回 200。
- 展示编辑 diff。
- 第 2 天下午 slot 被更新。
- 如果新活动是泛化描述，没有可靠坐标，地图提示为非阻塞 fallback。

## 4. 最近一次验证结果

结果：通过。

- 登录、生成、SSE 渐进渲染、行程卡片、预算卡、地图状态和编辑 diff 均正常。
- `/api/travel/query` 生成与编辑请求返回 200。
- 前端无 4xx/5xx 关键网络错误。
- AMap SDK 出现 Canvas2D `willReadFrequently` 性能提示，属于第三方 SDK 非阻塞 warning。

## 5. 已修复问题

- 登录页不再把登录行为绑定到注册协议勾选。
- 登录只校验邮箱格式与密码非空；注册仍要求协议、密码强度和确认密码。
- 注册密码允许特殊字符，避免真实密码与前端校验不一致。
- 移动端 Planner 面板补充滚动与最小高度，降低窄屏内容挤压风险。

## 6. 后续回归清单

每次修改 Planner、登录、地图或 travel 规则后，至少执行：

- `npm run type-check`
- `npm run build`
- `py -X utf8 -m pytest tests/test_patch_engine.py tests/test_travel_m2_011.py -q`
- 手动验证一次国内生成和一次编辑请求。

如果涉及地图 Provider、坐标回填或海外 POI，再补海外样例：

```text
帮我规划 4 天普吉岛轻松游，预算中等，偏好海岛和美食
```
