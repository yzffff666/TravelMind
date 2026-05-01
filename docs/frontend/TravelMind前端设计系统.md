# TravelMind 前端设计系统

## 1. 产品气质

TravelMind 的前端目标是从 demo 级聊天页面升级为产品级 AI 旅行规划工作台。

统一方向：

- **AI Copilot Workspace + Travel Itinerary Cards**
- 深色优先，冷静、可信、现代。
- 旅行感来自路线、地图、星光、玻璃卡片和行程时间线，不走 OTA 信息流风格。
- 技术能力要在 UI 中可见：SSE 阶段、Provider 证据、fallback、编辑 diff、地图点位。

避免：

- 后台管理系统感。
- 每页不同色彩体系。
- 随机硬编码颜色。
- 只改颜色、不改层级和交互状态。
- 使用 emoji 作为主要图标语言。

## 2. 视觉语言

### 色彩

主色使用 noir graphite / warm champagne / soft ivory。整体应接近黑色高级旅行产品，而不是蓝紫科技面板。深色背景分为三层：

- `background`：页面底色。
- `surface`：主面板。
- `surfaceElevated`：浮层、卡片、输入区。

品牌色使用暖金属感渐变，控制饱和度；蓝色不作为主视觉，只可在地图底图或第三方内容中自然出现。

状态色必须语义化：

- `success`：成功、已完成、可用。
- `warning`：假设、fallback、低置信度。
- `danger`：错误、失败、不可恢复。
- `info`：Provider、证据、阶段提示。

### 形状与层级

- 页面主面板使用 24px 左右大圆角。
- 卡片使用 18-24px 圆角。
- 小标签使用 pill 形态。
- 玻璃卡片允许半透明和 blur，但内容可读性优先。

### 字体

- 默认字体：`Inter`, `Noto Sans SC`, system-ui。
- 正文不小于 14px，移动端正文不小于 16px。
- 标题用 600-700 字重，正文 400-500。

## 3. Design Tokens

全局 token 位于：

`frontend/DsAgentChat_web/src/styles/theme.css`

组件和页面应优先使用以下变量类别：

- `--tm-color-bg-*`
- `--tm-color-surface-*`
- `--tm-color-text-*`
- `--tm-color-primary-*`
- `--tm-color-success`
- `--tm-color-warning`
- `--tm-color-danger`
- `--tm-radius-*`
- `--tm-shadow-*`
- `--tm-space-*`
- `--tm-font-*`
- `--tm-motion-*`

规则：

- 页面组件不应新增随意 hex 色。
- 新组件要先复用 token；确实需要新 token 时，先补到 `theme.css`。
- 阴影、圆角、间距使用 token scale，不单独发明。

## 4. 基础组件标准

第一阶段优先沉淀：

- `BaseButton`：primary / secondary / ghost / danger，支持 loading、disabled、focus。
- `BaseInput`：label、hint、error、focus、disabled。
- `GlassCard`：玻璃面板容器。
- `StatusBadge`：success / warning / danger / info / neutral。
- `EmptyState`：图标区域、标题、描述、操作入口。
- `LoadingState`：短文案 + 进度/加载视觉。

后续再扩展：

- `AppShell`
- `EvidenceBadge`
- `ProviderBadge`
- `ItineraryCard`
- `DayPlanCard`
- `ChatMessage`

## 5. 页面目标

### 登录/注册

- 深色玻璃卡片。
- 明确品牌识别。
- 表单状态完整：focus、error、disabled、loading。
- 移动端不溢出。

### 主工作台

- 左侧或上方：会话与导航。
- 中间：AI 对话与规划过程。
- 右侧或下方：行程预览、证据、地图。
- SSE 阶段必须清楚可见。

### 行程结果

- Day-by-day travel cards。
- 地图和 slot 可联动。
- Evidence / Provider / validation 可见但不喧宾夺主。
- fallback 坐标或低置信度要用非打扰式 badge 告知。

## 6. 可访问性与响应式

最低要求：

- 正文对比度满足可读性。
- 键盘 Tab 可看到 focus ring。
- icon-only button 必须有 `aria-label`。
- 交互目标至少 44px。
- 移动端无横向滚动。
- 动效在 `prefers-reduced-motion` 下应减少。

## 7. 迭代顺序

推荐顺序：

1. 建立 tokens 与基础组件。
2. 落地登录/注册页。
3. 抽主布局 shell。
4. 重构主工作台视觉层级。
5. 做地图与行程 slot 双向联动。
6. 做编辑 diff、fallback、evidence 的视觉增强。
7. 最后做整体响应式与可访问性 pass。
