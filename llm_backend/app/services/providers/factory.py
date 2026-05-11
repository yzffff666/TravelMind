"""Provider factory: builds a ready-to-use ``ProviderRegistry``.

Registration order = priority (first registered, first tried).

Strategy:
1. Amap (高德) — best for Chinese cities, generous free quota.
2. SerpAPI — good for international cities or web search.
3. Mock — always-available fallback with fixture data.

The ``ProviderOrchestrator`` iterates providers in registration order,
so higher-quality providers are tried first; if they fail the
orchestrator's error handling kicks in and lower-priority providers
may still contribute.
"""

from __future__ import annotations

import logging
import os

from app.services.providers.amap_provider import AmapMapProvider, AmapSearchProvider
from app.services.providers.mock_providers import MockMapProvider, MockSearchProvider
from app.services.providers.registry import ProviderRegistry
from app.services.providers.serp_providers import (
    SerpApiMapProvider,
    SerpApiSearchProvider,
)

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYS = {"", "xxxxx", "xxxx", "your-api-key", "sk-xxxx"}


def _get_key(setting_name: str, env_name: str) -> str | None:
    """Return an API key if it looks real, else None."""
    try:
        from app.core.config import settings
        key = getattr(settings, setting_name, "")
    except Exception:
        key = os.getenv(env_name, "")

    if not key or key.strip().lower() in _PLACEHOLDER_KEYS:
        return None
    return key.strip()


def _provider_enabled(setting_name: str, env_name: str, default: bool = True) -> bool:
    """Return whether a provider is allowed to register even when a key exists."""
    try:
        from app.core.config import settings
        return bool(getattr(settings, setting_name, default))
    except Exception:
        raw = os.getenv(env_name)
        if raw is None:
            return default
        return raw.strip().lower() not in {"0", "false", "no", "off"}


def build_registry(*, include_mock_fallback: bool = True) -> ProviderRegistry:
    """Build a ``ProviderRegistry`` with the best available providers.

    Returns a registry ready to be passed to ``ProviderOrchestrator``.
    """
    registry = ProviderRegistry()

    amap_enabled = _provider_enabled("AMAP_ENABLED", "AMAP_ENABLED")
    amap_key = _get_key("AMAP_API_KEY", "AMAP_API_KEY") if amap_enabled else None
    if amap_key:
        logger.info("Amap key detected — registering 高德 search & map providers (priority 1)")
        registry.register_search(AmapSearchProvider(amap_key))
        registry.register_map(AmapMapProvider(amap_key))
    elif not amap_enabled:
        logger.info("Amap providers disabled by AMAP_ENABLED=false")

    serpapi_enabled = _provider_enabled("SERPAPI_ENABLED", "SERPAPI_ENABLED")
    serpapi_key = _get_key("SERPAPI_KEY", "SERPAPI_KEY") if serpapi_enabled else None
    if serpapi_key:
        logger.info("SerpAPI key detected — registering search & map providers (priority 2)")
        registry.register_search(SerpApiSearchProvider(serpapi_key))
        registry.register_map(SerpApiMapProvider(serpapi_key))
    elif not serpapi_enabled:
        logger.info("SerpAPI providers disabled by SERPAPI_ENABLED=false")

    if not amap_key and not serpapi_key:
        logger.warning(
            "No real API keys configured — only mock providers will be available. "
            "Set AMAP_API_KEY or SERPAPI_KEY in .env to enable real search."
        )

    if include_mock_fallback:
        registry.register_search(MockSearchProvider())
        registry.register_map(MockMapProvider())

    return registry
