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
import time

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

    def _get_metadata_key_by_hash(self, hash_id: str) -> str:
        return f"{self.prefix}:meta:{hash_id}"

    def _get_response_key_by_hash(self, hash_id: str) -> str:
        return f"{self.prefix}:resp:{hash_id}"

    def _get_last_user_message(self, messages: List[Dict]) -> str:
        for msg in reversed(messages):
            if msg["role"] == "user":
                return msg["content"]
        return ""

    def _ensure_cleanup_task(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.ensure_future(self._auto_cleanup())

    async def _scan_keys(self, pattern: str) -> list[str]:
        """Incrementally scan keys instead of blocking Redis with KEYS."""
        return [key async for key in self.redis.scan_iter(match=pattern)]

    async def _auto_cleanup(self) -> None:
        while True:
            try:
                await self._cleanup_once()
                logger.info(f"Cache cleanup completed for prefix {self.prefix}")
            except Exception as e:
                logger.error(f"Error in cache cleanup: {e}", exc_info=True)

            await asyncio.sleep(self.cleanup_interval)

    async def _cleanup_once(self) -> None:
        pattern = f"{self.prefix}:meta:*"
        all_keys: List[str] = await self._scan_keys(pattern)

        if len(all_keys) <= self.max_cache_size:
            return

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

    async def _remove_cache_item(self, hash_id: str) -> None:
        await self.redis.delete(
            f"{self.prefix}:vec:{hash_id}",
            f"{self.prefix}:resp:{hash_id}",
            f"{self.prefix}:meta:{hash_id}",
        )

    async def _update_metadata(self, message: str | None = None, *, hash_id: str | None = None) -> None:
        if hash_id is None:
            if not message:
                return
            hash_id = self._hash(message)
        meta_key = self._get_metadata_key_by_hash(hash_id)
        raw = await self.redis.get(meta_key)
        current_meta = json.loads(raw) if raw else {"access_count": 0}
        metadata = {
            "created_at": current_meta.get("created_at", datetime.now().timestamp()),
            "last_access": datetime.now().timestamp(),
            "access_count": current_meta.get("access_count", 0) + 1,
        }
        await self.redis.set(meta_key, json.dumps(metadata), ex=settings.REDIS_CACHE_EXPIRE)

    async def lookup(self, messages: List[Dict]) -> Optional[str]:
        self._ensure_cleanup_task()
        started = time.perf_counter()
        scanned_count = 0
        try:
            user_message = self._get_last_user_message(messages)
            if not user_message:
                return None

            exact_response: str | None = await self.redis.get(self._get_response_key(user_message))
            if exact_response:
                await self._update_metadata(user_message)
                self._log_lookup(
                    cache_source="exact",
                    lookup_ms=self._elapsed_ms(started),
                    scanned_count=scanned_count,
                    similarity=1.0,
                )
                return exact_response

            current_vector = await self._get_embedding(user_message)

            pattern = f"{self.prefix}:vec:*"
            all_vec_keys: List[str] = await self._scan_keys(pattern)

            max_similarity = 0.0
            most_similar_key: str | None = None

            for vec_key in all_vec_keys:
                scanned_count += 1
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
                resp_key = self._get_response_key_by_hash(hash_id)
                cached_response: str | None = await self.redis.get(resp_key)
                if cached_response:
                    await self._update_metadata(hash_id=hash_id)
                    self._log_lookup(
                        cache_source="semantic",
                        lookup_ms=self._elapsed_ms(started),
                        scanned_count=scanned_count,
                        similarity=max_similarity,
                    )
                    return cached_response

            self._log_lookup(
                cache_source="miss",
                lookup_ms=self._elapsed_ms(started),
                scanned_count=scanned_count,
                similarity=max_similarity,
            )
            return None
        except Exception as e:
            logger.error(f"Error in lookup: {e}", exc_info=True)
            return None

    def _log_lookup(
        self,
        *,
        cache_source: str,
        lookup_ms: float,
        scanned_count: int,
        similarity: float | None = None,
    ) -> None:
        logger.info(
            "semantic_cache_lookup",
            extra={
                "prefix": self.prefix,
                "cache_source": cache_source,
                "lookup_ms": lookup_ms,
                "scanned_count": scanned_count,
                "similarity": round(similarity, 4) if similarity is not None else None,
            },
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)

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
