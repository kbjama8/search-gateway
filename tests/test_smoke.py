"""Regression guard for the kortex-search.

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
os.environ.setdefault("KORTEX_SEARCH_MMR", "0")
os.environ.setdefault("KORTEX_SEARCH_QUERY_EXPANSION", "0")
os.environ.setdefault("KORTEX_SEARCH_EMBEDDING_DEDUP", "0")

import asyncio

from kortex_search import orchestrator
from kortex_search.sources import ALL_SOURCES

EXPECTED_SOURCES = {
    "arxiv", "bilibili", "crossref", "exa", "facebook", "github",
    "instagram", "linkedin", "openalex", "reddit", "searxng",
    "semantic_scholar", "stackoverflow", "twitter", "v2ex", "web",
    "xiaohongshu", "youtube",
    # v0.7 additions (2026-09-01)
    "hackernews", "wikipedia",
    # CN tier (v0.4, gated)
    "zhihu", "zhihu_hot", "weibo", "baidu", "toutiao",
}


def test_package_imports():
    import kortex_search.cache
    import kortex_search.embeddings
    import kortex_search.llm
    import kortex_search.rerank
    import kortex_search.server
    import kortex_search.stats  # noqa: F401


def test_all_25_sources_registered():
    assert len(ALL_SOURCES) == 25, f"expected 25 sources, got {len(ALL_SOURCES)}"
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
