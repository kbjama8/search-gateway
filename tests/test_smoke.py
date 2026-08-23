"""Regression guard for the search-gateway.

Asserts the package imports, all 18 sources register, and a smoke search
returns fused results. Run after any Phase 4 gateway change:

    PYTHONPATH=. pytest tests/ -q

Set the env flags below BEFORE import so the smoke search skips the model-heavy
re-rank / MMR / expansion path and stays fast + deterministic.
"""

import os

# Disable the slow/semantic paths for the smoke search (models load lazily and
# are not needed to prove the pipeline fuses results).
os.environ.setdefault("SEMANTIC_RERANK", "0")
os.environ.setdefault("SEARCH_GATEWAY_MMR", "0")
os.environ.setdefault("SEARCH_GATEWAY_QUERY_EXPANSION", "0")
os.environ.setdefault("SEARCH_GATEWAY_EMBEDDING_DEDUP", "0")

import asyncio

from search_gateway import orchestrator
from search_gateway.sources import ALL_SOURCES

EXPECTED_SOURCES = {
    "arxiv", "bilibili", "crossref", "exa", "facebook", "github",
    "instagram", "linkedin", "openalex", "reddit", "searxng",
    "semantic_scholar", "stackoverflow", "twitter", "v2ex", "web",
    "xiaohongshu", "youtube",
    # CN tier (v0.4, gated)
    "zhihu", "weibo", "baidu", "toutiao",
}


def test_package_imports():
    import search_gateway.cache
    import search_gateway.embeddings
    import search_gateway.llm
    import search_gateway.rerank
    import search_gateway.server
    import search_gateway.stats  # noqa: F401


def test_all_22_sources_registered():
    assert len(ALL_SOURCES) == 22, f"expected 22 sources, got {len(ALL_SOURCES)}"
    assert set(ALL_SOURCES) == EXPECTED_SOURCES


def test_smoke_search_returns_fused_results():
    async def _run():
        return await orchestrator.search(
            "transformer architecture", ["searxng"],
            category="general", limit=3, expand=False,
        )

    res = asyncio.run(_run())
    assert "results" in res
    assert isinstance(res["results"], list)
    assert res["count"] == len(res["results"])
    # every result is a dict with the Result contract's core fields
    for r in res["results"]:
        assert "title" in r and "url" in r and "source" in r
