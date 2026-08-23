# Configuration Reference

All 70 settings are environment variables with defaults — `config.py` is the
source of truth, and `.env.example` mirrors it (verified: the three cross-check
clean against each other). Copy `.env.example`, override what you need, and
never commit a secret (`.gitignore` blocks `*.env`).

One invariant, restated because it matters: **logs go to stderr — stdout is the
MCP stdio protocol wire.** `SEARCH_GATEWAY_LOG_FMT=json` emits one JSON object
per line to stderr for systemd/journald.

## Override precedence

For every setting, resolution happens in this order, highest wins:

```mermaid
flowchart LR
    A["1. environment variable (set at process launch)"] -.->|"wins if set"| D["effective value"]
    B["2. auth-file fallback (DEEPSEEK_API_KEY only)"] -.->|"wins if A unset"| D
    C["3. hardcoded default (config.py)"] -.->|"wins if A and B unset"| D
```

Almost every variable is `env var > default` — two levels, checked by
`_env`/`_env_bool`/`_env_int`/`_env_float` in `config.py`. Exactly one setting
has a third level: `DEEPSEEK_API_KEY`. `llm.get_api_key()` reads the env var
first and, only if that's empty, falls back to `load_env_file(DEEPSEEK_AUTH_FILE,
...)` — so a value exported in the shell always overrides whatever sits in
`~/.agent-reach/deepseek.env`. `TWITTER_AUTH_FILE` is different: it only sets
*where* Twitter reads its tokens from — the tokens themselves
(`TWITTER_AUTH_TOKEN` / `TWITTER_CT0`) come from that file and have no env-var
override. Every other variable — `SEARXNG_BASE`, all the fusion/rerank knobs,
the cache TTLs — has no file-based fallback; if the env var isn't set, you get
the hardcoded default, full stop.

## Rationale by group + tier mapping

Each group below exists to solve one operational problem, and each maps to a
point in the capability-tier ladder from `docs/deployment.md` — most vars
matter starting at a specific tier, not from `minimal` onward.

| Group | Solves | Matters starting at tier |
|-------|--------|---------------------------|
| Infrastructure | Where Redis/SearXNG live; GitHub rate-limit relief | **minimal** |
| Search behaviour | Fan-out budget and the polite-pool contact email | **minimal** |
| Retry | Distinguishing a transient failure from a permanent one | **minimal** |
| Rate limiting | Protecting cookie-authenticated accounts from bans | **social/vertical** |
| Fusion / re-rank / diversity | Turning 18 raw result lists into one ranked, deduped, diverse list | **web+neural** (rerank/embed models apply to any multi-source fan-out) |
| Pinned model revisions | Stopping silent re-downloads when a model repo's HEAD moves | **web+neural** |
| Two-tier / opencli parallelism | Isolating slow, browser-backed sources from the fast default fan-out | **social/vertical** |
| Cache | Bounding repeat-query cost and staleness | **minimal** |
| LLM / answer synthesis | `research_answer` + query expansion | **answer synthesis** |
| Auth files | Keeping tokens out of shell history and process listings | **social/vertical**, **answer synthesis** |
| Observability / serving | Log format/level; HTTP bind address for a host-process deployment | **minimal** (logging), **any tier running `--transport http/sse`** (host/port) |
| Ledger health | Read-only visibility into `deep-research` skill run health | optional, any tier |
| Extraction tiering (v0.4) | Browser budget, jittered pacing, per-profile health | **social/vertical** |
| Block intelligence (v0.4) | Detecting challenge walls instead of burning retries on them | **social/vertical** |
| Proxy subsystem (v0.4) | Optional residential/ISP egress with geo-coherent fingerprints | only when funded (see `docs/extraction/proxy-funding-guide.md`) |
| Stealth / impersonation (v0.4) | Camoufox anonymous tier + curl_cffi TLS impersonation | experimental, opt-in |
| Read_url stages (v0.4) | Jina → Trafilatura → readability extraction pipeline | **minimal** |
| CN tier (v0.4) | zhihu/weibo/baidu/toutiao + bilibili wbi signing | opt-in (`SEARCH_GATEWAY_CN_SOURCES=1`) |

## Infrastructure

*Where the gateway's two hard service dependencies live, plus an optional
GitHub token.*

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARXNG_BASE` | `http://127.0.0.1:8888` | SearXNG metasearch endpoint (JSON API) |
| `SEARCH_GATEWAY_REDIS_URL` | `redis://127.0.0.1:6379/0` | cache + stats + rate-limit + saved queries |
| `GITHUB_TOKEN` | `""` | GitHub REST rate-limit boost (optional) |

## Search behaviour

*The fan-out budget and the one non-secret "identity" var — a courtesy email
some academic APIs ask for, not an API key.*

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_MAILTO` | `kaichen.research@proton.me` | polite-pool email for OpenAlex/Crossref (not a key) |
| `SEARCH_GATEWAY_TIMEOUT` | `50` | global fan-out budget (seconds per search) |
| `SEARCH_GATEWAY_SOURCE_TIMEOUT` | `18` | per-source timeout (seconds) |

`SEARCH_GATEWAY_TIMEOUT=50` bounds the whole fan-out in seconds (`config.py`).
Lower it when sources hang; raise it for slow verticals.

## Retry

*How many times, and how long to wait, before giving up on one source for one
query — scoped to transient failures only.*

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_RETRY_COUNT` | `1` | retries per source |
| `SEARCH_GATEWAY_RETRY_BACKOFF` | `1.5` | backoff multiplier (×2 per retry) |

Retries apply only to `RETRYABLE_EXIT_CODES = (1, 8, 52, 56)` — curl-style
transient codes. An auth failure or a 404 is not retried; retrying a
permanent failure just burns the fan-out budget.

## Rate limiting (cookie-logged sources)

*A floor on request frequency to the four cookie-authenticated sources, so
burst traffic doesn't read as bot behavior to the platform.*

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_RATE_LIMIT` | `2.5` | min seconds between queries to cookie-logged sources |

Applies to `RATE_LIMITED_SOURCES = {twitter, reddit, facebook, instagram}`
specifically — the four other social/video sources (xiaohongshu, linkedin,
youtube, bilibili) authenticate differently and aren't gated by this variable.

## Fusion / re-rank / diversity

*The knobs that turn 18 raw ranked lists into one fused, deduped, re-ranked,
diverse list.*

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | cross-encoder for re-rank |
| `SEARCH_GATEWAY_EMBED_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | bi-encoder (dedup/MMR) |
| `SEARCH_GATEWAY_EMBED_MODEL_CJK` | `BAAI/bge-m3` | multilingual bi-encoder for CJK-heavy runs (lazy) |
| `SEARCH_GATEWAY_EMBED_CJK` | `1` | enable/disable the CJK-dominant detection + multilingual model switch |
| `SEARCH_GATEWAY_CJK_SHARE_THRESHOLD` | `0.25` | CJK char share that triggers the multilingual model |
| `SEMANTIC_RERANK` | `1` | `0` = RRF-only |
| `SEARCH_GATEWAY_RERANK_CANDIDATES` | `30` | top-RRF candidates re-ranked |
| `SEARCH_GATEWAY_MMR` | `1` | diversity filter |
| `SEARCH_GATEWAY_MMR_LAMBDA` | `0.75` | relevance vs diversity trade-off |
| `SEARCH_GATEWAY_EMBEDDING_DEDUP` | `1` | embedding near-dup collapse |
| `SEARCH_GATEWAY_WEIGHTED_RRF` | `1` | reliability-weighted fusion |
| `SEARCH_GATEWAY_FRESHNESS` | `1` | freshness filter |

`SEARCH_GATEWAY_MMR_LAMBDA=0.75` weighs relevance 75% against diversity 25% in
the greedy MMR selection (`diversity.py`) — raise it toward `1.0` if results
feel too scattered across unrelated domains, lower it if the top-k feels like
five copies of the same article.
`SEARCH_GATEWAY_EMBED_CJK` is the master switch: with it off, `cjk_dominant()`
always returns `False` and the multilingual model never loads, regardless of
how much Chinese/Japanese/Korean text is in the fused set.

## Pinned model revisions

Empty string = unpinned. Pinned by default so Hugging Face commit-churn never
triggers a silent re-download (verified: models load from cache with the pinned
`revision=`).

| Variable | Default (sha) |
|----------|---------------|
| `SEARCH_GATEWAY_RERANK_REVISION` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| `SEARCH_GATEWAY_EMBED_REVISION` | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| `SEARCH_GATEWAY_EMBED_CJK_REVISION` | `5617a9f61b028005a4858fdac845db406aefb181` |

`docs/adrs/0005-pinned-model-revisions.md` has the incident this fixed.

## Inference backend

*The cross-encoder runs on ONNX Runtime by default — ~2× faster re-rank and a
smaller memory footprint than torch, at essentially equal ranking quality
(Spearman ≈ 0.96). `optimum` + `onnxruntime` are core dependencies.*

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_INFERENCE_BACKEND` | `onnx_int8` | `onnx_int8` (dynamic-quantized) \| `onnx` (fp32) \| `torch` |
| `SEARCH_GATEWAY_RERANK_ONNX_MODEL` | `onnx-community/bge-reranker-v2-m3-ONNX` | pre-exported ONNX cross-encoder |
| `SEARCH_GATEWAY_RERANK_ONNX_REVISION` | `6f5ff65…` | pinned revision of the ONNX model |

`onnx` selects `model.onnx` (fp32); `onnx_int8` selects `model_int8.onnx`.
Set `SEARCH_GATEWAY_INFERENCE_BACKEND=torch` to use the original
`BAAI/bge-reranker-v2-m3` weights via `sentence-transformers`. If the ONNX
model can't load (not yet cached, offline), the reranker falls back to torch
automatically rather than silently dropping re-rank.

## Two-tier / opencli parallelism

*Isolating the slow, browser-backed sources so they don't block the fast
default fan-out.*

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_TWO_TIER` | `1` | two-tier fan-out for slow sources |
| `SEARCH_GATEWAY_OPENCLI_PROFILES` | `1` | number of Chromium profiles (parallel opencli bridge) |

## Cache

*How long a result is trusted before the gateway re-fetches it.*

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_CACHE_TTL` | `3600` | final-result TTL (seconds) |
| `SEARCH_GATEWAY_SOURCE_CACHE_TTL` | `900` | per-source TTL (seconds) |

The final-result TTL outlives the per-source TTL by 4×: a per-source result
is reusable across many different fused queries, so it refreshes more often;
the expensive fused-and-reranked output is worth holding onto longer.

## LLM / answer synthesis

*Everything `research_answer` and query expansion need — and nothing else
needs.*

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_QUERY_EXPANSION` | `1` | LLM query variants |
| `SEARCH_GATEWAY_LLM` | `1` | enable LLM features |
| `SEARCH_GATEWAY_LLM_MODEL` | `deepseek-v4-flash` | reasoning LLM |
| `SEARCH_GATEWAY_LLM_TIMEOUT` | `60` | LLM request timeout (seconds) |
| `DEEPSEEK_API_KEY` | `""` | DeepSeek key (also read from `DEEPSEEK_AUTH_FILE`) |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API base URL |

Every other tool works with none of these set. `search`, `search_web`,
`search_academic`, and the rest never touch DeepSeek; only `research_answer`'s
synthesis step and the optional query-expansion pass inside `orchestrator.py`
do (`docs/faq.md`).

## Auth files (paths, not inline secrets)

| Variable | Default |
|----------|---------|
| `TWITTER_AUTH_FILE` | `~/.agent-reach/twitter-auth.env` |
| `DEEPSEEK_AUTH_FILE` | `~/.agent-reach/deepseek.env` |

These are *paths* to files containing `KEY=VALUE` secrets, parsed by
`load_env_file()` (export-aware, quote-stripped) — not secrets themselves.
Env var still wins if both are set (see override precedence above).

## Observability / serving

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_LOG_FMT` | `text` | `text` \| `json` (JSON → stderr, one object/line) |
| `SEARCH_GATEWAY_LOG_LEVEL` | `INFO` | Python log level |
| `SEARCH_GATEWAY_HOST` | `127.0.0.1` | bind host for `serve --transport http/sse` |
| `SEARCH_GATEWAY_PORT` | `8765` | bind port for `serve --transport http/sse` |

`SEARCH_GATEWAY_HOST`/`_PORT` are read only when `--transport http` or
`--transport sse` is passed to `serve` — the stdio default (no flag) ignores
both.

## Ledger health

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_LEDGER_DIR` | `~/research_runs` | dir scanned by `doctor`/`stats_report` for run health |

Read-only: `stats.ledger_health()` walks this directory for `ledger.json`
files and never writes to it. A missing directory or a malformed
`ledger.json` is skipped, not raised.

> Logs always go to **stderr** — stdout is the MCP stdio protocol wire.

---

## v0.4 extraction layer (Project Gatekeeper)

*Everything the extraction overhaul added. Risky capabilities ship disabled;
the gateway's behavior is unchanged when the flags below sit at their
defaults. Full rationale: `docs/extraction/PLAN.md`.*

### Browser budget & pacing

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_BROWSER_BUDGET` | `1` | concurrent browser ops (1 = old single-bridge behavior; raise per profile farm) |
| `SEARCH_GATEWAY_RATE_LIMIT_JITTER` | `0.3` | ± fraction of the inter-query interval — fixed intervals are a fingerprint |
| `SEARCH_GATEWAY_PROFILE_DIR` | `~/.agent-reach/profiles` | JSON profile definitions for the browser farm |
| `SEARCH_GATEWAY_PROFILE_HEALTH_TTL` | `3600` | base cooldown TTL for profile health transitions (seconds) |

### Block & challenge intelligence

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_BLOCK_DETECTION` | `1` | classify CLI/HTTP outputs for challenge markers; blocked → fail immediately, never retry |
| `SEARCH_GATEWAY_PLATFORM_BLOCK_LIMIT` | `3` | failures before a profile enters cooldown; N cooldown cycles → quarantine |
| `SEARCH_GATEWAY_PLATFORM_COOLDOWN_TTL` | `900` | per-platform circuit-breaker pause (seconds) |

### Stealth & impersonation (experimental, default OFF)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_STEALTH` | `0` | enable the Camoufox anonymous tier (`docs/extraction/camoufox-migration.md`) |
| `SEARCH_GATEWAY_STEALTH_PROFILE` | `""` | pinned Camoufox fingerprint preset (empty = random browserforge) |
| `SEARCH_GATEWAY_IMPERSONATE` | `0` | curl_cffi TLS/JA3 impersonation for bilibili/zhihu/weibo HTTP |

### Proxy subsystem (default OFF)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_PROXY_ENABLED` | `0` | master switch (`docs/extraction/proxy-funding-guide.md`) |
| `SEARCH_GATEWAY_PROXY_PROTOCOL` | `http` | `http` \| `socks5` |
| `SEARCH_GATEWAY_PROXY_GATEWAY` | `""` | provider gateway `host:port` |
| `SEARCH_GATEWAY_PROXY_USERNAME` | `""` | targeting-grammar username (verbatim wins; else auto-built `country-sid-ttl`) |
| `SEARCH_GATEWAY_PROXY_PASSWORD` | `""` | provider password |
| `SEARCH_GATEWAY_PROXY_AUTH_FILE` | `~/.agent-reach/proxy.env` | 0600 file for the three credentials above |
| `SEARCH_GATEWAY_PROXY_COUNTRY` | `""` | persona egress country (ISO) |
| `SEARCH_GATEWAY_PROXY_STICKY_TTL` | `30m` | sticky-session lifetime per profile |
| `SEARCH_GATEWAY_PROXY_GEO_ALIGN` | `1` | derive TZ/locale/languages from egress geo into the fingerprint bundle |

### read_url stages

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_READ_URL_STAGES` | `jina,trafilatura,readability` | stage order; first to return ≥50 chars wins |
| `SEARCH_GATEWAY_TRAFILATURA_MIN_LEN` | `300` | minimum usable length for the trafilatura stage |
| `SEARCH_GATEWAY_LLM_PARSE` | `0` | gated LLM-assisted extraction for degenerate parse shapes (validated) |

### CN tier (opt-in)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_GATEWAY_CN_SOURCES` | `0` | register-visible zhihu/weibo/baidu/toutiao become queryable |
| `ZHIHU_COOKIE` | `""` | `d_c0` + `z_c0` from a browser session (zhihu blocks anonymous, 401) |
| `WEIBO_SUB` | `""` | logged-in `SUB` cookie (weibo keyword search; hot list works without) |
| `SEARCH_GATEWAY_BILIBILI_WBI` | `1` | wbi signing for bilibili (always on; keys Redis-cached) |
| `SEARCH_GATEWAY_BILIBILI_WBI_KEY_TTL` | `82800` | wbi key cache TTL (23h — keys rotate daily) |
| `SEARCH_GATEWAY_YOUTUBE_PO_PLUGIN` | `""` | yt-dlp PO-token provider plugin (e.g. `bgutil-ytdlp-pot-provider`) |
| `SEARCH_GATEWAY_YOUTUBE_PO_SERVER` | `http://127.0.0.1:4416` | PO-token HTTP server URL when a provider plugin needs one |