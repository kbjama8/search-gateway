"""Per-source rate-limit coordinator (Redis) for cookie-logged platforms.

Enforces a minimum interval between queries to a source, protecting the
Kaiser Chen burner accounts from ban-triggering request frequency.
"""

from __future__ import annotations

import asyncio
import logging
import time

import redis

from .config import DAILY_QUERY_LIMIT, REDIS_URL
from .sources.base import SourceError

logger = logging.getLogger("search_gateway.ratelimit")

_client: redis.Redis | None = None
_local: dict[str, float] = {}


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _client


async def enforce_daily_budget(source: str) -> None:
    """Raise `SourceBudgetError` when the source has exceeded its daily query
    budget (Redis counter, 24h window). Protects cookie-logged accounts and
    spend even when the HTTP transport is authenticated but abused."""
    if DAILY_QUERY_LIMIT <= 0:
        return
    try:
        c = _get_client()
        key = f"sg:rl:daily:{source}"
        n = c.incr(key)
        if n == 1:
            c.expire(key, 86400)
        if n > DAILY_QUERY_LIMIT:
            raise SourceBudgetError(
                f"daily query budget exceeded for {source} "
                f"({DAILY_QUERY_LIMIT}/day; SEARCH_GATEWAY_DAILY_QUERY_LIMIT)"
            )
    except redis.RedisError as exc:
        logger.debug("ratelimit daily error: %s", exc)


class SourceBudgetError(SourceError):
    """Daily query budget exceeded (fail the source, not the whole search)."""


async def wait_if_needed(source: str, min_interval: float) -> None:
    """Block until `min_interval` seconds have elapsed since the last query
    to `source` (across processes via Redis; local fallback in-memory).

    The Redis gate stores the monotonic timestamp of the last query, so every
    caller — regardless of process — waits out the remainder of the window.
    """
    now = time.monotonic()
    last = _local.get(source, 0.0)
    wait = last + min_interval - now
    if wait > 0:
        await asyncio.sleep(wait)
    _local[source] = time.monotonic()

    try:
        c = _get_client()
        key = f"sg:rl:{source}"
        prev = c.get(key)
        if prev is not None:
            try:
                remaining = float(prev) + min_interval - time.monotonic()
            except ValueError:
                remaining = 0.0
            if remaining > 0:
                await asyncio.sleep(remaining)
        # persist this query's timestamp; TTL = 3x interval so the key
        # self-cleans when the source goes quiet
        c.set(key, str(time.monotonic()), ex=max(int(min_interval * 3), 30))
    except redis.RedisError as exc:
        logger.debug("ratelimit redis error: %s", exc)
