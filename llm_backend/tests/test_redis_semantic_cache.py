import asyncio
import fnmatch
import json

import pytest

from app.services.redis_semantic_cache import RedisSemanticCache


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.scan_patterns: list[str] = []
        self.keys_called = False

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex=None):  # noqa: ARG002
        self.store[key] = value

    async def delete(self, *keys: str):
        removed = 0
        for key in keys:
            if key in self.store:
                removed += 1
                del self.store[key]
        return removed

    async def scan_iter(self, match: str):
        self.scan_patterns.append(match)
        for key in list(self.store):
            if fnmatch.fnmatch(key, match):
                yield key

    async def keys(self, pattern: str):  # noqa: ARG002
        self.keys_called = True
        raise AssertionError("RedisSemanticCache should use SCAN instead of KEYS")


def _make_cache(*, threshold: float = 0.8, max_cache_size: int = 1000):
    cache = RedisSemanticCache.__new__(RedisSemanticCache)
    cache.redis = _FakeRedis()
    cache.model_name = "fake-embedding"
    cache.score_threshold = threshold
    cache.prefix = "test-cache"
    cache.max_cache_size = max_cache_size
    cache.cleanup_interval = 3600
    cache._cleanup_task = None
    cache._session = None
    cache._init_faiss_state()
    cache._ensure_cleanup_task = lambda: None
    return cache


def test_exact_cache_hit_skips_embedding_and_scan():
    cache = _make_cache()
    message = "上海 3天 预算5000"
    cache.redis.store[cache._get_response_key(message)] = "cached response"

    async def fail_embedding(text: str):  # noqa: ARG001
        raise AssertionError("exact cache hit should not call embedding")

    cache._get_embedding = fail_embedding

    result = asyncio.run(cache.lookup([{"role": "user", "content": message}]))

    assert result == "cached response"
    assert cache.redis.keys_called is False
    assert cache.redis.scan_patterns == []


def test_semantic_cache_hit_uses_scan_not_keys():
    cache = _make_cache()
    cached_message = "上海三天旅行"
    cache.redis.store[cache._get_vector_key(cached_message)] = json.dumps([1.0, 0.0])
    cache.redis.store[cache._get_response_key(cached_message)] = "semantic response"

    async def fake_embedding(text: str):  # noqa: ARG001
        return [1.0, 0.0]

    cache._get_embedding = fake_embedding

    result = asyncio.run(cache.lookup([{"role": "user", "content": "上海旅行三天"}]))

    assert result == "semantic response"
    assert cache.redis.keys_called is False
    assert cache.redis.scan_patterns == ["test-cache:vec:*"]


def test_faiss_hit_reuses_loaded_index_without_rescan():
    pytest.importorskip("faiss")
    cache = _make_cache()
    cached_message = "上海三天旅行"
    cache.redis.store[cache._get_vector_key(cached_message)] = json.dumps([1.0, 0.0])
    cache.redis.store[cache._get_response_key(cached_message)] = "faiss response"

    async def fake_embedding(text: str):  # noqa: ARG001
        return [1.0, 0.0]

    cache._get_embedding = fake_embedding

    first = asyncio.run(cache.lookup([{"role": "user", "content": "上海旅行三天"}]))
    assert first == "faiss response"
    assert cache.redis.scan_patterns == ["test-cache:vec:*"]

    cache.redis.scan_patterns.clear()
    second = asyncio.run(cache.lookup([{"role": "user", "content": "上海三日游"}]))

    assert second == "faiss response"
    assert cache.redis.keys_called is False
    assert cache.redis.scan_patterns == []


def test_faiss_unavailable_falls_back_to_semantic_scan(monkeypatch):
    import app.services.redis_semantic_cache as cache_module

    monkeypatch.setattr(cache_module, "faiss", None)
    cache = _make_cache()
    cached_message = "上海三天旅行"
    cache.redis.store[cache._get_vector_key(cached_message)] = json.dumps([1.0, 0.0])
    cache.redis.store[cache._get_response_key(cached_message)] = "scan response"

    async def fake_embedding(text: str):  # noqa: ARG001
        return [1.0, 0.0]

    cache._get_embedding = fake_embedding

    result = asyncio.run(cache.lookup([{"role": "user", "content": "上海旅行三天"}]))

    assert result == "scan response"
    assert cache.redis.keys_called is False
    assert cache.redis.scan_patterns == ["test-cache:vec:*"]


def test_update_appends_to_loaded_faiss_index():
    pytest.importorskip("faiss")
    cache = _make_cache()

    async def fake_embedding(text: str):  # noqa: ARG001
        return [1.0, 0.0]

    cache._get_embedding = fake_embedding

    assert asyncio.run(cache.lookup([{"role": "user", "content": "没有缓存"}])) is None
    assert cache._faiss_loaded is True

    asyncio.run(cache.update([{"role": "user", "content": "上海 3天 预算5000"}], "new response"))

    cache.redis.scan_patterns.clear()
    result = asyncio.run(cache.lookup([{"role": "user", "content": "上海三日游"}]))

    assert result == "new response"
    assert cache.redis.scan_patterns == []


def test_cleanup_uses_scan_and_removes_oldest_items():
    cache = _make_cache(max_cache_size=1)
    for idx, last_access in (("old", 1), ("new", 2)):
        cache.redis.store[f"test-cache:vec:{idx}"] = json.dumps([1.0, 0.0])
        cache.redis.store[f"test-cache:resp:{idx}"] = f"response-{idx}"
        cache.redis.store[f"test-cache:meta:{idx}"] = json.dumps({"last_access": last_access})

    asyncio.run(cache._cleanup_once())

    assert "test-cache:vec:old" not in cache.redis.store
    assert "test-cache:resp:old" not in cache.redis.store
    assert "test-cache:meta:old" not in cache.redis.store
    assert "test-cache:vec:new" in cache.redis.store
    assert cache.redis.keys_called is False
    assert cache.redis.scan_patterns == ["test-cache:meta:*"]


@pytest.mark.parametrize("messages", [[], [{"role": "assistant", "content": "hi"}]])
def test_lookup_empty_user_message_returns_miss_without_scan(messages):
    cache = _make_cache()

    result = asyncio.run(cache.lookup(messages))

    assert result is None
    assert cache.redis.keys_called is False
    assert cache.redis.scan_patterns == []
