"""
Redis-compatible caching layer for Agent Sentinel.

Uses in-process LRU cache by default. Set REDIS_URL to enable a real Redis
backend (requires redis package: pip install redis).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger("cache")

_DEFAULT_TTL_SECONDS = int(os.getenv("CACHE_DEFAULT_TTL_SECONDS", "3600"))
_EVAL_CACHE_TTL = int(os.getenv("EVAL_CACHE_TTL_SECONDS", "7200"))
_REDIS_URL = os.getenv("REDIS_URL", "")


class _MemoryCache:
    """Thread-safe-enough LRU cache with TTL for single-process Cloud Run."""

    def __init__(self, max_size: int = 2000):
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at and time.time() > expires_at:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else _DEFAULT_TTL_SECONDS
        expires_at = time.time() + ttl if ttl > 0 else 0
        self._store[key] = (value, expires_at)
        self._store.move_to_end(key)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


class _RedisCache:
    """Thin wrapper matching _MemoryCache interface."""

    def __init__(self, url: str):
        import redis

        self._client = redis.from_url(url, decode_responses=True)

    def get(self, key: str) -> Any | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else _DEFAULT_TTL_SECONDS
        self._client.setex(key, ttl, json.dumps(value))

    def delete(self, key: str) -> None:
        self._client.delete(key)


def _build_cache():
    if _REDIS_URL:
        try:
            cache = _RedisCache(_REDIS_URL)
            logger.info("Using Redis cache at configured REDIS_URL")
            return cache
        except Exception as exc:
            logger.warning("Redis unavailable (%s); falling back to in-memory cache", exc)
    return _MemoryCache(max_size=int(os.getenv("MEMORY_CACHE_MAX_SIZE", "2000")))


_cache = _build_cache()

# Scenario JSON files — loaded once per process
_scenario_cache: dict[str, Any] | None = None


def get_cached(key: str) -> Any | None:
    return _cache.get(key)


def set_cached(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    _cache.set(key, value, ttl_seconds)


def delete_cached(key: str) -> None:
    _cache.delete(key)


def eval_cache_key(scenario: dict, agent_response: str) -> str:
    """Stable key for eval judge results (attack prompt + response)."""
    payload = json.dumps(
        {
            "scenario_id": scenario.get("scenario_id"),
            "user_message": scenario.get("user_message"),
            "expected_behavior": scenario.get("expected_behavior"),
            "agent_response": agent_response,
        },
        sort_keys=True,
    )
    return f"eval:{hashlib.sha256(payload.encode()).hexdigest()}"


def get_eval_cache(scenario: dict, agent_response: str) -> dict | None:
    return get_cached(eval_cache_key(scenario, agent_response))


def set_eval_cache(scenario: dict, agent_response: str, result: dict) -> None:
    set_cached(eval_cache_key(scenario, agent_response), result, _EVAL_CACHE_TTL)


def get_scenario_cache() -> dict[str, Any] | None:
    return _scenario_cache


def set_scenario_cache(data: dict[str, Any]) -> None:
    global _scenario_cache
    _scenario_cache = data
