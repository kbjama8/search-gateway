# -*- coding: utf-8 -*-
"""Health reporting for `search-gateway doctor` / `search-gateway check`.

Kept separate from `server.py` so the CLI can run diagnostics without
importing FastMCP (which starts a server). `report()` powers the MCP `doctor`
tool; `check()` is the strict gate used by systemd `ExecStartPre` and CI.
"""

from __future__ import annotations

import asyncio

from . import cache, llm, rerank, stats
from . import embeddings as emb
from .config import ACADEMIC_SOURCES
from .sources import ALL_SOURCES


async def report() -> dict:
    """Full health report: Redis, models, every source, academic latency /
    rate-limit status, and ledger health."""
    out: dict = {
        "redis": cache.ping(),
        "rerank": rerank.status(),
        "embed": emb.status(),
        "llm": {"available": llm.available()},
        "sources": {},
        "academic": {},
        "ledger": stats.ledger_health(),
    }
    probes = {name: src.available() for name, src in ALL_SOURCES.items()}
    results = await asyncio.gather(*probes.values(), return_exceptions=True)
    snap = stats.snapshot()
    for name, res in zip(probes.keys(), results):
        if isinstance(res, Exception):
            out["sources"][name] = f"error: {res}"
        else:
            ok, msg = res
            out["sources"][name] = ("ok" if ok else "down") + (f" — {msg}" if msg else "")
    # academic health: availability + rolling latency + reliability
    for name in ACADEMIC_SOURCES + ["semantic_scholar"]:
        probe = out["sources"].get(name, "unknown")
        s = snap.get(name, {})
        out["academic"][name] = {
            "status": probe,
            "latency_s": s.get("avg_latency_s", 0.0),
            "reliability": s.get("reliability", 1.0),
            "rate_limited": probe.startswith("down") and ("429" in probe or "rate" in probe.lower()),
        }
    return out


async def check() -> tuple[bool, dict]:
    """Strict gate: 18 sources registered + Redis reachable. DeepSeek key is a
    soft signal (answer synthesis is an optional tier) — recorded but never a
    failure. Returns (ok, report)."""
    result: dict = {
        "sources": len(ALL_SOURCES),
        "redis": cache.ping(),
        "llm": {"available": llm.available()},
    }
    ok = True
    if len(ALL_SOURCES) != 18:
        result["error"] = f"expected 18 sources, got {len(ALL_SOURCES)}"
        ok = False
    if not result["redis"].get("ok"):
        result["error"] = result.get("error", "redis unreachable")
        ok = False
    return ok, result
