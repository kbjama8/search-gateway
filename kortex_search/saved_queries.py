"""Saved / recurring query store (Redis) + delta reporting.

The gateway owns Redis (cache/stats/rate-limit), so saved queries live here too.
A thin `monitor` skill wraps the `saved_queries` MCP tool and interprets the
deltas — the intelligence stays in the skill; this module is just persistence
+ re-run + diff.
"""

from __future__ import annotations

import json
import logging
import time

import redis

from . import orchestrator
from .config import DEFAULT_SOURCES, REDIS_URL

logger = logging.getLogger("kortex_search.saved_queries")

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            REDIS_URL, decode_responses=True,
            socket_connect_timeout=1.0, socket_timeout=2.0,
        )
    return _client


def _key(name: str) -> str:
    return f"ks:sq:{name}"


def _get(name: str) -> dict | None:
    try:
        raw = _get_client().get(_key(name))
    except redis.RedisError as exc:
        logger.debug("saved_queries get error: %s", exc)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _snapshot(results: list[dict]) -> list[dict]:
    """Minimal identity fields for delta comparison."""
    out = []
    for r in results:
        out.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "source": r.get("source", ""),
            "published": r.get("published"),
        })
    return out


def _identity(r: dict) -> str:
    url = (r.get("url") or "").strip().rstrip("/")
    return url or (r.get("title") or "").strip().lower()


def save(name: str, query: str, sources: list[str] | None = None,
         freshness: str | None = None, category: str = "general") -> dict:
    if not name or not query:
        return {"error": "name and query are required"}
    rec = {
        "name": name, "query": query, "sources": sources or [],
        "freshness": freshness, "category": category,
        "created_at": time.time(), "last_run": None, "last_results": [],
    }
    try:
        _get_client().set(_key(name), json.dumps(rec, ensure_ascii=False))
    except redis.RedisError as exc:
        return {"error": f"redis error: {exc}"}
    return {"saved": name, "query": query}


def list_all() -> list[dict]:
    out: list[dict] = []
    try:
        for k in _get_client().scan_iter("ks:sq:*"):
            name = k.removeprefix("ks:sq:")
            rec = _get(name)
            if not rec:
                continue
            out.append({f: rec.get(f) for f in
                        ("name", "query", "sources", "freshness", "category", "last_run")})
    except redis.RedisError as exc:
        logger.debug("saved_queries list error: %s", exc)
    return out


def delete(name: str) -> dict:
    try:
        n = _get_client().delete(_key(name))
    except redis.RedisError as exc:
        return {"error": f"redis error: {exc}"}
    return {"deleted": bool(n), "name": name}


async def _run(rec: dict, limit: int) -> dict:
    res = await orchestrator.search(
        rec.get("query"),
        rec.get("sources") or DEFAULT_SOURCES,
        category=rec.get("category") or "general",
        limit=limit,
        freshness=rec.get("freshness"),
        expand=False,
    )
    return res


async def run(name: str, limit: int = 10) -> dict:
    rec = _get(name)
    if not rec:
        return {"error": f"unknown saved query: {name}"}
    res = await _run(rec, limit)
    rec["last_run"] = time.time()
    rec["last_results"] = _snapshot(res.get("results", []))
    try:
        _get_client().set(_key(name), json.dumps(rec, ensure_ascii=False))
    except redis.RedisError as exc:
        return {"error": f"redis error: {exc}"}
    return {"name": name, "count": res.get("count"), "results": res.get("results", [])}


async def diff(name: str, limit: int = 10) -> dict:
    """Delta report in a stable shape: {name, new, removed, unchanged, count}.

    First run has no baseline: it establishes one and reports everything as
    `new` (marked `baseline_established`), so callers never have to branch on
    the response shape.
    """
    rec = _get(name)
    if not rec:
        return {"error": f"unknown saved query: {name}"}
    old = rec.get("last_results") or []
    if not old:
        res = await _run(rec, limit)
        new_snap = _snapshot(res.get("results", []))
        rec["last_run"] = time.time()
        rec["last_results"] = new_snap
        try:
            _get_client().set(_key(name), json.dumps(rec, ensure_ascii=False))
        except redis.RedisError as exc:
            return {"error": f"redis error: {exc}"}
        return {
            "name": name,
            "new": new_snap,
            "removed": [],
            "unchanged": 0,
            "count": res.get("count"),
            "baseline_established": True,
        }
    res = await _run(rec, limit)
    new_snap = _snapshot(res.get("results", []))
    old_ids = {_identity(r) for r in old}
    new_ids = {_identity(r) for r in new_snap}
    new_items = [r for r in new_snap if _identity(r) not in old_ids]
    removed_items = [r for r in old if _identity(r) not in new_ids]
    rec["last_run"] = time.time()
    rec["last_results"] = new_snap
    try:
        _get_client().set(_key(name), json.dumps(rec, ensure_ascii=False))
    except redis.RedisError as exc:
        return {"error": f"redis error: {exc}"}
    return {
        "name": name,
        "new": new_items,
        "removed": removed_items,
        "unchanged": len(old_ids & new_ids),
        "count": res.get("count"),
    }
