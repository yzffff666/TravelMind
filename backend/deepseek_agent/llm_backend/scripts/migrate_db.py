import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

# Add project root to PYTHONPATH.
# 添加项目根目录到 PYTHONPATH。
ROOT_DIR = Path(__file__).parent.parent
sys.path.append(str(ROOT_DIR))

# 导入数据库引擎和基类。
from app.core.database import engine, Base  
# 导入模型。
from app.models import (  
    Itinerary,
    ItineraryRevision,
    ItineraryDiff,
    ItineraryEvidence,
    TravelConversationState,
)
# 导入日志记录器。
from app.core.logger import get_logger 

logger = get_logger(service="migrate_db")
# 定义迁移版本。
MIGRATION_VERSION = "20260219_001_itinerary_revision_evidence"

# 创建迁移表的 SQL 语句。
CREATE_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(128) PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

# 检查版本号的 SQL 语句。
CHECK_VERSION_SQL = "SELECT version FROM schema_migrations WHERE version = :version"
INSERT_VERSION_SQL = "INSERT INTO schema_migrations (version) VALUES (:version)"
DELETE_VERSION_SQL = "DELETE FROM schema_migrations WHERE version = :version"


# 确保迁移表存在。
async def _ensure_migration_table(conn):
    # 创建迁移表。
    await conn.execute(text(CREATE_MIGRATION_TABLE_SQL))


# 检查迁移状态。
async def status():
    try:
        async with engine.begin() as conn:
            # 确保迁移表存在。
            await _ensure_migration_table(conn)
            # 查询版本号。
            result = await conn.execute(text("SELECT version, applied_at FROM schema_migrations ORDER BY applied_at DESC"))
            # 获取版本号。
            rows = result.fetchall()
            # 如果版本号不存在，则返回。
            if not rows:
                logger.info("No applied migrations found.")
                return
            # 记录迁移日志。
            logger.info("Applied migrations:")
            for version, applied_at in rows:
                logger.info(f"- {version} @ {applied_at}")
    finally:
        await engine.dispose()


# 应用迁移。
async def up():
    try:
        # 创建数据库连接。
        async with engine.begin() as conn:
            # 确保迁移表存在。
            await _ensure_migration_table(conn)
            # 检查版本号。
            result = await conn.execute(text(CHECK_VERSION_SQL), {"version": MIGRATION_VERSION})
            # 如果版本号已存在，则返回。
            if result.first():
                logger.info(f"Migration already applied: {MIGRATION_VERSION}")
                return
            # 创建所有表。
            # create_all is idempotent and safe for repeated execution.
            await conn.run_sync(Base.metadata.create_all)
            # 插入版本号。
            await conn.execute(text(INSERT_VERSION_SQL), {"version": MIGRATION_VERSION})
            # 记录迁移日志。
            logger.info(f"Migration applied: {MIGRATION_VERSION}")
    finally:
        await engine.dispose()


# 回滚迁移。
async def down():
    try:
        async with engine.begin() as conn:
            # 确保迁移表存在。
            await _ensure_migration_table(conn)
            # 检查版本号。
            result = await conn.execute(text(CHECK_VERSION_SQL), {"version": MIGRATION_VERSION})
            # 如果版本号不存在，则返回。
            if not result.first():
                logger.info(f"Migration not found, nothing to rollback: {MIGRATION_VERSION}")
                return

            # Drop only TravelMind-related tables in reverse dependency order.
            await conn.execute(text("DROP TABLE IF EXISTS itinerary_evidence"))
            await conn.execute(text("DROP TABLE IF EXISTS itinerary_diffs"))
            await conn.execute(text("DROP TABLE IF EXISTS itinerary_revisions"))
            await conn.execute(text("DROP TABLE IF EXISTS itineraries"))
            await conn.execute(text("DROP TABLE IF EXISTS travel_conversation_states"))
            await conn.execute(text(DELETE_VERSION_SQL), {"version": MIGRATION_VERSION})
            logger.warning(f"Migration rolled back: {MIGRATION_VERSION}")
    finally:
        await engine.dispose()


# 主函数。
def main():
    parser = argparse.ArgumentParser(description="Simple migration/version manager for TravelMind tables.")
    parser.add_argument("action", choices=["up", "down", "status"], help="Migration action")
    args = parser.parse_args()

    if args.action == "up":
        asyncio.run(up())
    elif args.action == "down":
        asyncio.run(down())
    else:
        asyncio.run(status())


if __name__ == "__main__":
    main()
