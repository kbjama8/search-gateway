# -*- coding: utf-8 -*-
"""Redis-backed cache (keyed by query + sources + category)."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import redis

from .config import CACHE_TTL, REDIS_URL, SOURCE_CACHE_TTL

logger = logging.getLogger("search_gateway.cache")

_client: Optional[redis.Redis] = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def _key(query: str, sources: list[str], category: str, limit: int, filters: str = "") -> str:
    suffix = f":{filters}" if filters else ""
    return f"sg:{category}:{','.join(sorted(sources))}:{limit}:{query.lower().strip()}{suffix}"


def get(query: str, sources: list[str], category: str, limit: int, filters: str = "") -> Optional[list[dict]]:
    try:
        raw = _get_client().get(_key(query, sources, category, limit, filters))
    except redis.RedisError as exc:
        logger.debug("cache get error: %s", exc)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set(query: str, sources: list[str], category: str, limit: int, value: list[dict],
        filters: str = "") -> None:
    try:
        _get_client().set(
            _key(query, sources, category, limit, filters),
            json.dumps(value, ensure_ascii=False),
            ex=CACHE_TTL,
        )
    except redis.RedisError as exc:
        logger.debug("cache set error: %s", exc)


def ping() -> dict[str, Any]:
    """Health check for the doctor tool."""
    try:
        info = _get_client().info("server")
        return {"ok": True, "version": info.get("redis_version")}
    except redis.RedisError as exc:
        return {"ok": False, "error": str(exc)}


def get_source(source: str, query: str, category: str, filters: str = "") -> Optional[list[dict]]:
    """Per-source cache (granular — a query reusing any source hits it)."""
    suffix = f":{filters}" if filters else ""
    key = f"sg:s:{source}:{category}:{query.lower().strip()}{suffix}"
    try:
        raw = _get_client().get(key)
    except redis.RedisError as exc:
        logger.debug("source cache get error: %s", exc)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_source(source: str, query: str, category: str, value: list[dict], filters: str = "") -> None:
    suffix = f":{filters}" if filters else ""
    key = f"sg:s:{source}:{category}:{query.lower().strip()}{suffix}"
    try:
        _get_client().set(key, json.dumps(value, ensure_ascii=False), ex=SOURCE_CACHE_TTL)
    except redis.RedisError as exc:
        logger.debug("source cache set error: %s", exc)
