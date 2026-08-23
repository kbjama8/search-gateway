# Project Map

A complete navigational map of this repository: where every piece lives, what
it owns, and how the pieces connect. Reference register: facts are anchored to
the file that defines them; nothing here claims to be verified unless it was
demonstrated (see [Verification status](#verification-status)).

Use this document as the first stop before reading code — it names the file,
the entry point, and the surrounding contract for each subsystem, so the code
read is confirmation rather than discovery.

## Contents

- [Vision & goals](#vision--goals)
- [Repo layout](#repo-layout)
- [The pipeline](#the-pipeline)
- [Module map](#module-map)
- [Source adapters](#source-adapters)
- [MCP tool surface](#mcp-tool-surface)
- [Reliability model](#reliability-model)
- [Configuration surface](#configuration-surface)
- [Tests & CI](#tests--ci)
- [Infra](#infra)
- [Orchestration skills](#orchestration-skills)
- [Scripts](#scripts)
- [ADRs](#adrs)
- [Verification status](#verification-status)

## Vision & goals

The gateway is not a search API with more backends. It is a refusal: the
world arrives in eighteen unshaped forms — Reddit posts, arXiv abstracts,
bilibili clips, Stack Overflow answers — and the refusal is to hand that
fragmentation to the client. "The problem it kills is fragmentation"
(`README.md:14`): one `search()` in, one `Result` out, and any client,
past or future, gets the whole fused web for the price of a handshake.

Three stances carry that refusal, and they are the project's goals made
architectural.

**Honesty is reliability.** A source that times out is absent — and the
envelope says so: `"partial": true, "pending": ["youtube"]`
(`README.md:260`). A claim that has not been demonstrated is `expected` or
`not yet validated`, never `verified` (`docs/voice.md:19-24`). A ledger
with zero contradictions is a red flag, not a success — the red-team pass
is mandatory, not optional (`skills/deep-research/SKILL.md:127-133`). The
system would rather name its failure than look like it succeeded:
`research_answer` refuses to guess when the sources are empty
(`server.py:307-309`).

**Autonomy is architecture.** No client is the source of truth — the
conformance check is the protocol handshake, so the server never knows any
client exists (`docs/adrs/0001-stdio-first.md`). Zero paid APIs: the
backbone owes no vendor (`docs/history/tasks/todo.md:36`). Upstream drift
is a decision, not an accident — model weights are pinned to commit SHAs so
nothing changes on this machine unless the operator changes it
(`config.py:67-75`, ADR 0005). The burner persona never touches the
personal accounts; secrets never enter the repo (`ratelimit.py:3-4`,
`.gitignore`).

**Degradation is designed, not accidental.** Every stage after the fan-out
fails toward its input: a missing model skips its stage, Redis losing
connectivity costs only the cache, and the failure is named in the
envelope. Control here does not mean preventing failure; it means making
it legible, bounded, and survivable (`orchestrator.py`, `cache.py`).

The voice of the whole corpus — short, cited, honest, decisive — is the
same register as the gateway's own synthesis output. That is deliberate:
the documentation is written for the people after the author, agents
included, and the claim discipline (every load-bearing sentence anchored
to a file or a test) is what makes it verifiable long after the context
that produced it is gone.

### Goals

| Horizon | Goal | Where it shows |
|---------|------|----------------|
| short | a stable, verifiable retrieval backbone for the research skills | 135-test fast suite, golden contract (`tests/test_contract.py`) |
| short | deterministic behaviour on this machine: pinned revisions, adaptive timeouts, negative caching | `config.py`, ADR 0005 |
| medium | a bounded extension path — source #23 is a four-step change, nothing else moves | `docs/architecture.md#source-adapter-contract` |
| medium | long-running host deployments: HTTP/SSE transports, systemd, headless image | `server.py`, `infra/` |
| long | a client-agnostic research substrate that outlives any single tool — evidence memory across runs, recurring monitors, docs written for future readers | `skills/deep-research` memory-*, `skills/monitor`, `docs/voice.md` |

### The code of practice

Ten principles the artifacts demonstrate, each enforced somewhere
concrete — the project's ethics as implemented, not aspirational:

| Principle | Enforced in |
|-----------|-------------|
| One contract against fragmentation | `models.py` `Result`; `tests/test_contract.py` |
| Degrade explicitly, never silently | `orchestrator.py` envelope (`sources`, `partial`, `pending`) |
| No client is the source of truth | `docs/adrs/0001-stdio-first.md` |
| Verified, or not yet validated — never hopeful | `docs/voice.md`; `docs/faq.md` |
| Zero paid keys; the backbone owes no vendor | `docs/history/tasks/todo.md:36`; free sources only |
| Upstream drift is a decision, not an accident | ADR 0005; `config.py` `*_REVISION` |
| An unsearched contradiction is a red flag | `skills/deep-research/SKILL.md` red-team pass |
| The burner never touches your accounts | `ratelimit.py`; auth files under `~/.agent-reach/` |
| Gaps are findings, not omissions | `docs/voice.md:22`; `research_answer` refusal to guess |
| Trust is measured hourly and can be lost | `fusion.py` weighted RRF over `stats.reliability` |

## Repo layout

```
search-gateway/
├── search_gateway/            # core package (~3,100 LOC, 17 modules)
│   ├── server.py              # FastMCP app: 14 tools + Bearer auth + main()
│   ├── orchestrator.py        # the pipeline: fan-out → fuse → dedup → rerank → MMR
│   ├── cli.py                 # console entry: serve|doctor|check|version|warm
│   ├── health.py              # doctor report() + strict check() gate
│   ├── models.py              # Result dataclass — the universal contract
│   ├── config.py              # 41 env-overridable settings + fallback-chain matrix
│   ├── fusion.py              # weighted RRF
│   ├── dedup.py               # canonical URL + title + embedding-cosine dedup
│   ├── diversity.py           # MMR, per-category λ
│   ├── rerank.py              # lazy bge-reranker-v2-m3 (ONNX default, torch fallback)
│   ├── embeddings.py          # MiniLM bi-encoder + lazy bge-m3 for CJK runs
│   ├── llm.py                 # DeepSeek client (OpenAI-compatible)
│   ├── cache.py               # Redis: per-source 15m / final 1h / negative cache
│   ├── stats.py               # Redis reliability + latency reservoir → fusion weights
│   ├── ratelimit.py           # cross-process rate gate + daily budget
│   ├── saved_queries.py       # recurring queries + {new, removed, unchanged} diff
│   ├── log.py                 # text|json → stderr ONLY (stdout is the MCP wire)
│   ├── sources/               # 22 adapters + base.py (Source, run_cmd, run_opencli)
│   └── extract/               # v0.4: parse, detectors, router, scheduler,
│                              # profiles, fingerprints, proxies, http, camoufox
├── skills/                    # 5 orchestration skills, symlinked by install.sh
│   ├── deep-research/         # research_ledger.py CLI (760 LOC, stdlib-only)
│   ├── master-router/         # request classification → tools/sources/effort plan
│   ├── report/                # make_report.py + make_charts.py + export.sh
│   ├── monitor/               # wraps saved_queries tool, interprets deltas
│   └── research-rubric/       # eval_run.py scores runs 0–100 on 4 axes
├── tests/                     # 14 files; fast suite = 135 tests (see Verification)
├── scripts/                   # bench.py (micro/model/search) + rerank_eval.py
├── docs/                      # this map, architecture, api/tools, meta-schema,
│                              # config-reference, deployment, security, faq,
│                              # 6 ADRs, voice, history/
├── infra/                     # docker-compose (Redis AOF + SearXNG), Dockerfile,
│                              # systemd unit, searxng settings
├── install.sh                 # idempotent skill symlinker → opencode + claude dirs
├── diagram-design/            # git submodule, pinned (install.sh links its skill)
├── mcp.json                   # ready stdio registration example
└── .env.example               # full config skeleton (see config-reference.md)
```

## The pipeline

`orchestrator.search()` is the single entry point every search tool funnels
through (`server.py` → `orchestrator.py:265`). The stages, in order:

| # | Stage | Module | Behavior |
|---|-------|--------|----------|
| 1 | Final cache | `cache.get` | Redis hit (TTL 1h) returns immediately, envelope `cached: true` |
| 2 | Fan-out | `orchestrator._singleflight` / `_run_one` | `asyncio.wait`, `SEARCH_GATEWAY_TIMEOUT=50s`; per-source: rate-limit → daily budget → per-source cache (15m) → adaptive timeout `min(p95×1.5, 25s)` → search; stragglers cancelled, reported `pending (timeout)`, never fail the request |
| 3 | Query expansion | `orchestrator._expand_query` | DeepSeek generates ≤2 variants, **only when base results < `SEARCH_GATEWAY_EXPANSION_GATE` (6)**; variants fan out over searxng+exa only |
| 4 | Fusion | `fusion.rrf_fuse` | score = Σ `w_s / (60 + rank)`; `w_s` = rolling 24h success rate (`stats.reliability`) |
| 5 | Dedup | `dedup.dedup` | canonical URL (tracking params stripped) → title difflib (≥0.92) → embedding cosine (≥0.93); CJK-aware — bge-m3 loads only when CJK share ≥25% (`embeddings.cjk_dominant`) |
| 6 | Re-rank | `rerank.rerank` | cross-encoder on top `RERANK_CANDIDATES` (30) only; ONNX int8 default (`SEARCH_GATEWAY_INFERENCE_BACKEND`), auto torch fallback |
| 7 | Diversity | `diversity.mmr_select` | greedy MMR, relevance floor 0.1, λ per category (news/social 0.7, general 0.75, science 0.8) |
| 8 | Filters | `orchestrator` | freshness (day/week/month/year) → year_from → open-access-only |

Every stage after fan-out degrades to its input rather than raising: model
unavailable → stage skipped, cache/stats Redis errors → caught, logged at
debug, treated as miss. The response envelope names the survivors:
`{query, count, results[], sources{ok(n)/error/pending}, cached, reranked,
partial, pending[], elapsed_ms, stage_ms{fanout, fusion_dedup, rerank, mmr}}`
(`orchestrator.py:365`).

## Module map

| Module | Owns | Key entry points |
|--------|------|------------------|
| `server.py` | the MCP surface; 14 `@mcp.tool()` handlers; `_clamp_limit` (1..30), `_resolve_sources` (unknown names fail loudly); `BearerAuthMiddleware` for http/sse; `_scrub` control-char stripping; `main(transport)` | `search`, `research_answer`, `get_paper`, `read_url`, `doctor`, `saved_queries` |
| `orchestrator.py` | pipeline orchestration; singleflight `_inflight` map; adaptive timeout; expansion gating | `search` (382-LOC module, the hub — 63 edges in the code graph) |
| `cli.py` | console commands; SIGTERM→SIGINT mapping for graceful shutdown | `serve` (default), `doctor`, `check`, `version`, `warm` |
| `health.py` | `report()` (cached probes, `DOCTOR_TIMEOUT=12s` budget) + `check()` (strict: 22 sources + Redis) | shared by the `doctor` tool and the CLI |
| `models.py` | `Result{title,url,snippet,source,engine,published,score,meta}` + `identity()` (canonical dedup key) | — |
| `config.py` | all 41 env settings + `load_env_file` + `FALLBACK_CHAINS` (per-source degrade-order matrix) | — |
| `fusion.py` | weighted RRF, `score_raw` preserved in `meta` | `rrf_fuse` |
| `dedup.py` | canonical URL (tracking-param strip), title `SequenceMatcher`, embedding cosine; `_merge` folds richest fields + `_also_found_by` | `canonical_url`, `dedup` |
| `diversity.py` | MMR; `_domain` uses `removeprefix` (documented `lstrip` bug fix, CHANGELOG 0.2.0) | `mmr_select` |
| `rerank.py` | lazy cross-encoder singleton; ONNX (`onnx`/`onnx_int8`) vs torch; status for doctor | `rerank`, `status` |
| `embeddings.py` | lazy MiniLM + bge-m3 singletons; `local_files_only=True` fast path with `snapshot_download` on miss; CJK detection | `encode`, `cjk_dominant` |
| `llm.py` | DeepSeek chat client; thinking-mode aware (reasoning tokens count toward max_tokens); key from env or `~/.agent-reach/deepseek.env` | `complete`, `available` |
| `cache.py` | Redis: final (`sg:`), per-source (`sg:s:`), negative (`sg:sf:`); `_valid_payload` schema check treats poisoned payloads as miss; `_norm_key_part` cache-poisoning defense | `get/set`, `get_source/set_source`, `mark_source_failed` |
| `stats.py` | Redis reliability counters (24h window) + bounded latency reservoir (60) → p50/p95, fusion weights, `snapshot()`; `ledger_health()` scans `SEARCH_GATEWAY_LEDGER_DIR` | `record`, `reliability`, `latency_percentiles` |
| `ratelimit.py` | per-source min-interval gate (Redis, in-memory fallback) + daily budget (300) | `wait_if_needed`, `enforce_daily_budget` |
| `saved_queries.py` | Redis `sg:sq:*` store; identity-based diff; first run establishes baseline | `save`, `list_all`, `run`, `diff` |
| `log.py` | text/json formatter → stderr; stdout is reserved for the MCP wire | `configure_logging` |
| `extract/` | the v0.4 extraction layer — tier routing (api=1/cli=3/browser=10), block/challenge detectors, browser budget + jittered pacing, profile farm + health machine, fingerprint bundles + coherence lint, env-gated proxy gateway, curl_cffi impersonation seam, multi-shape parsing, Camoufox adapter | `router`, `detectors`, `profiles`, `proxies`, `parse` |
| `sources/base.py` | `Source` ABC, `SourceError`, `run_cmd` (retry on exit codes 1/8/52/56), `run_opencli` (serialized via `OPENCLI_LOCK`), `guard_query` (flag-injection), `_subprocess_env` allowlist, `normalize_published` | — |

## Source adapters

22 adapters in `search_gateway/sources/`, all registered in `ALL_SOURCES`
(`sources/__init__.py:23`) — the single registry the orchestrator, `doctor`,
and `search-gateway check` read from. Three implementation patterns:

| Pattern | Mechanism | Sources |
|---------|-----------|---------|
| HTTP API | `httpx` direct, `SourceError` on failure | searxng (SearXNG JSON), arxiv (Atom), openalex (REST), crossref (REST), semantic_scholar (Graph API), github (REST; token raises rate limit), bilibili (B站 API), v2ex (sov2ex), stackoverflow (Stack Exchange), web (Jina Reader) |
| Subprocess CLI | `run_cmd` with env allowlist + retry | exa (mcporter), youtube (yt-dlp NDJSON) |
| Browser / OpenCLI | `run_opencli` (browser budget via `extract/scheduler`, default 1), opt-in via `sources=`, rate-limited 2.5s | twitter (twitter-cli → opencli failover), reddit, facebook, instagram, xiaohongshu (not yet authenticated — errors gracefully), linkedin (mcporter; account blocked on QR verification — errors gracefully) |
| CN tier (v0.4, gated by `SEARCH_GATEWAY_CN_SOURCES`) | zhihu (v4 API, cookie-gated), weibo (hot list + SUB-gated keyword search), baidu + toutiao hot boards (public JSON); bilibili upgraded with wbi signing (always on) |

Contract: subclass `Source`, implement `search()` (+ `available()` for doctor),
emit `Result` with `meta` keys per `docs/meta-schema.md`. Adding source #19 is
four bounded steps: new `sources/<name>.py` → register in `ALL_SOURCES` →
bump the count in `tests/test_contract.py` → cover it. Nothing else changes.

Notable per-source capabilities: openalex `get/citations/references` (work-ID
resolution), crossref `get/references` (structured refs), semantic_scholar
`citations/references` fallback tier, arxiv `get` by ID. All academic sources
honor the polite-pool `SEARCH_GATEWAY_MAILTO`.

## MCP tool surface

14 tools, asserted against the live `tools/list` by `tests/test_contract.py`
— a tool rename/removal is a SemVer-major event (see `docs/api/tools.md`).

| Tool | Routes to | Notes |
|------|-----------|-------|
| `search` | any source subset, any category | the universal fan-out; unknown source names raise |
| `search_web` | searxng + exa | |
| `search_news` | searxng + exa, category=news | |
| `search_science` | academic + searxng, science | supports year_from + open_access_only |
| `search_academic` | arxiv + openalex + crossref | expansion disabled |
| `search_social` | twitter + reddit + facebook + instagram | expansion disabled (keeps results social) |
| `get_paper` | crossref + openalex + arxiv merged | identifier: DOI / arXiv ID / title |
| `get_citations` | openalex → semantic_scholar fallback | |
| `get_references` | crossref → openalex → semantic_scholar chain | arxiv path skips crossref |
| `research_answer` | full search + DeepSeek synthesis | sources delimited, instruction-guarded; refuses to guess on empty |
| `read_url` | web (Jina Reader) | content scrubbed to 20k, control chars stripped |
| `doctor` | health.report() | bounded 12s, probe cache 120s |
| `stats_report` | stats.snapshot() + ledger_health() | |
| `saved_queries` | save / list / delete / run / diff | Redis-backed; diff is identity-based |

## Reliability model

Five independent mechanisms, each covering one failure mode
(`docs/architecture.md#reliability-model`):

| Failure | Mechanism | Where |
|---------|-----------|-------|
| source hangs | `asyncio.wait` keeps completed, cancels stragglers | orchestrator fan-out |
| source errors | retry ×1 (backoff ×1.5) on transient exit codes 1/8/52/56 only | `run_cmd` |
| cookie source flagged | 2.5s min interval + 300/day budget, cross-process via Redis | `ratelimit.py` |
| flaky source degrades results | weighted RRF: rolling 24h success rate as fusion weight, floored at 0.05 | `fusion.py` + `stats.py` |
| model / Redis down | stage skips its step, never raises; Redis errors logged at debug and treated as miss | rerank/embeddings/cache/stats |

## Configuration surface

41 environment variables, all with defaults, precedence env var > env file >
default (`config.py`; full reference in `docs/config-reference.md`). Groups:

- **Infrastructure**: `SEARXNG_BASE`, `SEARCH_GATEWAY_REDIS_URL`, `GITHUB_TOKEN`, `SEARCH_GATEWAY_HTTP_TOKEN`
- **Search behaviour**: `DEFAULT_SOURCES` (fast set: searxng/exa/github/youtube/bilibili/v2ex), `GLOBAL_TIMEOUT` (50), `PER_SOURCE_TIMEOUT` (18), `MAILTO`
- **Retry / rate-limit**: `RETRY_COUNT` (1), `RETRY_BACKOFF` (1.5), `RATE_LIMIT` (2.5), `DAILY_QUERY_LIMIT` (300)
- **Fusion / rerank / diversity**: models + pinned `*_REVISION` SHAs, `INFERENCE_BACKEND` (onnx_int8), `RERANK_CANDIDATES` (30), per-category MMR λ, `CJK_SHARE_THRESHOLD` (0.25), `WEIGHTED_RRF`, `EMBEDDING_DEDUP`, `FRESHNESS`
- **Cache**: `CACHE_TTL` (3600), `SOURCE_CACHE_TTL` (900), `NEGATIVE_CACHE_TTL` (60)
- **LLM**: `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL`, `LLM_MODEL` (deepseek-v4-flash), `QUERY_EXPANSION`, `EXPANSION_GATE` (6)
- **Observability / serving**: `LOG_FMT` (text|json, always stderr), `LOG_LEVEL`, `MCP_HOST`/`MCP_PORT`, adaptive-timeout knobs, `STATS_RESERVOIR` (60), doctor timeouts
- **Auth files** (paths, never inline secrets): `TWITTER_AUTH_FILE`, `DEEPSEEK_AUTH_FILE` — both under `~/.agent-reach/`

Secrets live in `~/.agent-reach/*.env` (or a 0600 `EnvironmentFile`); `.env.example` is the skeleton.

## Tests & CI

- **Fast suite: 191 tests, all green** (verified 2026-08-22: `pytest -m "not slow"` exit 0). Slow tests (model downloads) excluded.
- Test tiers: unit (models, parsers — `test_sources_parsers.py` has the largest parser surface), pipeline (in-memory `RedisStub` fixture in `tests/conftest.py` binds every module's `_get_client`), integration (smoke + stdio handshake — `test_smoke.py`, `test_mcp_handshake.py`).
- **Golden contract** (`tests/test_contract.py`): live registry = 22 sources, live `tools/list` = 14 tools, `Result` shape + standardized meta keys.
- CI (`.github/workflows/ci.yml`): ruff (F-clean, select E/W/I/B/UP/SIM/RUF/FURB/S/DTZ/BLE) + pytest on 3.12/3.13 against real Redis + SearXNG services + coverage gate ≥85% + headless Docker build.

## Infra

Host-process by design (ADR 0002 — CLIs + Chromium + warm model cache don't
dockerize). `infra/docker-compose.yml` runs only the two service dependencies:
Redis 7 (AOF persistence, password via `REDIS_PASSWORD`) and SearXNG
(`:8888`, JSON, `SEARXNG_SECRET_KEY`). `infra/Dockerfile` is a headless tier-1
image; `infra/systemd/search-gateway@.service` uses `search-gateway check` as
`ExecStartPre`. Full tier model: `docs/deployment.md`.

## Orchestration skills

Five skills ship in `skills/`, symlinked into client skill dirs by
`install.sh` (idempotent; `diagram-design` arrives as a git submodule). All
obey the gateway-first rule: retrieval goes through the MCP tools only, never
raw platform CLIs.

| Skill | Tool it wraps | Artifact |
|-------|---------------|----------|
| `master-router` | classification table → tool/source/effort plan | routing plan JSON |
| `deep-research` | `search_*`, `get_paper`, `get_citations`, `get_references`, `read_url` | versioned `ledger.json` via `research_ledger.py` (stdlib-only CLI: init/add-hop/add-claim/add-evidence/status/lint/export/memory-*) |
| `report` | ledger + `results.json` | 7-section report: `make_charts.py` (matplotlib) + editorial diagrams (diagram-design) + `make_report.py` + `export.sh` → md/pdf/docx/html + BibTeX |
| `monitor` | `saved_queries` | `{new, removed, unchanged}` delta report |
| `research-rubric` | ledger lint-passed | 0–100 score on 4 axes + Markdown self-review |

## Scripts

- `scripts/bench.py` — micro (dedup/MMR offline), model (cold load fresh-subprocess, warm latency, RSS), search (cold vs warm e2e, per-source latency, throughput).
- `scripts/rerank_eval.py` — CPU-only rerank/MMR/dedup evaluation: cross-encoder latency, Spearman vs reference, Hit@k, dedup collapse rate, MMR λ sweep. Includes CJK query set.

## ADRs

Six standing decisions in `docs/adrs/` (each linked from
`docs/architecture.md#design-decisions`): 0001 stdio-first · 0002 host-process
+ Redis state · 0003 weighted RRF · 0004 cross-encoder/bi-encoder CJK split ·
0005 pinned model revisions · 0006 skills-in-repo + submodule.

## Verification status

Verified on 2026-08-22:

- Fast test suite passes: 191 tests, exit 0.
- Code graph current: 619 nodes / 4,395 edges / 59 files, built at
  `bea991b` (matches HEAD).
- Version: `0.4.0` (`search_gateway/__init__.py`).

Not re-verified in this pass (live dependencies, expected to vary per machine):
per-source `available()` probes, model loads, Redis credentials, DeepSeek key.
Run `search-gateway doctor` / `search-gateway check` for the live picture.
