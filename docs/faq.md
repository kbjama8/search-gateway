# FAQ

## Why 25 sources instead of one search engine?

Because one engine has one blind spot, consistently. Bing/Google-style
metasearch (via SearXNG) covers general web queries well and academic
literature barely at all; a single engine has no concept of a GitHub repo's
stars or a Stack Overflow answer's accepted status. `kortex-search` fuses
25 sources spanning web, code, video, social, forum, academic, encyclopedic (wikipedia), and (opt-in) Chinese-ecosystem verticals (zhihu, zhihu_hot, weibo, baidu, toutiao)
precisely so that one `search()` call doesn't inherit one engine's coverage
gaps. `README.md`'s "Why a gateway and not one search API" framing and its
source table lay out the full list.

## How big are the models, and when do they download?

| Model | Size (approx.) | Loads when |
|-------|------------------|------------|
| `BAAI/bge-reranker-v2-m3` (cross-encoder) | ~568M parameters | First `search` call with `SEMANTIC_RERANK=1` and more fused results than `limit` — or explicitly via `kortex-search warm`. |
| `sentence-transformers/all-MiniLM-L6-v2` (bi-encoder) | small (~90 MB) | First `search` call needing dedup/MMR embeddings on English-dominant text. |
| `BAAI/bge-m3` (multilingual bi-encoder) | ~2.3 GB | Only when `embeddings.cjk_dominant()` finds the fused result set's CJK character share ≥ `KORTEX_SEARCH_CJK_SHARE_THRESHOLD` (default `0.25`) — never loads for English-only usage. |

All three are lazy singletons — loaded once per process, not per query
(`rerank.py`, `embeddings.py`). `kortex-search warm` forces the load ahead
of time so the first live query doesn't pay for it.

## When does the CJK model actually kick in?

`embeddings.cjk_dominant()` counts CJK-range characters (Han ideographs,
hiragana/katakana, hangul) across the fused result set's titles and
snippets. If that combined share is at or above the threshold (25% by
default), dedup and MMR switch to the `bge-m3` multilingual bi-encoder for
that request; otherwise they use the fast MiniLM default. This is
per-request, not global — an English query stays on MiniLM even if `bge-m3`
loaded earlier in the process for a different, CJK-heavy query; once loaded,
though, the model stays resident for the life of the process.

## How do I add a new source?

Four steps, detailed in `docs/architecture.md#source-adapter-contract`:
subclass `Source` in `sources/<name>.py` and implement `search()`; emit
`Result` objects with `meta` keys per `docs/meta-schema.md`; register the
instance in `ALL_SOURCES` (`sources/__init__.py`); update
`tests/test_contract.py`'s expected source count. Fusion, dedup, rerank, and
MMR are all written against the `Result` contract, not against any
individual source, so nothing else needs to change.

## stdio or HTTP — which should I use?

stdio if your MCP client spawns the server itself (most desktop
IDEs/CLIs) — it's the default and needs no additional setup. HTTP/SSE if you
want one long-running process serving multiple clients or sessions without
re-paying cold-model-load latency per spawn — that's the systemd path in
`docs/deployment.md`. `docs/mcp-registration.md#stdio-vs-http-tradeoff` has
the full comparison; both transports expose the identical 14-tool surface.

## Why isn't this on PyPI?

It isn't published there today — install is `pip install .` from a clone,
per the Quick Start in `README.md`. Nothing in the packaging
(`pyproject.toml` is a standard `setuptools` project with `dynamic` version
and a `project.scripts` console entry) blocks a future PyPI release; it
simply hasn't happened yet. Treat this as **not yet validated** rather than
a permanent design decision.

## Do I need a DeepSeek API key?

No — search itself never touches it. `DEEPSEEK_API_KEY` (or the
`DEEPSEEK_AUTH_FILE` fallback) is read only by two features:
`research_answer`'s answer synthesis, and the optional LLM query-expansion
pass inside `orchestrator.search()` (`KORTEX_SEARCH_QUERY_EXPANSION`,
default on but silently a no-op without a key —
`orchestrator._expand_query()` checks `llm.available()` first and returns an
empty list if it's false). Every other tool — `search`, `search_web`,
`search_academic`, `get_paper`, `doctor`, `saved_queries`, and the rest —
works fully without it. `kortex-search check`'s exit code doesn't depend on
`llm.available()` either; it's recorded, never a failure condition
(`health.check()`).