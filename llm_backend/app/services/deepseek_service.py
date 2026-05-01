from typing import List, Dict, AsyncGenerator, Callable, Optional
from openai import AsyncOpenAI
from app.core.config import settings
import json
from app.core.logger import get_logger
from app.core.database import AsyncSessionLocal
from app.models.conversation import Conversation, DialogueType
from app.models.message import Message
from app.services.redis_semantic_cache import RedisSemanticCache
import time
import asyncio

logger = get_logger(service="deepseek")

class DeepseekService:
    def __init__(self, model: str = "deepseek-chat"):
        logger.info("Initializing Deepseek Service")
        self.client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL
        )

        # 优先使用配置中的 DEEPSEEK_MODEL，其次使用传入的 model
        self.model = settings.DEEPSEEK_MODEL or model
        self.cache = RedisSemanticCache(prefix="deepseek")

    async def _create_completion_with_retry(self, messages: List[Dict], *, stream: bool):
        max_attempts = max(1, settings.CHAT_LLM_MAX_ATTEMPTS)
        timeout_seconds = max(0.1, settings.CHAT_LLM_TIMEOUT_SECONDS)
        backoff_seconds = max(0.0, settings.CHAT_LLM_RETRY_BACKOFF_SECONDS)
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            started = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        stream=stream,
                    ),
                    timeout=timeout_seconds,
                )
                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "deepseek_llm_call",
                    extra={
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "timeout_ms": int(timeout_seconds * 1000),
                        "elapsed_ms": round(elapsed_ms, 2),
                        "stream": stream,
                        "status": "ok",
                    },
                )
                return response
            except Exception as exc:  # noqa: BLE001
                elapsed_ms = (time.perf_counter() - started) * 1000
                last_exc = exc
                logger.warning(
                    "deepseek_llm_call_failed",
                    extra={
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "timeout_ms": int(timeout_seconds * 1000),
                        "elapsed_ms": round(elapsed_ms, 2),
                        "stream": stream,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "retryable": attempt < max_attempts,
                    },
                )
                if attempt >= max_attempts:
                    break
                await asyncio.sleep(backoff_seconds * attempt)

        assert last_exc is not None
        raise last_exc

    # 流式返回缓存的响应
    async def _stream_cached_response(self, response: str, delay: float = 0.05) -> AsyncGenerator[str, None]:
        """模拟流式返回缓存的响应"""
        # 每次返回4个字符
        chunks = [response[i:i + 4] for i in range(0, len(response), 4)]
        for chunk in chunks:
            await asyncio.sleep(delay)  # 50ms延迟
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    # 流式生成回复
    async def generate_stream(
        self,
        messages: List[Dict],
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        on_complete: Optional[Callable[[int, int, List[Dict], str], None]] = None
    ) -> AsyncGenerator[str, None]:
        """流式生成回复"""
        try:
            # 为每个用户创建独立的缓存实例
            cache = RedisSemanticCache(prefix="deepseek", user_id=user_id)

            start_time = time.time()

            # 检查缓存
            cached_response = await cache.lookup(messages)
            if cached_response:
                response_time = time.time() - start_time
                logger.info(f"Cache hit! Response time: {response_time:.4f} seconds")

                # 模拟流式返回，因为速率太快了
                async for chunk in self._stream_cached_response(cached_response):
                    yield chunk

                if on_complete and user_id is not None and conversation_id is not None:
                    await on_complete(user_id, conversation_id, messages, cached_response)
                return

            # 缓存未命中,调用API
            full_response = []
            response = await self._create_completion_with_retry(messages, stream=True)

            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    # 使用 ensure_ascii=False 来保持中文字符
                    content = json.dumps(chunk.choices[0].delta.content, ensure_ascii=False)

                    full_response.append(content)
                    yield f"data: {content}\n\n"

            # 完整响应
            complete_response = "".join(full_response)

            # 更新缓存
            await cache.update(messages, complete_response)

            response_time = time.time() - start_time
            logger.info(f"Cache miss. Response time: {response_time:.4f} seconds")

            # 如果有回调，执行回调
            if on_complete and user_id is not None and conversation_id is not None:
                await on_complete(user_id, conversation_id, messages, complete_response)

        except Exception as e:
            logger.error(f"Error in generate_stream: {str(e)}", exc_info=True)
            error_msg = json.dumps(f"生成回复时出错: {str(e)}", ensure_ascii=False)
            yield f"data: {error_msg}\n\n"

    async def generate(self, messages: List[Dict]) -> str:
        """非流式生成回复"""
        try:
            response = await self._create_completion_with_retry(messages, stream=False)
            return response.choices[0].message.content
        except Exception as e:
            print(f"Generation error: {str(e)}")
            raise