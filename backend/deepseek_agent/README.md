# TravelMind - 基于大语言模型构建的旅行规划智能体

一个基于 FastAPI 和 Vue 3 构建的前后端分离旅行规划智能体项目，支持多轮对话生成、编辑与重置行程。系统面向自由行场景，围绕“可对话、可解释、可编辑”的目标，逐步落地 Agent + 检索增强 + 证据归因的工程化链路。

## 功能特性

### 1. 对话式行程规划能力
- **支持多轮对话生成/优化行程（create/edit/qa/reset）**
- **支持结构化行程输出（itinerary v1：days + slots）**
- **支持缺失关键约束时澄清追问（目的地/天数/预算）**

### 2. 流式与状态能力
- **支持 SSE 流式事件输出（阶段状态、终态结果、错误兜底）**
- **支持会话级 itinerary 状态持久化（conversation state）**
- **支持 reset 会话重置并清理澄清中间态**

### 3. 可扩展能力链路（M2 基线）
- QP baseline（意图识别 + 约束抽取 + recall_query）
- Provider 抽象（Search/Map/Weather/Review）
- 后续扩展：Recall / Ranking / Rule Filter / Evidence Builder

## 快速启动

### 1. 安装依赖

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `env.example` 文件到 `llm_backend/.env` 文件中，并根据实际情况修改配置：

```env
# LLM 服务配置
CHAT_SERVICE=OLLAMA  # 或 DEEPSEEK
REASON_SERVICE=OLLAMA  # 或 DEEPSEEK

# Ollama 配置
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=deepseek-coder:6.7b
OLLAMA_REASON_MODEL=deepseek-coder:6.7b

# DeepSeek 配置（如果使用）
DEEPSEEK_API_KEY=your-api-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

### 3. 安装 MySQL 并在 `.env` 中配置数据库连接

用于用户、会话、消息、行程状态等持久化。

### 4. 启动服务

```bash
# 进入后端目录
cd llm_backend

# 启动服务（默认端口 9000）
python run.py

# 如果需要修改 IP 和端口，编辑 run.py 中的配置：
uvicorn.run(
    "main:app",
    host="0.0.0.0",  # 修改监听地址
    port=8000,       # 修改端口号
    access_log=False,
    log_level="error",
    reload=True
)
```

服务启动后可以访问：
- API 文档：http://localhost:8000/docs
- 前端界面：http://localhost:8000

## 技术栈

- 后端：
  - FastAPI
  - SQLAlchemy
  - MySQL
  - LangGraph
  - Ollama / DeepSeek

- 前端：
  - Vue 3
  - Element Plus
  - TypeScript

## 注意事项

1. 生产环境部署时：
   - 修改 `.env` 中的 `SECRET_KEY`
   - 配置正确的 CORS 设置
   - 使用 HTTPS
   - 关闭 `reload=True`

2. 开发环境：
   - 可以启用 `reload=True` 实现热重载
   - 可以设置 `log_level="debug"` 查看更多日志

## 旅行数据与证据服务说明

本项目当前聚焦“旅行建议 + 可解释证据”，不包含交易闭环（下单/支付）。

### 核心数据对象

1. **Itinerary v1** - 结构化行程
   - itinerary_id / revision_id / schema_version
   - trip_profile（目的地、约束）
   - days（按天）/ slots（按时段活动）
   - budget_summary / validation（assumptions、risks）

2. **Conversation State** - 会话行程状态
   - conversation_id
   - current_revision_id
   - current_itinerary_json
   - trip_profile_json
   - last_user_query

3. **Evidence（规划中的证据对象）**
   - provider / title / url / fetched_at / attribution

### 主要流程

1. 用户输入旅行需求（目的地/天数/预算/偏好）
2. QP 识别意图与约束
3. 若缺失硬约束，进入澄清分支
4. 生成结构化行程并写回会话状态
5. 用户可继续 edit/qa/reset 进行多轮共创

## 项目文档索引

- 产品需求：`requirement.md`
- 工程设计：`design.md`
- 任务拆解：`task.md`
- 学习路线：`study.md`
- 变更记录：`CHANGELOG.md`

## License

MIT
