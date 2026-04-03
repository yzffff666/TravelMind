"""Provider factory: builds a ready-to-use ``ProviderRegistry``.

Strategy:
1. If a valid ``SERPAPI_KEY`` is configured → register real SerpAPI providers.
2. Always register Mock providers as fallback (lower priority).

The ``ProviderOrchestrator`` iterates providers in registration order,
so real providers are tried first; if they fail the orchestrator's
error handling kicks in and mock results may still contribute.
"""

from __future__ import annotations

import logging
import os

from app.services.providers.mock_providers import MockMapProvider, MockSearchProvider
from app.services.providers.registry import ProviderRegistry
from app.services.providers.serp_providers import (
    SerpApiMapProvider,
    SerpApiSearchProvider,
)

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYS = {"", "xxxxx", "xxxx", "your-api-key", "sk-xxxx"}


def _get_serpapi_key() -> str | None:
    """Return the SerpAPI key if it looks real, else None."""
    try:
        from app.core.config import settings
        key = settings.SERPAPI_KEY
    except Exception:
        key = os.getenv("SERPAPI_KEY", "")

    if not key or key.strip().lower() in _PLACEHOLDER_KEYS:
        return None
    return key.strip()


def build_registry(*, include_mock_fallback: bool = True) -> ProviderRegistry:
    """Build a ``ProviderRegistry`` with the best available providers.

    Returns a registry ready to be passed to ``ProviderOrchestrator``.
    """
    registry = ProviderRegistry()
    serpapi_key = _get_serpapi_key()

    if serpapi_key:
        logger.info("SerpAPI key detected — registering real search & map providers")
        registry.register_search(SerpApiSearchProvider(serpapi_key))
        registry.register_map(SerpApiMapProvider(serpapi_key))
    else:
        logger.warning(
            "SerpAPI key not configured or is placeholder — "
            "only mock providers will be available. "
            "Set SERPAPI_KEY in .env to enable real search."
        )

    if include_mock_fallback:
        registry.register_search(MockSearchProvider())
        registry.register_map(MockMapProvider())

    return registry
