"""Fresh-agent journey smoke — the full MCP tool surface driven like a
research agent over stdio (expanded from the live gateway smoke, sweep
2026-09-04; the live script lives in scripts/smoke_gateway.py).

Design: ONE session per journey, tools called sequentially (a real agent's
flow), assertions on TOOL CONTRACTS — protocol success, envelope shape,
non-empty/graceful answers — never on specific result content, so the
journey stays meaningful in CI without network guarantees.

Regression guards this journey pins (both found by the original live
smoke, both now fixed):
  * research_answer must NEVER return an empty answer string — deepseek-v4
    reasoning can starve the json_mode budget; the tool retries with
    thinking disabled and degrades with an explicit message;
  * every tool must return its documented envelope keys even when the
    backends are missing/down (honest degradation, no protocol errors).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "doctor", "get_citations", "get_paper", "get_references", "read_url",
    "research_answer", "saved_queries", "search", "search_academic",
    "search_news", "search_science", "search_social", "search_web",
    "stats_report", "warm",
}

_SEARCH_KEYS = {"query", "results", "count", "sources", "elapsed_ms"}


async def _run_journey(calls: list[tuple[str, dict, callable]]):
    """One stdio session; runs each (tool, arguments, assert_fn) in order
    and returns the list of (tool, payload, elapsed_s)."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "kortex_search.cli", "serve"],
    )
    out = []
    async with (stdio_client(params) as (read, write),
                ClientSession(read, write) as session):
        await session.initialize()
        tools = await session.list_tools()
        assert {t.name for t in tools.tools} == EXPECTED_TOOLS, (
            "tool surface changed — update EXPECTED_TOOLS")
        for tool, arguments, assert_fn in calls:
            t0 = time.monotonic()
            res = await session.call_tool(tool, arguments)
            dt = time.monotonic() - t0
            text = ""
            for c in res.content:
                if c.type == "text":
                    text = c.text
                    break
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {"_raw": text}
            assert_fn(payload)
            out.append((tool, payload, dt))
    return out


def _assert_search_envelope(d: dict) -> None:
    assert isinstance(d, dict), type(d)
    assert set(d) >= _SEARCH_KEYS, f"missing keys: {_SEARCH_KEYS - set(d)}"
    assert isinstance(d["results"], list)
    assert isinstance(d["count"], int)
    assert isinstance(d["sources"], dict)
    if d["results"]:  # results present → standardized fields per result
        r = d["results"][0]
        assert isinstance(r.get("title"), str) and isinstance(r.get("url"), str)


def assert_kind(d: dict) -> None:
    assert isinstance(d, dict) and d.get("identifier"), f"get_paper: {d!r}"
    assert d.get("kind") in ("arxiv", "doi", "other")


def test_journey_full_tool_surface():
    """The complete research-agent flow, one session, in order."""

    def _doctor(d):
        assert {"redis", "rerank", "embed", "llm", "sources", "academic",
                "ledger", "egress", "vault", "blocks", "profiles",
                "farm"} <= set(d), set(d)
        assert isinstance(d["redis"].get("ok"), bool)
        assert isinstance(d["rerank"].get("loaded"), bool)
        assert isinstance(d["embed"].get("loaded"), bool)
        assert isinstance(d["farm"], dict)

    def _research_answer(d):
        # the empty-answer regression guard (smoke discovery 2026-09-04)
        assert isinstance(d.get("answer"), str) and d["answer"].strip(), (
            f"research_answer returned an empty answer: {d!r}")
        assert isinstance(d.get("citations"), list)
        assert isinstance(d.get("results"), list)
        assert "verification" in d or "sources" in d

    def _read_url(d):
        assert isinstance(d, dict) and "url" in d
        ok = isinstance(d.get("content"), str) and d["content"].strip()
        assert ok or d.get("error"), f"read_url gave neither content nor error: {d!r}"

    def _stats(d):
        assert isinstance(d, dict) and "blocks" in d

    def _saved(d):
        assert isinstance(d.get("queries"), list)

    def _warm(d):
        assert isinstance(d.get("rerank"), dict) and "loaded" in d["rerank"]
        assert isinstance(d.get("embed"), dict) and "loaded" in d["embed"]

    results = asyncio.run(_run_journey([
        ("doctor", {}, _doctor),
        ("search_web", {"query": "rust async runtime", "limit": 4},
         _assert_search_envelope),
        ("search", {"query": "开源大模型 生态", "sources": ["bilibili", "v2ex"],
                    "limit": 4}, _assert_search_envelope),
        ("search_academic", {"query": "retrieval augmented generation",
                             "limit": 4}, _assert_search_envelope),
        ("get_paper", {"identifier": "10.48550/arxiv.2312.10997"},
         assert_kind),
        ("research_answer", {"query": "state of mixture of experts models",
                             "limit": 4}, _research_answer),
        ("read_url", {"url": "https://example.com/"}, _read_url),
        ("stats_report", {}, _stats),
        ("saved_queries", {"action": "list"}, _saved),
        ("warm", {}, _warm),
    ]))
    names = [r[0] for r in results]
    assert names == ["doctor", "search_web", "search", "search_academic",
                     "get_paper", "research_answer", "read_url",
                     "stats_report", "saved_queries", "warm"], names


@pytest.mark.slow
def test_journey_social_ladder_degrades_honestly():
    """reddit/twitter searches must return an envelope with per-source
    status strings (errors/timeouts surfaced, never a protocol crash) —
    the browser tier is externally constrained on this host."""
    def _social(d):
        assert set(d) >= _SEARCH_KEYS, d
        assert isinstance(d["results"], list)
        statuses = d.get("sources") or {}
        assert statuses, f"social search must report source statuses: {d!r}"
        for s in statuses.values():
            assert isinstance(s, str) and s, f"empty status: {statuses!r}"

    results = asyncio.run(_run_journey([
        ("search", {"query": "rust async", "sources": ["reddit"], "limit": 4},
         _social),
        ("search", {"query": "rust async", "sources": ["twitter"], "limit": 4},
         _social),
    ]))
    assert [r[0] for r in results] == ["search", "search"]


@pytest.mark.gateway
def test_live_gateway_journey():
    """Run scripts/smoke_gateway.py against the live HTTP gateway.

    Gated: KORTEX_SEARCH_SMOKE_GATEWAY=1 enables it (needs the systemd
    gateway up + the token exported)."""
    import os
    import subprocess

    if os.environ.get("KORTEX_SEARCH_SMOKE_GATEWAY") != "1":
        pytest.skip("set KORTEX_SEARCH_SMOKE_GATEWAY=1 to run the live "
                    "gateway smoke")
    script = "scripts/smoke_gateway.py"
    proc = subprocess.run([sys.executable, script], capture_output=True,
                          text=True, timeout=900)
    assert proc.returncode == 0, f"gateway smoke failed:\n{proc.stdout}\n{proc.stderr}"
