"""Golden contract: 25 sources + 14 tools + Result surface unchanged.

Any change to a tool name, the source registry, or the `Result` shape is a
SemVer-major event (see docs/api/tools.md + docs/meta-schema.md). These tests
fail loudly to catch that. The CN tier (zhihu/weibo/baidu/toutiao) is
registered but gated by KORTEX_SEARCH_CN_SOURCES — presence in the registry
is the contract; availability is runtime state.
"""

import asyncio

from kortex_search.models import Result
from kortex_search.server import mcp
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

EXPECTED_TOOLS = {
    "doctor", "get_citations", "get_paper", "get_references", "read_url",
    "research_answer", "saved_queries", "search", "search_academic",
    "search_news", "search_science", "search_social", "search_web",
    "stats_report",
}

# Standardized optional meta keys (docs/meta-schema.md).
EXPECTED_META_KEYS = {
    "source_type", "doi", "arxiv_id", "pmid", "paper_id", "authors", "year",
    "venue", "publisher", "citation_count", "is_oa", "pdf_url", "abstract",
    "score_raw", "engagement", "accepted", "answer_count", "question_id",
    "tags", "is_answered", "_also_found_by",
}


def test_25_sources_registered():
    assert len(ALL_SOURCES) == 25
    assert set(ALL_SOURCES) == EXPECTED_SOURCES


def test_14_tools():
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == EXPECTED_TOOLS


def test_result_top_level_fields():
    r = Result(title="t", url="https://example.com/", snippet="s", source="arxiv")
    d = r.to_dict()
    assert d["title"] == "t"
    assert d["url"] == "https://example.com/"
    assert d["source"] == "arxiv"
    assert isinstance(d["meta"], dict)
    # identity: canonical URL (trailing slash stripped), title fallback
    assert r.identity() == "https://example.com"
    assert Result(title="T", url="").identity() == "t"


def test_result_meta_accepts_standardized_keys():
    r = Result(title="t", url="u")
    r.meta.update(dict.fromkeys(EXPECTED_META_KEYS))
    assert set(r.meta) >= EXPECTED_META_KEYS
