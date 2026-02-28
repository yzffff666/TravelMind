import sys
from pathlib import Path
import argparse

# 添加项目根目录到 PYTHONPATH
ROOT_DIR = Path(__file__).parent.parent
sys.path.append(str(ROOT_DIR))

# 确保能找到 app 模块
# print(f"Python path: {sys.path}")
# print(f"Current directory: {Path.cwd()}")
# print(f"Root directory: {ROOT_DIR}")

import asyncio
from sqlalchemy import text
from app.core.database import engine, Base
from app.models import (
    User,
    Conversation,
    Message,
    Itinerary,
    ItineraryRevision,
    ItineraryDiff,
    ItineraryEvidence,
)
from app.core.logger import get_logger

logger = get_logger(service="init_db")

async def init_db(reset: bool = False):
    try:
        logger.info("Initializing database...")
        async with engine.begin() as conn:
            if reset:
                logger.warning("Reset mode enabled: dropping all tables first.")
                await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            result = await conn.execute(text("SHOW TABLES"))
            tables = [row[0] for row in result.fetchall()]
            logger.info(f"Current tables: {tables}")
        logger.info("Database initialization completed successfully!")
    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}")
        raise
    finally:
        await engine.dispose()

def main():
    parser = argparse.ArgumentParser(description="Initialize MySQL schema for local development.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop all tables before create_all. Use with caution.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(init_db(reset=args.reset))
    except RuntimeError as e:
        logger.error(f"Runtime error: {str(e)}")
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    main()