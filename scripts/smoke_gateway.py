#!/usr/bin/env python3
"""Live gateway journey smoke — the full MCP tool surface as a fresh
research agent would drive it, against the systemd HTTP gateway.

Prerequisites:
  * kortex-search@8765.service running
  * KORTEX_SEARCH_HTTP_TOKEN exported (gateway.env)

Usage:  python3 scripts/smoke_gateway.py
   or:  KORTEX_SEARCH_SMOKE_GATEWAY=1 pytest -m gateway -s

Exit 0 = all contracts hold; 1 = a contract failed. Assertions target tool
CONTRACTS (protocol success, envelope shape, non-empty/graceful answers),
never specific result content.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

GATEWAY = os.environ.get("KORTEX_SEARCH_GATEWAY_URL", "http://127.0.0.1:8765/mcp")

_SEARCH_KEYS = {"query", "results", "count", "sources", "elapsed_ms"}


def _token() -> str:
    path = os.path.expanduser("~/.config/kortex-search/gateway.env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("KORTEX_SEARCH_HTTP_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("KORTEX_SEARCH_HTTP_TOKEN", "")


async def _journey() -> list[tuple[str, float, str]]:
    results: list[tuple[str, float, str]] = []

    def ok(name: str, dt: float, note: str = "") -> None:
        results.append((name, dt, note))
        print(f"  ok  {name:<16} {dt:5.1f}s {note}")

    async with streamablehttp_client(
            GATEWAY,
            headers={"Authorization": f"Bearer {_token()}"}) as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        t0 = time.monotonic()
        tools = await s.list_tools()
        names = {t.name for t in tools.tools}
        assert "research_answer" in names and "warm" in names, names
        ok("initialize+tools", time.monotonic() - t0, f"{len(names)} tools")

        async def call(name: str, args: dict) -> tuple[dict, float]:
            t1 = time.monotonic()
            res = await s.call_tool(name, args)
            dt = time.monotonic() - t1
            text = res.content[0].text if res.content else ""
            try:
                return json.loads(text), dt
            except json.JSONDecodeError:
                return {"_raw": text}, dt

        d, dt = await call("doctor", {})
        assert d["redis"].get("ok") is True, d["redis"]
        ok("doctor", dt,
           f"models: rerank={d['rerank']['loaded']} embed={d['embed']['loaded']} "
           f"farm={list(d.get('farm', {}).get('browsers', {}))}")

        d, dt = await call("search_web", {"query": "rust async runtime",
                                          "limit": 5})
        assert set(d) >= _SEARCH_KEYS, d
        ok("search_web", dt, f"count={d['count']} cached={d.get('cached')}")

        d, dt = await call("search", {
            "query": "国产大模型 开源 生态",
            "sources": ["bilibili", "v2ex"], "limit": 5})
        assert set(d) >= _SEARCH_KEYS, d
        ok("search(CN)", dt, f"count={d['count']}")

        d, dt = await call("search_academic", {
            "query": "retrieval augmented generation", "limit": 5})
        assert set(d) >= _SEARCH_KEYS, d
        metas = [r.get("meta", {}) for r in d.get("results", [])]
        ok("search_academic", dt,
           f"count={d['count']} doi={sum(1 for m in metas if m.get('doi'))}")

        d, dt = await call("get_paper",
                           {"identifier": "10.48550/arxiv.2312.10997"})
        assert d.get("identifier"), d
        ok("get_paper", dt, f"kind={d.get('kind')}")

        d, dt = await call("research_answer", {
            "query": "state of mixture of experts models", "limit": 6})
        assert isinstance(d.get("answer"), str) and d["answer"].strip(), d
        assert isinstance(d.get("citations"), list)
        ok("research_answer", dt,
           f"answer={len(d['answer'])}ch citations={len(d['citations'])} "
           f"verify={d.get('verification', {}).get('status')}")

        d, dt = await call("read_url", {"url": "https://example.com/"})
        assert "url" in d and (d.get("content") or d.get("error")), d
        ok("read_url", dt, f"len={d.get('length')}")

        d, dt = await call("stats_report", {})
        assert "blocks" in d
        ok("stats_report", dt, f"tracked={len([k for k in d if k not in ('blocks', '_ledger')])}")

        d, dt = await call("saved_queries", {"action": "list"})
        assert isinstance(d.get("queries"), list), d
        ok("saved_queries", dt, f"{len(d['queries'])} saved")

        d, dt = await call("warm", {})
        assert "loaded" in d.get("rerank", {}) and "loaded" in d.get("embed", {}), d
        ok("warm", dt, f"rerank={d['rerank'].get('loaded')} embed={d['embed'].get('loaded')}")

    return results


def main() -> int:
    token = _token()
    if not token:
        print("error: KORTEX_SEARCH_HTTP_TOKEN not set (see gateway.env)",
              file=sys.stderr)
        return 1
    print(f"gateway journey → {GATEWAY}")
    try:
        results = asyncio.run(_journey())
    except AssertionError as exc:
        print(f"CONTRACT FAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"JOURNEY FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"all {len(results)} contracts hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
