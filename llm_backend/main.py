# Windows: avoid "DLL load failed" when langchain_core imports uuid_utils (C extension).
# Inject a stub that provides uuid7 via stdlib uuid so the app can start.
import sys
import os
from datetime import datetime, timezone
if sys.platform == "win32":
    import types
    import uuid
    def _uuid7_fallback():
        return uuid.uuid4()
    _compat = types.ModuleType("uuid_utils.compat")
    _compat.uuid7 = _uuid7_fallback
    sys.modules["uuid_utils.compat"] = _compat
    _pkg = types.ModuleType("uuid_utils")
    sys.modules["uuid_utils"] = _pkg


def _sanitize_broken_proxy_env() -> None:
    """Remove known-bad local proxy settings (e.g. 127.0.0.1:9)."""
    proxy_keys = (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
        "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY",
        "git_http_proxy", "git_https_proxy",
    )
    bad_tokens = ("127.0.0.1:9", "localhost:9")
    removed: list[str] = []
    for key in proxy_keys:
        value = (os.environ.get(key) or "").strip()
        if not value:
            continue
        v = value.lower()
        if any(token in v for token in bad_tokens):
            os.environ.pop(key, None)
            removed.append(key)

    if removed:
        # Use stderr-safe print here because logger is not initialized yet.
        print(f"[startup] removed broken proxy env: {', '.join(removed)}")


_sanitize_broken_proxy_env()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.core.config import settings
from app.core.logger import get_logger
from app.core.middleware import LoggingMiddleware
from app.api import api_router
from app.api.chat import router as chat_router


# logger 变量就被初始化为一个日志记录器实例。
# 之后，便可以在当前文件中直接使用 logger.info()、logger.error() 等方法来记录日志，而不需要进行其他操作。
logger = get_logger(service="main")
APP_STARTED_AT = datetime.now(timezone.utc).isoformat()

# 创建 FastAPI 应用实例
app = FastAPI(title="TravelMind API")

# 添加日志中间件， 使用 LoggingMiddleware 来统一处理日志记录，从而替代 FastAPI 的原生打印日志。
app.add_middleware(LoggingMiddleware)

# CORS设置 跨域资源共享
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Conversation-ID"],
)

# 1. 用户注册、登录路由通过 api_router 路由挂载到 /api 前缀
app.include_router(api_router, prefix="/api")
# 2. 其余历史接口（含 /api/chat、/chat-rag）按原路径直接挂载
app.include_router(chat_router)

# 健康检查路由
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "pid": os.getpid(),
        "started_at": APP_STARTED_AT,
    }

# 最后挂载静态文件，并确保使用绝对路径
STATIC_DIR = Path(__file__).parent / "static" / "dist"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
