# Configuration Reference

All 41 settings are environment variables with defaults — `config.py` is the
source of truth, and `.env.example` mirrors it (verified: the three cross-check
clean against each other). Copy `.env.example`, override what you need, and
never commit a secret (`.gitignore` blocks `*.env`).

One invariant, restated because it matters: **logs go to stderr — stdout is the
MCP stdio protocol wire.** `SEARCH_GATEWAY_LOG_FMT=json` emits one JSON object
per line to stderr for systemd/journald.

## Infrastructure

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARXNG_BASE` | `http://127.0.0.1:8888` | SearXNG metasearch endpoint (JSON API) |
| `SEARCH_GATEWAY_REDIS_URL` | `redis://127.0.0.1:6379/0` | cache + stats + rate-limit + saved queries |
| `GITHUB_TOKEN` | `""` | GitHub REST rate-limit boost (optional) |

## Search behaviour

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_MAILTO` | `kaichen.research@proton.me` | polite-pool email for OpenAlex/Crossref (not a key) |
| `SEARCH_GATEWAY_TIMEOUT` | `50` | global fan-out budget (seconds per search) |
| `SEARCH_GATEWAY_SOURCE_TIMEOUT` | `18` | per-source timeout (seconds) |

## Retry

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_RETRY_COUNT` | `1` | retries per source |
| `SEARCH_GATEWAY_RETRY_BACKOFF` | `1.5` | backoff multiplier (×2 per retry) |

## Rate limiting (cookie-logged sources)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_RATE_LIMIT` | `2.5` | min seconds between queries to cookie-logged sources |

## Fusion / re-rank / diversity

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | cross-encoder for re-rank |
| `SEARCH_GATEWAY_EMBED_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | bi-encoder (dedup/MMR) |
| `SEARCH_GATEWAY_EMBED_MODEL_CJK` | `BAAI/bge-m3` | multilingual bi-encoder for CJK-heavy runs (lazy) |
| `SEARCH_GATEWAY_CJK_SHARE_THRESHOLD` | `0.25` | CJK char share that triggers the multilingual model |
| `SEMANTIC_RERANK` | `1` | `0` = RRF-only |
| `SEARCH_GATEWAY_RERANK_CANDIDATES` | `30` | top-RRF candidates re-ranked |
| `SEARCH_GATEWAY_MMR` | `1` | diversity filter |
| `SEARCH_GATEWAY_MMR_LAMBDA` | `0.75` | relevance vs diversity trade-off |
| `SEARCH_GATEWAY_EMBEDDING_DEDUP` | `1` | embedding near-dup collapse |
| `SEARCH_GATEWAY_WEIGHTED_RRF` | `1` | reliability-weighted fusion |
| `SEARCH_GATEWAY_FRESHNESS` | `1` | freshness filter |

## Pinned model revisions

Empty string = unpinned. Pinned by default so Hugging Face commit-churn never
triggers a silent re-download (verified: models load from cache with the pinned
`revision=`).

| Variable | Default (sha) |
|----------|---------------|
| `SEARCH_GATEWAY_RERANK_REVISION` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| `SEARCH_GATEWAY_EMBED_REVISION` | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| `SEARCH_GATEWAY_EMBED_CJK_REVISION` | `5617a9f61b028005a4858fdac845db406aefb181` |

## Two-tier / opencli parallelism

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_TWO_TIER` | `1` | two-tier fan-out for slow sources |
| `SEARCH_GATEWAY_OPENCLI_PROFILES` | `1` | number of Chromium profiles (parallel opencli bridge) |

## Cache

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_CACHE_TTL` | `3600` | final-result TTL (seconds) |
| `SEARCH_GATEWAY_SOURCE_CACHE_TTL` | `900` | per-source TTL (seconds) |

## LLM / answer synthesis

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_QUERY_EXPANSION` | `1` | LLM query variants |
| `SEARCH_GATEWAY_LLM` | `1` | enable LLM features |
| `SEARCH_GATEWAY_LLM_MODEL` | `deepseek-v4-flash` | reasoning LLM |
| `SEARCH_GATEWAY_LLM_TIMEOUT` | `60` | LLM request timeout (seconds) |
| `DEEPSEEK_API_KEY` | `""` | DeepSeek key (also read from `DEEPSEEK_AUTH_FILE`) |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API base URL |

## Auth files (paths, not inline secrets)

| Variable | Default |
|----------|---------|
| `TWITTER_AUTH_FILE` | `~/.agent-reach/twitter-auth.env` |
| `DEEPSEEK_AUTH_FILE` | `~/.agent-reach/deepseek.env` |

## Observability / serving

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_LOG_FMT` | `text` | `text` \| `json` (JSON → stderr, one object/line) |
| `SEARCH_GATEWAY_LOG_LEVEL` | `INFO` | Python log level |
| `SEARCH_GATEWAY_HOST` | `127.0.0.1` | bind host for `serve --transport http/sse` |
| `SEARCH_GATEWAY_PORT` | `8765` | bind port for `serve --transport http/sse` |

## Ledger health

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_LEDGER_DIR` | `~/research_runs` | dir scanned by `doctor`/`stats_report` for run health |

> Logs always go to **stderr** — stdout is the MCP stdio protocol wire.
