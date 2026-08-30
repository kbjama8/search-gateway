# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-08-29

"Rename bridge removal" — the 0.5.x `SEARCH_GATEWAY_*` fallback is gone.

### Removed
- **`SEARCH_GATEWAY_*` env fallback** (`config._read_env` legacy branch +
  the once-per-variable deprecation warning). Only `KORTEX_SEARCH_*` is
  read now. Stale env files, units, and shells still carrying the old
  prefix silently lose those settings — migrate to the new prefix.

### Fixed
- **CI red since 0.4.2**: `test_vault_status` passed locally only by
  accident (the machine's real vault files tripped the out-of-vault
  hygiene finding); in CI's clean HOME the assertion flipped. The fixture
  is now hermetic — VAULT_DIR points at a nonexistent path and
  `_CONFIG_PATHS` is patched too, asserting the intended
  "missing vault → warn" contract.
- **Time-bomb freshness fixtures**: two tests hardcoded
  `published=2026-08-20` against `freshness=week` and aged out of their
  own window two days later; fixtures are now date-relative.
- **Residual `sg-` doc stragglers** from the rename (deployment.md
  sudoers heredoc pointed at the old ruleset filename — a broken drop-in
  waiting to happen).

## [0.5.0] - 2026-08-26

"Rename to Kortex Search" — product rebrand from Search Gateway.

### Changed (breaking)
- **Package** `search_gateway` → `kortex_search` (imports, loggers, module paths).
- **Console script / binary** `search-gateway` → `kortex-search`
  (`[project.scripts]` entry, CLI `prog`, FastMCP server name).
- **Env prefix** `SEARCH_GATEWAY_*` → `KORTEX_SEARCH_*`. The old prefix is
  still read as a deprecated fallback (warns once per variable; removal in
  0.6.0). Unprefixed vars (`SEARXNG_*`, `GITHUB_TOKEN`, `DEEPSEEK_*`,
  `ZHIHU_COOKIE`, `WEIBO_SUB`, `TWITTER_AUTH_FILE`, `DEEPSEEK_AUTH_FILE`)
  are unchanged.
- **Redis key prefix** `sg:` → `ks:` (cache, rate-limit, stats, saved
  queries). `sg:sq:*` saved queries are migrated on upgrade; TTL-bound
  caches/stats expire naturally.
- **Systemd units** `search-gateway@.service` → `kortex-search@.service`,
  `search-gateway-harden.service` → `kortex-search-harden.service`; config
  dir `~/.config/search-gateway/` → `~/.config/kortex-search/`.
- **Egress filter** nft table/scope `sg_egress`/`sg-egress` →
  `ks_egress`/`ks-egress`; ruleset file `sg-egress.nft` → `ks-egress.nft`.
- Repo renamed (local + GitHub `kbjama8/kortex-search`); opencode MCP key
  `mcp.kortex-search` (tool prefix `kortex-search_*`).

## [0.4.3] - 2026-08-23

"CN truth + vault finalization" (PHASE8 Plan 1/2/3/5 + D7.3).

### Fixed
- **Baidu hot board was silently broken** (R12, live-verified 2026-08-23):
  the endpoint's JSON structure changed (`cards[]` with `word`/`hotScore` →
  `tabTextList` with nested `content[].content[]` items carrying
  `word`/`url`/`index`/`hotTag`/`newHotName`), so the parser returned
  empty results. Dual-shape parser now handles both shapes, and a
  **shape-drift guard** raises `SourceError` on any 200-with-cards-but-
  unparseable response — the silent-empty failure mode is closed for good.

### Added
- **Zhihu hot-list source** (`zhihu_hot`, R11): the anonymous
  `api.zhihu.com/topstory/hot-list` endpoint (verified live, 30-item cap)
  gives zhihu a zero-cookie presence alongside the cookie-gated v4 search;
  URLs rewritten to the human surface; registry 22 → **23 sources** (contract
  + `check` gate updated in the same commit).
- Fixtures for both CN fixes under `tests/fixtures/platforms/` (recorded
  live captures).
- `docs/extraction/stealth-matrix.md` (R2): nodriver vs Patchright vs
  Camoufox capability matrix + adoption triggers — insurance, not adoption.
- `docs/adrs/0007-cn-signing-deferred.md` (Plan 5): Douyin/XHS stay deferred
  with explicit revival triggers (XHS drift + 406 since Mar 2026; Douyin
  x-gorgon emulation cost).
- `docs/extraction/PHASE8-PLAN.md`: the approved consolidation plan.

### Changed
- **D7.3 lands**: legacy flat secret paths (`~/.agent-reach/twitter-auth.env`
  etc.) are **removed** — `env_file_for` resolves the vault path only;
  `migrate()` remains as the migration path for never-migrated machines
  (migrate before upgrading past 0.4.2). Doctor `vault` section drops
  `legacy_in_use`.

## [0.4.2] - 2026-08-23

Phase 7 (containment & observability), release 2 of 2 — the sharp end:
L2 forced-proxy for the anonymous tier, the **mandatory** L3 kernel egress
filter, bench browser tier, and the hardened systemd unit
(`docs/extraction/PHASE7-HANDOFF.md`, decisions D7.1/D7.2).

### Added
- **L3 kernel egress filter** (`extract/harden.py`, decision D7.1):
  nftables `socket cgroupv2` per-cgroup DROP rules for private/link-local/
  metadata ranges (pam_authnft pattern — no suid binary, no kernel module,
  LESSONS.md §1.5). `search-gateway harden --install|--status|--uninstall|
  --check [--sudo]`; `build_rules()` is a pure function with a golden
  ruleset test; all kernel probes mocked in CI.
- **Mandatory enforcement (D7.1)**: browser-tier ops (`run_opencli` +
  Camoufox launch) refuse to run until the filter is installed — the
  explicit `blocked (egress-unhardened): run 'search-gateway harden
  --install --sudo'` message reaches the envelope and negative cache.
  `SEARCH_GATEWAY_HARDEN=required` (default) | `permissive` (sandboxed-CI
  opt-out). OpenCLI children are wrapped in a `systemd-run --user --scope
  --unit=sg-egress` transient scope when the gateway itself is not inside
  the scoped cgroup; Camoufox requires the gateway to be scoped (its
  children cannot be wrapped).
- **L2 forced-proxy** (`egress.EgressProxy`, decision D7.2): loopback
  CONNECT/absolute-URI HTTP proxy fronting the anonymous tier; every target
  re-passes the floor (403 + telemetry), chains through the residential
  tier when enabled, origin-form rewriting, lazy singleton.
  `SEARCH_GATEWAY_EGRESS_PROXY=1` (default ON for the anonymous tier).
  Camoufox launches with `--proxy-server` + `--host-resolver-rules="MAP *
  0.0.0.0, EXCLUDE 127.0.0.1"` (remote DNS through the proxy too).
- **bench browser tier** (`scripts/bench.py browser`, slow): egress-floor
  overhead, L2 proxy roundtrip vs direct, Camoufox cold/warm launch,
  navigate→extract→teardown, profile rotation, RSS delta — each measurement
  SKIPs with a reason when its dependency is absent.
- **Hardened systemd unit** (`infra/systemd/search-gateway@.service`):
  `LoadCredential=` for the vault (`$CREDENTIALS_DIRECTORY` bridge),
  `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict` + `ReadWritePaths`
  for vault/HF-cache, `RestrictAddressFamilies`, service-level `IPAddressDeny`
  (loopback stays open for Redis/SearXNG), `ExecStartPre` installs + reports
  the L3 filter for the unit's cgroup. `systemd-analyze verify` exits 0.

### Changed
- `doctor`'s `egress` section is now fully populated: floor + proxy + kernel
  state (`mode`/`installed`/`covered`) + denial counters.
- `.env.example` / `docs/config-reference.md`: 3 new variables
  (`SEARCH_GATEWAY_EGRESS_PROXY`, `SEARCH_GATEWAY_HARDEN`,
  `SEARCH_GATEWAY_HARDEN_SUDO`) → 82 documented.
- Deployment docs: §3.2 kernel-filter walkthrough (ad-hoc scope, systemd
  unit, `sudo nft -f` one-time load).

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
