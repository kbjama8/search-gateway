# -*- coding: utf-8 -*-
"""Per-source rate-limit coordinator (Redis) for cookie-logged platforms.

Enforces a minimum interval between queries to a source, protecting the
Kaiser Chen burner accounts from ban-triggering request frequency.
"""

from __future__ import annotations

import asyncio
import logging
import time

import redis

from .config import REDIS_URL

logger = logging.getLogger("search_gateway.ratelimit")

_client: redis.Redis | None = None
_local: dict[str, float] = {}


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _client


async def wait_if_needed(source: str, min_interval: float) -> None:
    """Block until `min_interval` seconds have elapsed since the last query
    to `source` (across processes via Redis; local fallback in-memory)."""
    now = time.monotonic()
    last = _local.get(source, 0.0)
    wait = last + min_interval - now
    if wait > 0:
        await asyncio.sleep(wait)
    _local[source] = time.monotonic()

    try:
        c = _get_client()
        key = f"sg:rl:{source}"
        # Redis SET NX EX acts as a distributed lock-ish gate
        if c.set(key, "1", nx=True, ex=int(min_interval * 2) or 1):
            return
    except redis.RedisError as exc:
        logger.debug("ratelimit redis error: %s", exc)
