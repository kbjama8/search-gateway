# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
