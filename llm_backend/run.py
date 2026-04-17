import uvicorn
from app.core.logger import get_logger
import os
import sys
from pathlib import Path

logger = get_logger(service="server")

def start_server():
    # 确保工作目录正确
    os.chdir(Path(__file__).parent)
    
    logger.info("Starting server...")
    logger.info(f"Working directory: {os.getcwd()}")
    
    # Windows 下默认关闭 reload，避免多进程命名管道权限错误（WinError 5）。
    enable_reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"
    if sys.platform == "win32":
        enable_reload = False

    uvicorn.run(
        "main:app",        # 使用模块路径
        host="0.0.0.0",
        port=8000,
        access_log=False,
        log_level="error",
        reload=enable_reload
    )

if __name__ == "__main__":
    start_server() 
