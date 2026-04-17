from typing import Dict, List, Optional
import redis.asyncio as aioredis
import hashlib
import numpy as np
import json
import aiohttp
from app.core.config import settings
from app.core.logger import get_logger
import asyncio
from datetime import datetime

logger = get_logger(service="redis_cache")


class RedisSemanticCache:
    """基于语义的 Redis 缓存实现（全异步版本）"""

    def __init__(
        self,
        redis_url: str = None,
        model_name: str = None,
        score_threshold: float = None,
        prefix: str = "cache",
        user_id: Optional[int] = None,
        max_cache_size: int = 1000,
        cleanup_interval: int = 3600,
    ):
        # decode_responses=True 让 redis-py 自动处理字符串编解码，无需手动 encode/decode
        self.redis: aioredis.Redis = aioredis.from_url(
            redis_url or settings.REDIS_URL,
            decode_responses=True,
        )
        self.model_name = model_name or settings.OLLAMA_EMBEDDING_MODEL
        self.score_threshold = score_threshold or settings.REDIS_CACHE_THRESHOLD
        self.prefix = f"{prefix}:{user_id}" if user_id else prefix
        self.max_cache_size = max_cache_size
        self.cleanup_interval = cleanup_interval
        self._cleanup_task: asyncio.Task | None = None
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _get_ollama_embedding(self, text: str) -> List[float]:
        session = await self._get_session()
        async with session.post(
            f"{settings.OLLAMA_BASE_URL}/api/embed",
            json={"model": self.model_name, "input": text},
        ) as response:
            result = await response.json()
            return result["embeddings"][0]

    async def _get_embedding(self, text: str) -> List[float]:
        try:
            embedding = await self._get_ollama_embedding(text)
            if not embedding:
                raise ValueError("Empty embedding returned")
            return embedding
        except Exception as e:
            logger.error(f"Error getting embedding: {e}", exc_info=True)
            raise

    def _hash(self, message: str) -> str:
        return hashlib.md5(message.encode()).hexdigest()

    def _get_vector_key(self, message: str) -> str:
        return f"{self.prefix}:vec:{self._hash(message)}"

    def _get_response_key(self, message: str) -> str:
        return f"{self.prefix}:resp:{self._hash(message)}"

    def _get_metadata_key(self, message: str) -> str:
        return f"{self.prefix}:meta:{self._hash(message)}"

    def _get_last_user_message(self, messages: List[Dict]) -> str:
        for msg in reversed(messages):
            if msg["role"] == "user":
                return msg["content"]
        return ""

    def _ensure_cleanup_task(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.ensure_future(self._auto_cleanup())

    async def _auto_cleanup(self) -> None:
        while True:
            try:
                pattern = f"{self.prefix}:meta:*"
                all_keys: List[str] = await self.redis.keys(pattern)

                if len(all_keys) > self.max_cache_size:
                    cache_items = []
                    for key in all_keys:
                        raw = await self.redis.get(key)
                        if raw:
                            meta = json.loads(raw)
                            cache_items.append((key, meta.get("last_access", 0)))

                    cache_items.sort(key=lambda x: x[1])
                    items_to_remove = len(all_keys) - self.max_cache_size
                    for key, _ in cache_items[:items_to_remove]:
                        hash_id = key.split(":")[-1]
                        await self._remove_cache_item(hash_id)

                logger.info(f"Cache cleanup completed for prefix {self.prefix}")
            except Exception as e:
                logger.error(f"Error in cache cleanup: {e}", exc_info=True)

            await asyncio.sleep(self.cleanup_interval)

    async def _remove_cache_item(self, hash_id: str) -> None:
        await self.redis.delete(
            f"{self.prefix}:vec:{hash_id}",
            f"{self.prefix}:resp:{hash_id}",
            f"{self.prefix}:meta:{hash_id}",
        )

    async def _update_metadata(self, message: str) -> None:
        meta_key = self._get_metadata_key(message)
        raw = await self.redis.get(meta_key)
        current_meta = json.loads(raw) if raw else {"access_count": 0}
        metadata = {
            "last_access": datetime.now().timestamp(),
            "access_count": current_meta["access_count"] + 1,
        }
        await self.redis.set(meta_key, json.dumps(metadata), ex=settings.REDIS_CACHE_EXPIRE)

    async def lookup(self, messages: List[Dict]) -> Optional[str]:
        self._ensure_cleanup_task()
        try:
            user_message = self._get_last_user_message(messages)
            if not user_message:
                return None

            current_vector = await self._get_embedding(user_message)

            pattern = f"{self.prefix}:vec:*"
            all_vec_keys: List[str] = await self.redis.keys(pattern)

            max_similarity = 0.0
            most_similar_key: str | None = None

            for vec_key in all_vec_keys:
                raw = await self.redis.get(vec_key)
                if not raw:
                    continue
                cached_vector = json.loads(raw)
                similarity = float(np.dot(current_vector, cached_vector) / (
                    np.linalg.norm(current_vector) * np.linalg.norm(cached_vector)
                ))
                if similarity > max_similarity:
                    max_similarity = similarity
                    most_similar_key = vec_key

            if max_similarity >= self.score_threshold and most_similar_key:
                hash_id = most_similar_key.split(":")[-1]
                resp_key = f"{self.prefix}:resp:{hash_id}"
                cached_response: str | None = await self.redis.get(resp_key)
                if cached_response:
                    await self._update_metadata(user_message)
                    logger.info(f"Cache hit with similarity: {max_similarity:.4f}")
                    return cached_response

            return None
        except Exception as e:
            logger.error(f"Error in lookup: {e}", exc_info=True)
            return None

    async def update(self, messages: List[Dict], response: str, expire: int = None) -> None:
        self._ensure_cleanup_task()
        try:
            user_message = self._get_last_user_message(messages)
            if not user_message:
                return

            vector = await self._get_embedding(user_message)
            expire = expire or settings.REDIS_CACHE_EXPIRE

            await self.redis.set(self._get_vector_key(user_message), json.dumps(vector), ex=expire)
            await self.redis.set(self._get_response_key(user_message), response, ex=expire)
            await self.redis.set(
                self._get_metadata_key(user_message),
                json.dumps({
                    "created_at": datetime.now().timestamp(),
                    "last_access": datetime.now().timestamp(),
                    "access_count": 1,
                }),
                ex=expire,
            )
            logger.info(f"Cache updated for message: {user_message[:50]}...")
        except Exception as e:
            logger.error(f"Error in update: {e}", exc_info=True)
