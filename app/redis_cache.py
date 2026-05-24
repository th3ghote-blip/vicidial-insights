"""
Redis cache layer — thin wrapper around redis-py.

Design:
- No-ops silently if REDIS_URL is not set (safe in mock mode / local dev).
- All values are JSON-serialised strings — no pickle, no binary blobs.
- Caller passes TTL explicitly; default is settings.cache_ttl (300s).
- Thread-safe: redis-py connection pool is shared across requests.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .config import settings

log = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not settings.redis_url:
        return None
    try:
        import redis as _redis
        _client = _redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
        _client.ping()
        log.info("redis: connected to %s", settings.redis_url.split("@")[-1])
    except Exception as exc:
        log.warning("redis: could not connect — %s (running without cache)", exc)
        _client = None
    return _client


def is_available() -> bool:
    return _get_client() is not None


def cache_get(key: str) -> Any | None:
    r = _get_client()
    if not r:
        return None
    try:
        raw = r.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception as exc:
        log.warning("redis get(%s) failed: %s", key, exc)
        return None


def cache_set(key: str, data: Any, ttl: int | None = None) -> None:
    r = _get_client()
    if not r:
        return
    try:
        r.setex(key, ttl or settings.cache_ttl, json.dumps(data, default=str))
    except Exception as exc:
        log.warning("redis set(%s) failed: %s", key, exc)


def cache_delete(key: str) -> None:
    r = _get_client()
    if not r:
        return
    try:
        r.delete(key)
    except Exception as exc:
        log.warning("redis delete(%s) failed: %s", key, exc)
