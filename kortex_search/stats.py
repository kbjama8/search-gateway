"""Per-source reliability & latency counters in Redis.

Feeds weighted RRF (Phase 1.3): each source's rolling success rate becomes
its fusion weight, so flaky sources are naturally down-ranked.

Counters use a daily-reset window (24h EXPIRE) — simple, correct, and
bounded. Latency is tracked as a running mean.
"""

from __future__ import annotations

import logging
import math
import time

import redis

from .config import BLOCK_RESERVOIR, LEDGER_DIR, REDIS_URL, STATS_RESERVOIR_SIZE

logger = logging.getLogger("kortex_search.stats")

_WINDOW = 86400  # 24h
_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def _keys(source: str) -> tuple[str, str, str, str, str]:
    return (f"ks:stats:{source}:total", f"ks:stats:{source}:err",
            f"ks:stats:{source}:lat", f"ks:stats:{source}:latn",
            f"ks:stats:{source}:latres")


def record(source: str, ok: bool, elapsed_s: float) -> None:
    try:
        c = _get_client()
        total, err, lat, latn, latres = _keys(source)
        pipe = c.pipeline()
        pipe.incr(total)
        if not ok:
            pipe.incr(err)
        else:
            # latency accumulates over successes only — errors must not
            # drag the mean down with 0.0 samples
            pipe.incrbyfloat(lat, elapsed_s)
            pipe.incr(latn)
            # bounded reservoir (last N latencies) → p50/p95 percentiles
            pipe.rpush(latres, str(elapsed_s))
            pipe.ltrim(latres, -STATS_RESERVOIR_SIZE, -1)
        for k in (total, err, lat, latn, latres):
            pipe.expire(k, _WINDOW)
        pipe.execute()
    except redis.RedisError as exc:
        logger.debug("stats record error: %s", exc)


def record_block(source: str, vendor: str, level: str) -> None:
    """Record a block event: bounded reservoir + counter (24h TTL).

    Keyed `ks:bl:<source>:<vendor>` so the doctor `blocks` section can break
    down denials by source and vendor (e.g. `egress:floor`, `reddit:cf`).
    `level` rides along in the recent-events list only.
    """
    try:
        c = _get_client()
        key = f"ks:bl:{source}:{vendor}"
        pipe = c.pipeline()
        pipe.incr(key)
        pipe.rpush("ks:bl:recent", f"{source}|{vendor}|{level}|{int(time.time())}")
        pipe.ltrim("ks:bl:recent", -BLOCK_RESERVOIR, -1)
        pipe.expire(key, _WINDOW)
        pipe.expire("ks:bl:recent", _WINDOW)
        pipe.execute()
    except redis.RedisError as exc:
        logger.debug("stats record_block error: %s", exc)


def blocks_snapshot() -> dict:
    """Block counters + the recent-event reservoir (bounded, newest last)."""
    out = {"counters": {}, "total": 0, "recent": []}
    try:
        c = _get_client()
        for key in c.scan_iter("ks:bl:*"):
            name = key.removeprefix("ks:bl:")
            if "|" in name or ":" not in name:
                continue  # the recent list key, not a counter
            n = int(c.get(key) or 0)
            out["counters"][name] = n
            out["total"] += n
        for item in c.lrange("ks:bl:recent", 0, -1):
            parts = item.split("|")
            if len(parts) == 4:
                src, vendor, level, ts = parts
                try:
                    ts = int(ts)
                except ValueError:
                    continue
                out["recent"].append({"source": src, "vendor": vendor,
                                      "level": level, "ts": ts})
        return out
    except redis.RedisError as exc:
        logger.debug("stats blocks snapshot error: %s", exc)
        return out


def _percentiles(values: list[float], *ps: float) -> list[float]:
    """Nearest-rank percentiles of a sorted list (empty → 0.0)."""
    if not values:
        return [0.0 for _ in ps]
    vals = sorted(values)
    out = []
    for p in ps:
        idx = max(0, min(len(vals) - 1, int(p / 100 * len(vals)) - 1))
        out.append(round(vals[idx], 3))
    return out


def latency_percentiles(source: str) -> dict:
    """p50/p95 of the recent-success reservoir (0.0 when unknown)."""
    try:
        c = _get_client()
        raw = c.lrange(_keys(source)[4], 0, -1)
        vals = []
        for v in raw:
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(f):
                vals.append(f)
        p50, p95 = _percentiles(vals, 50, 95)
        return {"p50_s": p50, "p95_s": p95, "samples": len(vals)}
    except redis.RedisError as exc:
        logger.debug("stats percentile error: %s", exc)
        return {"p50_s": 0.0, "p95_s": 0.0, "samples": 0}


def record_error(source: str) -> None:
    record(source, False, 0.0)


def reliability(source: str) -> float:
    """Rolling success rate 0..1 (defaults to 1.0 when unknown)."""
    try:
        c = _get_client()
        total, err, _, _, _ = _keys(source)
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
        for key in c.scan_iter("ks:stats:*:total"):
            src = key.removeprefix("ks:stats:").removesuffix(":total")
            total, err, lat, latn, _ = _keys(src)
            t = int(c.get(total) or 0)
            e = int(c.get(err) or 0)
            lat_sum = float(c.get(lat) or 0)
            lat_n = int(c.get(latn) or 0)
            entry = {
                "queries": t,
                "errors": e,
                "reliability": round(max(0.05, 1.0 - e / t) if t else 1.0, 3),
                "avg_latency_s": round(lat_sum / lat_n, 2) if lat_n else 0.0,
            }
            entry.update(latency_percentiles(src))
            out[src] = entry
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
