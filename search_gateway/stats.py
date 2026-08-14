# -*- coding: utf-8 -*-
"""Per-source reliability & latency counters in Redis.

Feeds weighted RRF (Phase 1.3): each source's rolling success rate becomes
its fusion weight, so flaky sources are naturally down-ranked.

Counters use a daily-reset window (24h EXPIRE) — simple, correct, and
bounded. Latency is tracked as a running mean.
"""

from __future__ import annotations

import logging

import redis

from .config import LEDGER_DIR, REDIS_URL

logger = logging.getLogger("search_gateway.stats")

_WINDOW = 86400  # 24h
_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def _keys(source: str) -> tuple[str, str, str, str]:
    return (f"sg:stats:{source}:total", f"sg:stats:{source}:err",
            f"sg:stats:{source}:lat", f"sg:stats:{source}:latn")


def record(source: str, ok: bool, elapsed_s: float) -> None:
    try:
        c = _get_client()
        total, err, lat, latn = _keys(source)
        pipe = c.pipeline()
        pipe.incr(total)
        if not ok:
            pipe.incr(err)
        pipe.incrbyfloat(lat, elapsed_s)
        pipe.incr(latn)
        for k in (total, err, lat, latn):
            pipe.expire(k, _WINDOW)
        pipe.execute()
    except redis.RedisError as exc:
        logger.debug("stats record error: %s", exc)


def record_error(source: str) -> None:
    record(source, False, 0.0)


def reliability(source: str) -> float:
    """Rolling success rate 0..1 (defaults to 1.0 when unknown)."""
    try:
        c = _get_client()
        total, err, _, _ = _keys(source)
        t = int(c.get(total) or 0)
        e = int(c.get(err) or 0)
        if t == 0:
            return 1.0
        return max(0.05, 1.0 - e / t)
    except redis.RedisError as exc:
        logger.debug("stats reliability error: %s", exc)
        return 1.0


def snapshot() -> dict:
    out: dict[str, dict] = {}
    try:
        c = _get_client()
        for key in c.scan_iter("sg:stats:*:total"):
            src = key.removeprefix("sg:stats:").removesuffix(":total")
            total, err, lat, latn = _keys(src)
            t = int(c.get(total) or 0)
            e = int(c.get(err) or 0)
            lat_sum = float(c.get(lat) or 0)
            lat_n = int(c.get(latn) or 0)
            out[src] = {
                "queries": t,
                "errors": e,
                "reliability": round(max(0.05, 1.0 - e / t) if t else 1.0, 3),
                "avg_latency_s": round(lat_sum / lat_n, 2) if lat_n else 0.0,
            }
    except redis.RedisError as exc:
        logger.debug("stats snapshot error: %s", exc)
    return out


def ledger_health() -> dict:
    """Scan the configured ledger dir for deep-research ledgers and report
    run/claim/open-claim health. Read-only and defensive: a missing dir or a
    malformed ledger.json is skipped, never raised."""
    import json
    from pathlib import Path

    base = Path(LEDGER_DIR).expanduser()
    out: dict = {
        "ledger_dir": str(base),
        "configured": bool(LEDGER_DIR),
        "run_count": 0,
        "claim_count": 0,
        "evidence_count": 0,
        "open_claims": 0,
        "runs_with_open_claims": 0,
        "errors": 0,
    }
    if not base.exists():
        return out
    for ledger_path in sorted(base.rglob("ledger.json")):
        out["run_count"] += 1
        try:
            data = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            out["errors"] += 1
            continue
        claims = data.get("claims", [])
        evidence = data.get("evidence", [])
        open_ids = [c.get("id") for c in claims if not c.get("evidence_ids")]
        out["claim_count"] += len(claims)
        out["evidence_count"] += len(evidence)
        out["open_claims"] += len(open_ids)
        if open_ids:
            out["runs_with_open_claims"] += 1
    return out
