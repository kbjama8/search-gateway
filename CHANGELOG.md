# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.1] - 2026-08-23

Phase 7 (containment & observability), release 1 of 2 — the zero-risk floor:
L1 egress floor, per-persona secrets vault with full migration, and block
telemetry. L2/L3 land in 0.4.2 (`docs/extraction/PHASE7-HANDOFF.md`, decisions
D7.1–D7.4).

### Added
- **L1 egress floor** (`extract/egress.py`): always-blocked private/link-local/
  metadata ranges (RFC1918, CGNAT, IMDS across AWS/GCP/Azure/Alibaba, loopback
  v4+v6) checked **pre-nav and post-redirect** on every extraction path — API
  tier (`extract/http.py`), all `read_url` stages (`sources/web.py`), the
  Camoufox adapter, and the `read_url` server tool. Pure IP/hostname matching,
  no DNS in the floor; the L3 kernel filter catches what the floor can't see.
  Local-infra exemption only (`SEARXNG_BASE`/`REDIS_URL` hosts +
  `SEARCH_GATEWAY_FLOOR_EXEMPT`). Default **ON** by design.
- **Per-persona secrets vault** (`extract/vault.py`): secrets move to
  `~/.agent-reach/profiles/<persona>/{twitter,deepseek,proxy}.env` (0600,
  decision D7.3). `search-gateway vault migrate [--dry-run]` / `vault status`;
  hygiene checks (mode enforcement, symlink traps, stale files, out-of-vault
  config) warn-not-fail but color doctor red. Legacy flat paths honored one
  release with a doctor deprecation warning (removed 0.4.3).
- **systemd credentials bridge**: `SEARCH_GATEWAY_CREDENTIALS_DIR`
  (`$CREDENTIALS_DIRECTORY`) — secrets arrive as files, never env vars
  (LESSONS.md §1.5).
- **Block-event telemetry** (`stats.record_block` / `blocks_snapshot`): bounded
  24h reservoir `sg:bl:<source>:<vendor>` recorded from the subprocess raise
  site, the envelope chokepoint (non-raising blocked strings only — no double
  counting), and egress denials.
- **Doctor sections**: `egress{floor,proxy,kernel,denied_count,last_denial}`,
  `vault{profiles,hygiene,findings}`, `blocks`, `profiles` (Phase 2 profile
  farm status). `stats_report` gains `blocks`.

### Changed
- `TWITTER_AUTH_FILE` / `DEEPSEEK_AUTH_FILE` / `SEARCH_GATEWAY_PROXY_AUTH_FILE`
  defaults now point into the vault; consumers resolve via the vault chain
  (credentials bridge → vault → legacy).
- `.env.example` / `docs/config-reference.md`: 6 new variables (containment +
  vault + telemetry).

### Security
- SSRF floor: the whole link-local range is blocked, not just the well-known
  IMDS address — a post-redirect jump to any private/metadata host now fails
  with an explicit `blocked (egress-floor/…)` envelope signal.

## [0.4.0] - 2026-08-22

Project Gatekeeper — the extraction-architecture overhaul
(`docs/extraction/PLAN.md`).

### Added
- `search_gateway/extract/` package: multi-shape parsing (`parse.py`),
  block & challenge intelligence (`detectors.py`), extraction tiering
  (`router.py`), browser budget + jittered pacing (`scheduler.py`), browser
  profile farm + health state machine (`profiles.py`), fingerprint bundles +
  coherence lint + geo alignment (`fingerprints.py`), env-gated proxy
  subsystem with sticky sessions (`proxies.py`), HTTP facade with optional
  curl_cffi TLS/JA3 impersonation (`http.py`), Camoufox anonymous-tier
  adapter, experimental (`camoufox.py`).
- Envelope v0.4 signals (additive): `extract{tier}`, `blocked[]`, `auth{}`.
- `read_url` multi-stage extraction: Jina (SPA) → Trafilatura (precision) →
  readability (recall), configurable via `SEARCH_GATEWAY_READ_URL_STAGES`.
- Bilibili **wbi signing** (w_rid/wts, Redis-cached daily keys) — verified
  against the canonical bilibili-API-collect worked example.
- Chinese-ecosystem tier (gated by `SEARCH_GATEWAY_CN_SOURCES=1`):
  **zhihu** (v4 search API, cookie-gated), **weibo** (hot search + SUB-gated
  keyword search), **baidu** + **toutiao** hot boards (public, no auth).
  Registry 18 → **22 sources**.
- Block detection in the subprocess layer: challenge walls fail immediately
  (`blocked (vendor/level)`) instead of burning retries; Cloudflare's
  official `cf-mitigated: challenge` header is the primary signal.
- `docs/extraction/`: PLAN (assignment), LESSONS (research journal),
  `proxy-funding-guide.md`, `camoufox-migration.md`, `project-map.md` vision
  & goals section.

### Changed
- `OPENCLI_LOCK` replaced by the configurable browser budget
  (`SEARCH_GATEWAY_BROWSER_BUDGET`, default 1 — old single-bridge behavior
  preserved).
- Core deps: `trafilatura`, `readability-lxml` (read_url stages).
- `search-gateway check` gate: 18 → 22 sources.
- Golden contract test: 22 sources + 14 tools + `Result` shape.

### Fixed
- Bilibili search silently degrading without wbi signing (unsigned requests
  returned `v_voucher` risk-control payloads).

## [0.3.0] - 2026-08-15

### Added
- ONNX Runtime inference backend for the cross-encoder, on by default
  (`SEARCH_GATEWAY_INFERENCE_BACKEND=onnx_int8`): ~2× faster re-rank and ~1GB
  smaller RSS than torch at Spearman ≈ 0.96 ranking agreement. `onnx`
  (fp32) and `torch` remain available; the reranker falls back to torch
  automatically if the ONNX model can't load.
- `scripts/bench.py` — micro/model/search benchmark harness (p50/p90, RSS,
  subprocess cold-start measurement).

### Changed
- `optimum[onnxruntime]` + `onnxruntime` are now core dependencies (was the
  `.[onnx]` optional extra).
- Docs rewritten in the hybrid answer-synthesis voice with Mermaid diagrams;
  six ADRs, a FAQ, and a CONTRIBUTING guide added.

### Fixed
- `saved_queries` MCP tool crashed with `AttributeError` (module shadowed by
  the same-named tool function) — now aliased and regression-guarded.
- `diversity._domain` misused `str.lstrip("www.")` (character-set semantics,
  mangling domains like `worldwide.com`) — now `removeprefix`.
- Embedding loader cold-start hits the Hugging Face API even on a warm cache —
  now `local_files_only=True` fast path with `snapshot_download` on miss.
- `get_paper` awaited its independent sub-lookups sequentially — now
  `asyncio.gather`.

## [0.2.0] - 2026-08-14

Standalone, client-agnostic release: the gateway decouples from OpenCode into
its own repo (public, MIT) while the orchestration skills ship alongside it.

### Added
- Console entry point `search-gateway` with `serve` (default, stdio),
  `doctor`, `check`, `version`, and `warm` subcommands (`cli.py`, `health.py`).
- Optional HTTP/SSE transports (`serve --transport http|sse --host --port`) for
  a long-running host process.
- Structured logging (`SEARCH_GATEWAY_LOG_FMT=json|text`, `SEARCH_GATEWAY_LOG_LEVEL`)
  — always to stderr; SIGTERM/SIGINT graceful shutdown.
- Repo hygiene: MIT `LICENSE`, `.gitignore`, `.env.example`, `mcp.json`,
  `install.sh` (idempotent skill symlinks), `CHANGELOG.md`.
- Canonical docs: `api/tools.md`, `meta-schema.md`, `config-reference.md`,
  `deployment.md`, `architecture.md`, `mcp-registration.md`, `security.md`,
  plus `docs/history/` (project archaeology).
- Infra: `docker-compose.yml` (Redis AOF + SearXNG JSON), headless tier-1
  `Dockerfile`, `systemd/search-gateway@.service`.
- CI (`ci.yml`, Python 3.12/3.13, `pytest -m "not slow"`) and a golden
  contract test (18 sources + 14 tools + `Result` surface).
- Regression tests for the bare `search-gateway` stdio handshake and the
  `saved_queries` tool (`tests/test_mcp_handshake.py`); the fast suite is now
  16 tests.
- `docs/voice.md` — the hybrid answer-synthesis voice contract; the docs were
  rewritten to it (narrative voice-card register for README/architecture,
  reference research_answer register for the rest, with Mermaid diagrams).

### Changed
- Orchestration skills (`deep-research`, `master-router`, `report`, `monitor`,
  `research-rubric`) now ship in this repo and are symlinked into client skill
  dirs; docs de-pathed to `$SKILL_DIR`-relative.
- `diagram-design` is now a **git submodule** (pinned commit) instead of a
  vendored copy.
- Version is sourced from `search_gateway/__version__` (`dynamic` in
  `pyproject.toml`).

### Fixed
- Declared `huggingface-hub` and `numpy` as direct dependencies (previously
  transitive-only).
- Pinned Hugging Face model revisions (`bge-reranker-v2-m3`, `all-MiniLM-L6-v2`,
  `bge-m3`) via `*_REVISION` env vars to stop the commit-churn re-download bug.
- `saved_queries` MCP tool crashed with `AttributeError`: the same-named tool
  function shadowed the module import. Now aliased (`sq`), verified end-to-end,
  and regression-guarded.
- `diversity._domain` misused `str.lstrip("www.")` (which strips a *character
  set*, mangling domains like `worldwide.com`); now `removeprefix`.
- File-handle leaks in `load_env_file` and the twitter env loader (`open()`
  without a context manager).
- Removed unused variables/imports; `ruff` F-rule checks are clean across the
  package and tests.

## [0.1.0] - 2026-08-14

### Added
- Unified web-search & research MCP server (FastMCP, stdio) fusing 18 sources
  behind one `search` tool: weighted RRF fusion, de-duplication, cross-encoder
  re-rank, MMR diversity, freshness filtering, Redis cache.
- 14 MCP tools: `search`, `search_web`, `search_news`, `search_science`,
  `search_social`, `search_academic`, `get_paper`, `get_citations`,
  `get_references`, `research_answer`, `read_url`, `doctor`, `stats_report`,
  `saved_queries`.
- Orchestration skills (deep-research, master-router, report, monitor,
  research-rubric) and a pytest regression guard.
