"""Health reporting for `search-gateway doctor` / `search-gateway check`.

Kept separate from `server.py` so the CLI can run diagnostics without
importing FastMCP (which starts a server). `report()` powers the MCP `doctor`
tool; `check()` is the strict gate used by systemd `ExecStartPre` and CI.
"""

from __future__ import annotations

import asyncio
import time

from . import cache, llm, rerank, stats
from . import embeddings as emb
from .config import (
    ACADEMIC_SOURCES,
    DOCTOR_CACHE_TTL,
    DOCTOR_PROBE_TIMEOUT,
    DOCTOR_TIMEOUT,
)
from .extract import profiles
from .extract.egress import status as egress_status
from .extract.vault import status as vault_status
from .sources import ALL_SOURCES

# probe results are cached in-process: `opencli doctor` ≈ 9s and `uvx` cold
# starts ≈ 2.5s, but source availability rarely changes second-to-second —
# caching makes repeated doctor calls instant while staying bounded.
_probe_cache: dict[str, tuple[float, tuple[bool, str]]] = {}


async def _probe(name: str, src) -> tuple[bool, str]:
    cached = _probe_cache.get(name)
    if cached and (time.monotonic() - cached[0]) < DOCTOR_CACHE_TTL:
        return cached[1]
    try:
        result = await asyncio.wait_for(src.available(), timeout=DOCTOR_PROBE_TIMEOUT)
    except TimeoutError:
        return False, "timeout (probe budget)"
    _probe_cache[name] = (time.monotonic(), result)
    return result


async def report() -> dict:
    """Full health report: Redis, models, every source, academic latency /
    rate-limit status, and ledger health.

    Bounded: probes run concurrently under a `DOCTOR_TIMEOUT` deadline so the
    report always fits inside the MCP client's request timeout; stragglers are
    reported as "timeout" instead of hanging the tool.
    """
    out: dict = {
        "redis": cache.ping(),
        "rerank": rerank.status(),
        "embed": emb.status(),
        "llm": {"available": llm.available()},
        "sources": {},
        "academic": {},
        "ledger": stats.ledger_health(),
        # Phase 7 sections (v0.4.1+): containment + block telemetry + profiles
        "egress": egress_status(),
        "vault": vault_status(),
        "blocks": stats.blocks_snapshot(),
        "profiles": profiles.store.status(),
    }
    tasks = {name: asyncio.ensure_future(_probe(name, src))
             for name, src in ALL_SOURCES.items()}
    await asyncio.wait(tasks.values(), timeout=DOCTOR_TIMEOUT)
    snap = stats.snapshot()
    for name, fut in tasks.items():
        if not fut.done():
            fut.cancel()
            out["sources"][name] = "timeout (probe budget)"
            continue
        if fut.exception() is not None:
            out["sources"][name] = f"error: {fut.exception()}"
            continue
        ok, msg = fut.result()
        out["sources"][name] = ("ok" if ok else "down") + (f" — {msg}" if msg else "")
    # academic health: availability + rolling latency + reliability
    for name in [*ACADEMIC_SOURCES, "semantic_scholar"]:
        probe = out["sources"].get(name, "unknown")
        s = snap.get(name, {})
        out["academic"][name] = {
            "status": probe,
            "latency_s": s.get("avg_latency_s", 0.0),
            "reliability": s.get("reliability", 1.0),
            "rate_limited": (probe.startswith("down")
                             and ("429" in probe or "rate" in probe.lower())),
        }
    return out


async def check() -> tuple[bool, dict]:
    """Strict gate: 23 sources registered + Redis reachable. DeepSeek key is a
    soft signal (answer synthesis is an optional tier) — recorded but never a
    failure. Returns (ok, report)."""
    result: dict = {
        "sources": len(ALL_SOURCES),
        "redis": cache.ping(),
        "llm": {"available": llm.available()},
    }
    ok = True
    if len(ALL_SOURCES) != 23:
        result["error"] = f"expected 23 sources, got {len(ALL_SOURCES)}"
        ok = False
    if not result["redis"].get("ok"):
        result["error"] = result.get("error", "redis unreachable")
        ok = False
    return ok, result
