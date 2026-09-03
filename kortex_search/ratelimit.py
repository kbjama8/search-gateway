"""Per-source rate-limit coordinator (Redis) for cookie-logged platforms.

Enforces a minimum interval between queries to a source, protecting the
Kaiser Chen burner accounts from ban-triggering request frequency.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time

import redis

from .config import DAILY_QUERY_LIMIT, REDIS_URL
from .sources.base import SourceError

logger = logging.getLogger("kortex_search.ratelimit")

_client: redis.Redis | None = None
_local: dict[str, float] = {}


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            REDIS_URL, decode_responses=True,
            socket_connect_timeout=1.0, socket_timeout=2.0,
        )
    return _client


async def enforce_daily_budget(source: str) -> None:
    """Raise `SourceBudgetError` when the source has exceeded its daily query
    budget (Redis counter, 24h window). Protects cookie-logged accounts and
    spend even when the HTTP transport is authenticated but abused."""
    if DAILY_QUERY_LIMIT <= 0:
        return
    try:
        c = _get_client()
        key = f"ks:rl:daily:{source}"
        n = c.incr(key)
        if n == 1:
            c.expire(key, 86400)
        if n > DAILY_QUERY_LIMIT:
            raise SourceBudgetError(
                f"daily query budget exceeded for {source} "
                f"({DAILY_QUERY_LIMIT}/day; KORTEX_SEARCH_DAILY_QUERY_LIMIT)"
            )
    except redis.RedisError as exc:
        logger.debug("ratelimit daily error: %s", exc)


class SourceBudgetError(SourceError):
    """Daily query budget exceeded (fail the source, not the whole search)."""


async def wait_if_needed(source: str, min_interval: float) -> None:
    """Block until `min_interval` seconds have elapsed since the last query
    to `source` (across processes via Redis; local fallback in-memory).

    The Redis gate is an ATOMIC claim: `SET key ts NX EX ttl` — exactly one
    concurrent caller claims the pacing slot; the others read the holder's
    timestamp and sleep the remainder, then re-claim (a stale slot is
    deleted and reclaimed). The old read-then-set pattern let concurrent
    callers both read the old timestamp and fire together, defeating the
    ban-protection pacing (bug-sweep discovery 2026-08-26).
    """
    now = time.monotonic()
    last = _local.get(source, 0.0)
    wait = last + min_interval - now
    if wait > 0:
        await asyncio.sleep(wait)
    _local[source] = time.monotonic()

    ttl = max(int(min_interval * 3), 30)
    try:
        c = _get_client()
        key = f"ks:rl:{source}"
        while True:
            if c.set(key, str(time.monotonic()), nx=True, ex=ttl):
                return  # claimed the pacing slot
            prev = c.get(key)
            try:
                remaining = float(prev) + min_interval - time.monotonic()
            except (TypeError, ValueError):
                remaining = 0.0
            if not math.isfinite(remaining) or remaining <= 0:
                # the holder's slot is stale (holder died / interval elapsed)
                # OR the value is garbage (nan/inf — cache poisoning, chaos
                # suite): delete and re-claim — the last claim always wins, so
                # pacing is measured from the newest timestamp, never shorter
                c.delete(key)
                continue
            # capped sleeps so cancellation/callers stay responsive
            await asyncio.sleep(min(remaining, 2.0))
    except redis.RedisError as exc:
        logger.debug("ratelimit redis error: %s", exc)
