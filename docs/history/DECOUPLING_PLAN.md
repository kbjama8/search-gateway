# Search-Gateway → Standalone Repo — Decoupling Plan (v2)

**Status:** PLAN — approved, ready to execute · **Owner:** KBJ · **Updated:** 2026-08-14

Goal: make `search-gateway` a fully standalone, self-contained MCP server that can
be uploaded as its own repository — while **everything currently connected
(OpenCode skills, Redis, SearXNG, DeepSeek, the research pipeline) keeps working
without interruption.** The MCP must not know or care that OpenCode exists.

---

## 0. Executive summary

The `search_gateway/` Python package is already ~90% decoupled — zero OpenCode
references in code, and the skills already talk to it purely over MCP tools. The
remaining work is **packaging + repo hygiene + infra reproducibility + a
reversible cutover + a hardening pass**, not a rewrite.

Work proceeds in six reversible phases (A–F). Each phase leaves the system
working; there is no big-bang cutover. The server is extracted into a public MIT
repo; the orchestration skills ship in the same repo and are symlinked back into
OpenCode; `diagram-design` becomes a git submodule.

---

## 1. Decisions (LOCKED 2026-08-14)

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | diagram-design | **git submodule** | upstream MIT repo; avoid 2.2 MB vendored bloat; report skill references it by name |
| 2 | skills in repo? | **ship in repo + symlink install** | keeps the research backbone versioned with the gateway |
| 3 | gateway deployment | **host process + systemd unit** | social sources need CLIs + Chromium + warm models; dockerize Redis/SearXNG only |
| 4 | visibility | **public, MIT** | credentials are external env files; matches diagram-design licensing |
| 5 | auth-file defaults | **keep `~/.agent-reach/*.env`** | belongs to the agent-reach ecosystem; already env-overridable |
| 6 | repo name | **`search-gateway`** (package `search-gateway`) | matches the existing package + README identity |
| 7 | PyPI publish | **GitHub-only for now** | "individual repo" ≠ package distribution; defer PyPI (name is generic, may collide) |
| 8 | HF model revision pinning | **pin now** | fixes the observed bge-m3 commit-churn re-download bug |
| 9 | bge-m3 in CI | **out of CI** | 2.3 GB download; model tests gated `@pytest.mark.slow` |

### Pinned model revisions (HF `revision=`)

| Model | Revision (sha) |
|-------|----------------|
| `BAAI/bge-reranker-v2-m3` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| `sentence-transformers/all-MiniLM-L6-v2` | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| `BAAI/bge-m3` | `5617a9f61b028005a4858fdac845db406aefb181` |

---

## 2. Current state / coupling inventory (verified 2026-08-14)

### 2.1 Already decoupled

- **Gateway code is OpenCode-free** — no `opencode` references in `search_gateway/**/*.py`.
- **MCP protocol is stdio (FastMCP)** — client-agnostic.
- **Skills → gateway only via MCP tools**, never by path.
- **Report scripts self-resolve** (`export.sh` uses `$SCRIPT_DIR`).
- **Config `~`-paths are env-overridable** (`TWITTER_AUTH_FILE`, `DEEPSEEK_AUTH_FILE`, `SEARCH_GATEWAY_LEDGER_DIR`).

### 2.2 The couplings to remove

| Coupling | Where | Severity |
|----------|-------|----------|
| Location inside `~/.config/opencode/` | filesystem | high |
| `opencode.jsonc` hardcodes absolute `PYTHONPATH` + `python3 -m` | `~/.config/opencode/opencode.jsonc` | high |
| No console entry point / no `main()` | `pyproject.toml`, `server.py` | medium |
| **`huggingface_hub` + `numpy` not declared as deps** (imported but transitive-only) | `pyproject.toml` | high (real bug) |
| No `.gitignore` / `LICENSE` / `.env.example` / CI | repo root | high |
| Skills hardcode `~/.config/opencode/skills/...` in docs | `skills/*/SKILL.md`, `README.md` | low |
| `.pytest_cache/` present in tree | repo root | low (hygiene) |
| `diagram-design` vendored as a full copy | `~/.config/opencode/skills/` | medium |

### 2.3 External dependencies (machine-level, NOT OpenCode)

| Dep | Type | Default | Env override |
|-----|------|---------|--------------|
| Redis | service | `redis://127.0.0.1:6379/0` | `SEARCH_GATEWAY_REDIS_URL` |
| SearXNG | service | `http://127.0.0.1:8888` | `SEARXNG_BASE` |
| DeepSeek | SaaS LLM | `https://api.deepseek.com` + key | `DEEPSEEK_API_KEY`/`DEEPSEEK_BASE_URL` |
| `opencli` + Chromium | CLI + browser | social sources | `SEARCH_GATEWAY_OPENCLI_PROFILES` |
| `twitter` (twitter-cli) | CLI | twitter primary | — |
| `mcporter` | CLI | exa + linkedin | — |
| `yt-dlp` | CLI | youtube | — |
| `uvx` | CLI | linkedin (`mcp-server-linkedin`) | — |
| HF models (cached `~/.cache/huggingface`) | weights | reranker · MiniLM · bge-m3 | model env vars + `*_REVISION` |
| Free academic APIs (arXiv/OpenAlex/Crossref/S2/StackExchange) | HTTP | no key | — |

> **agent-reach** is a separate ecosystem: the gateway shells out to its CLIs
> (opencli/twitter-cli/mcporter) but does **not** bundle it. In the standalone
> repo these are documented external dependencies (binaries on PATH + Chromium).

---

## 3. Dependency model

### 3.1 Core server (explicit — fixes the transitive-dep bug)

```toml
dependencies = [
    "fastmcp>=3.0,<4",
    "httpx>=0.27",
    "redis>=5.0",
    "pyyaml>=6.0",
    "sentence-transformers>=3.0",
    "huggingface-hub>=0.24",   # embeddings.py imports it directly
    "numpy>=1.24",             # embeddings/dedup/diversity import it directly
]
```
`requires-python = ">=3.10"` (recommend `>=3.12`; validated on 3.14).

### 3.2 Capability tiers (a fresh install degrades *explicitly*)

| Tier | Sources | Requires |
|------|---------|----------|
| **minimal** | arxiv, openalex, crossref, stackoverflow, github(REST), web/read_url (+ searxng if up) | `pip install .` + network |
| **web+neural** | + exa | `mcporter` on PATH |
| **social/vertical** | + twitter, reddit, facebook, instagram, xiaohongshu, linkedin, youtube | `opencli`+Chromium, `twitter`, `yt-dlp`, `uvx` |
| **answer synthesis** | `research_answer`, query expansion | `DEEPSEEK_API_KEY` |

`doctor()` already reports per-source down/error → it doubles as the **tier
report**. `docs/deployment.md` documents the install for each tier.

### 3.3 Skill deps (separate from server)

```toml
[project.optional-dependencies]
report = ["matplotlib", "weasyprint", "python-docx", "playwright"]
# pandoc + mmdc are system binaries, documented in skills/report/README.md
```
`deep-research` / `monitor` / `research-rubric` are stdlib-only.

---

## 4. Target repository layout

```
search-gateway/
├── search_gateway/            # server package + cli.py (new)
│   ├── server.py              # + def main(): mcp.run()
│   ├── cli.py                 # NEW: serve/doctor/check/version/warm
│   ├── config.py              # + *_REVISION pins
│   └── ... (orchestrator, cache, stats, sources/, etc.)
├── skills/                    # orchestration skills — SOURCE OF TRUTH
│   ├── deep-research/ master-router/ report/ monitor/ research-rubric/
├── tests/                     # 6 files (see §13)
├── docs/
│   ├── meta-schema.md         # Result.meta contract (moved)
│   ├── config-reference.md    # full env-var table (NEW)
│   ├── deployment.md          # tiers + docker/systemd/native (NEW)
│   ├── architecture.md        # pipeline + decoupling boundary (NEW)
│   ├── mcp-registration.md    # any-client registration (NEW)
│   ├── api/tools.md           # tool-surface contract (NEW)
│   ├── security.md            # threat model (NEW)
│   └── history/               # TODO.md + tasks/ (project archaeology)
├── infra/
│   ├── docker-compose.yml     # redis + searxng
│   ├── Dockerfile             # headless gateway image (CI/tier-1 only)
│   └── systemd/search-gateway@.service
├── .github/workflows/ci.yml
├── .env.example · .gitignore · LICENSE (MIT) · CHANGELOG.md
├── mcp.json · install.sh · pyproject.toml · README.md
```

**Move out / exclude:** `opencode.jsonc` stays in `~/.config/opencode/` (client
config). `references/search-gateway.md` + `agent-reach.md` stay in OpenCode. The
`diagram-design` skill becomes a **git submodule** (not copied). `.pytest_cache/`
is deleted before first commit. Secrets (`~/.agent-reach/*.env`) never enter the repo.

---

## 5. Packaging & CLI surface

```toml
[project.scripts]
search-gateway = "search_gateway.cli:main"
```

`search_gateway/cli.py`:

| Command | Behavior |
|---------|----------|
| `search-gateway serve` (default) | run the stdio MCP server (`mcp.run()`) |
| `search-gateway doctor` | run the health check **once**, print JSON, exit 0/1 — for `ExecStartPre`/CI |
| `search-gateway check` | import + 18 sources + Redis ping + DeepSeek availability; non-zero on failure |
| `search-gateway version` | print `__version__` |
| `search-gateway warm` | preload rerank/embed models (first-query latency) |

`server.py` gains `def main() -> None: mcp.run()`.

---

## 6. MCP tool-surface contract & versioning

- `docs/api/tools.md` = canonical list (14 tools incl. `saved_queries`) + arg/return
  schemas. **This is the public API.**
- **SemVer**: add tool = minor · remove/rename tool or change a `Result`/return
  field = major + deprecation cycle. `docs/meta-schema.md`'s rule generalizes to
  the whole surface.
- The stdio `initialize`/`tools/list` handshake is the conformance check; a
  `test_contract.py` asserts 18 sources + 14 tools + `Result.meta` keys.

---

## 7. MCP registration (any client)

```jsonc
// mcp.json (or the client's equivalent)
{
  "mcpServers": {
    "search-gateway": {
      "command": "search-gateway",
      "env": { "SEARCH_GATEWAY_REDIS_URL": "redis://127.0.0.1:6379/0" }
    }
  }
}
```

- **OpenCode**: `opencode.jsonc` `mcp.search-gateway.command` → `["search-gateway"]`.
- **Claude Code**: `claude mcp add search-gateway -- search-gateway`.
- Verify with a raw JSON-RPC stdio handshake so no client is the source of truth.

---

## 8. Containers, servers, and state

- **`infra/docker-compose.yml`** — `redis` + `searxng/searxng` (JSON format, `:8888`).
- **Gateway stays a host process** (CLIs + Chromium + model cache don't dockerize
  cleanly). Optional `Dockerfile` for a **headless tier-1 image** (academic/web/
  searxng/exa only) for CI.
- **systemd** (`search-gateway@.service`): `ExecStartPre=search-gateway check`,
  `Restart=on-failure`, `EnvironmentFile=` (secrets, 0600), `TimeoutStopSec`.
- **State**: Redis holds cache/stats/rate-limit (ephemeral) **and `saved_queries`
  (user state)**. Enable **AOF** so saved queries survive restart; document backup.

---

## 9. Config & secrets

### 9.1 Full env surface (for `.env.example` + `docs/config-reference.md`)

`SEARXNG_BASE` · `SEARCH_GATEWAY_REDIS_URL` · `GITHUB_TOKEN` · `SEARCH_GATEWAY_MAILTO` ·
`SEARCH_GATEWAY_TIMEOUT` · `SEARCH_GATEWAY_SOURCE_TIMEOUT` · `SEARCH_GATEWAY_RETRY_COUNT` ·
`SEARCH_GATEWAY_RETRY_BACKOFF` · `SEARCH_GATEWAY_RATE_LIMIT` · `SEARCH_GATEWAY_RERANK_MODEL` ·
`SEARCH_GATEWAY_EMBED_MODEL` · `SEARCH_GATEWAY_EMBED_MODEL_CJK` · `SEARCH_GATEWAY_CJK_SHARE_THRESHOLD` ·
`SEMANTIC_RERANK` · `SEARCH_GATEWAY_RERANK_CANDIDATES` · `SEARCH_GATEWAY_MMR` ·
`SEARCH_GATEWAY_MMR_LAMBDA` · `SEARCH_GATEWAY_EMBEDDING_DEDUP` · `SEARCH_GATEWAY_WEIGHTED_RRF` ·
`SEARCH_GATEWAY_FRESHNESS` · `SEARCH_GATEWAY_TWO_TIER` · `SEARCH_GATEWAY_OPENCLI_PROFILES` ·
`SEARCH_GATEWAY_CACHE_TTL` · `SEARCH_GATEWAY_SOURCE_CACHE_TTL` · `SEARCH_GATEWAY_QUERY_EXPANSION` ·
`SEARCH_GATEWAY_LLM` · `SEARCH_GATEWAY_LLM_MODEL` · `SEARCH_GATEWAY_LLM_TIMEOUT` ·
`DEEPSEEK_API_KEY` · `DEEPSEEK_BASE_URL` · `TWITTER_AUTH_FILE` · `DEEPSEEK_AUTH_FILE` ·
`SEARCH_GATEWAY_LEDGER_DIR`

**Plus** (new): `SEARCH_GATEWAY_RERANK_REVISION`, `SEARCH_GATEWAY_EMBED_REVISION`,
`SEARCH_GATEWAY_EMBED_CJK_REVISION` — default to the pinned shas in §1.

### 9.2 Hygiene

- `.gitignore`: `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `*.egg-info/`, `dist/`,
  `build/`, `deliverable/`, `assets/*.png`, `.env`, `*.env`, `*.pem`, `*.key`, `*.log`.
- Secrets stay in `~/.agent-reach/` (0600); `.env.example` has placeholders only.

---

## 10. Skills & tools connection

- Move `skills/{deep-research,master-router,report,monitor,research-rubric}` into
  the repo as source-of-truth.
- `install.sh` symlinks them into `~/.config/opencode/skills/` **and**
  `~/.claude/skills/` (multi-client), idempotent, `--force` to relink.
- **De-path the docs**: replace `~/.config/opencode/skills/<name>/...` with a
  `$SKILL_DIR`-relative instruction ("run `scripts/research_ledger.py` from this
  skill's dir"). Scripts already self-resolve; add the same pattern to any
  remaining absolute-path invocation.
- **diagram-design** = git submodule; the report skill references it by name.

### Skill ↔ gateway contract (must hold post-decoupling)

| Skill | MCP tools called | Local scripts |
|-------|------------------|---------------|
| deep-research | `search_*`, `get_paper`, `get_citations`, `get_references`, `read_url` | `research_ledger.py` |
| master-router | (planning only) | — |
| report | (reads ledger + results) | `make_report.py`, `make_charts.py`, `export_diagram.py`, `export.sh` |
| monitor | `saved_queries` | — |
| research-rubric | (reads ledger) | `eval_run.py` |

---

## 11. Observability & lifecycle

- **Structured logging** — `SEARCH_GATEWAY_LOG_FMT=json|text`, `SEARCH_GATEWAY_LOG_LEVEL`;
  JSON to stdout so systemd/journald capture it.
- **Graceful shutdown** — wire SIGTERM/SIGINT to FastMCP close.
- **systemd** — `Restart=on-failure`, `ExecStartPre=search-gateway check`,
  `ExecStartPost=search-gateway warm` (optional), `TimeoutStopSec`.
- First query loads models (~30 s) — `warm` removes that from the request path.

---

## 12. Security & threat model

| Threat | Mitigation |
|--------|-----------|
| Untrusted fetched content → DeepSeek (prompt injection) | `research_answer` prompt is scoped "use ONLY the numbered sources"; synthesis refuses out-of-scope; documented as best-effort, not a sandbox |
| Social auth tokens in subprocess env (`TWITTER_AUTH_TOKEN`/`CT0`) | child-process env only, never logged; `.gitignore` blocks `*.env`; `doctor`/`check` never echo secrets |
| Model download supply chain | pinned `*_REVISION` (fixes the bge-m3 re-download churn) |
| `read_url` fetching arbitrary URLs (SSRF) | local, user-initiated tool; no secret-bearing reach beyond the user's request |

`docs/security.md` ships the table + reporting guidance.

---

## 13. Testing strategy

```
tests/
├── test_smoke.py          # fast: imports + 18 sources + smoke search (no models)
├── test_phase4.py         # fast: cjk_dominant, ledger_health, saved_queries CRUD
├── test_cli.py            # fast: search-gateway doctor/check/version exit codes
├── test_mcp_handshake.py  # stdio JSON-RPC: initialize → tools/list → search
├── test_contract.py       # golden: tool surface + Result.meta keys unchanged
└── test_models.py         # @pytest.mark.slow: rerank/embed paths (skip if HF cache cold)
```
`pytest.ini_options`: `markers = ["slow: requires downloaded models"]`,
`pythonpath=["."]`, `addopts="-q"`. CI runs `-m "not slow"`.

---

## 14. CI/CD (`.github/workflows/ci.yml`)

- Matrix `python: [3.11, 3.12, 3.13]`; `pip install -e .` + `pytest -m "not slow"`.
- Lint (optional `ruff`); build the `Dockerfile` to prove it assembles.

---

## 15. Versioning & release

- SemVer from `search_gateway/__init__.py` (currently `0.1.0`).
- `CHANGELOG.md` (Keep-a-Changelog): Phases 1–4 = v0.1.0; decoupling = **v0.2.0**.
- GitHub-only release (no PyPI for now); tag + release on completion.

---

## 16. Phased migration (reversible, checkpoints)

| Phase | Work | Exit criteria | Rollback |
|-------|------|---------------|----------|
| **A. Repo scaffold** | git init, .gitignore, LICENSE, .env.example, `cli.py` + `main()`, pinned deps + extras, `*_REVISION`, CHANGELOG | `pip install -e .`; `search-gateway doctor` exits 0 | nothing deployed |
| **B. Cutover OpenCode** | `opencode.jsonc` → `["search-gateway"]` | restart; 14 tools load; a `search` returns fused results | revert one line |
| **C. Skills into repo** | move `skills/`, `install.sh`, de-path docs, submodule | each skill triggers + works e2e | relink old absolute paths |
| **D. Infra + docs** | compose, systemd, docs/* | `docker compose up` healthy; `systemctl --user start` clean | additive |
| **E. CI + release** | GitHub Actions, security.md, notices | CI green; `search-gateway version` | n/a |
| **F. Acceptance** | §18 checklist | all pass | tag + push |

Parallelizable: A ↔ C (scaffold vs skill-doc edits). D/E/F sequential.

---

## 17. Risk register

| Risk | L | I | Mitigation |
|------|---|---|-----------|
| Cutover breaks OpenCode MCP | low | high | B = one-line revert; editable install keeps old path alive |
| Model download flakiness (bge-m3) | med | med | pinned revisions; tier-1 needs no models; `warm` documented |
| Saved-query loss on Redis reset | low | med | enable AOF; document backup |
| Skill path drift after de-pathing | low | low | scripts self-resolve; `install.sh` idempotent |
| Submodule breaks report | low | med | pin submodule commit; report falls back to fenced source |

---

## 18. Verification checklist (all must pass)

**Server (standalone)**
- [ ] `pip install .` in a clean venv; `search-gateway --help` works.
- [ ] `search-gateway serve` answers `tools/list` (14 tools incl. `saved_queries`).
- [ ] `pytest -m "not slow"` green on 3 Python versions.
- [ ] `search-gateway doctor` → 18 sources; Redis/models/academic/ledger health present; exit 0.
- [ ] stdio handshake from a non-OpenCode client (Claude Code).

**Cross-client + skills**
- [ ] OpenCode: 14 tools after config rewrite; a `search` returns fused results.
- [ ] deep-research → ledger → `lint` passes.
- [ ] report → charts + diagram-design → `report.md` → PDF/DOCX/HTML zip.
- [ ] monitor → `saved_queries` save/run/diff.
- [ ] research-rubric → `eval_run.py` scores.

**Infra**
- [ ] `docker compose up` → Redis + SearXNG healthy; `doctor` shows both OK.
- [ ] systemd unit survives a client disconnect (models stay warm).

**Hygiene**
- [ ] `git status` clean of `*.env`/keys/`.pytest_cache`/`__pycache__`.

---

## 19. Acceptance criteria (definition of done)

- `search-gateway doctor` exits 0; `search-gateway check` gates the systemd unit.
- A **non-OpenCode client** lists the same 14 tools.
- `pytest -m "not slow"` green on `3.11/3.12/3.13`.
- `docs/api/tools.md` + `docs/meta-schema.md` match the live `tools/list` (contract test).
- Repo pushed public, tagged `v0.2.0`, MIT license, no secrets in history.

---

## 20. Ongoing management (post-decoupling)

- **Redis/SearXNG** — docker-compose or systemd; health via `doctor()`.
- **Chromium + opencli** — relaunch cmd documented (social only).
- **Model cache** — `~/.cache/huggingface`; bge-m3 lazy (CJK runs); revisions pinned.
- **DeepSeek key** — env-file rotation, never committed.
- **Versions** — bump `__version__` + `CHANGELOG.md` every release.
- **Contract** — any tool-surface/`meta` change updates `docs/api/tools.md` + `meta-schema.md` first.

---

## 21. File inventory (exact)

| File | New/Edit/Move | Purpose |
|------|---------------|---------|
| `search_gateway/cli.py` | new | serve/doctor/check/version/warm |
| `search_gateway/server.py` | edit | `def main()` |
| `search_gateway/config.py` | edit | `*_REVISION` pins |
| `pyproject.toml` | edit | deps + `[project.scripts]` + extras + markers |
| `.gitignore`, `LICENSE`, `.env.example`, `CHANGELOG.md`, `mcp.json`, `install.sh` | new | hygiene + entry |
| `README.md` | rewrite | standalone-first quickstart |
| `docs/{config-reference,deployment,architecture,mcp-registration,security}.md`, `docs/api/tools.md` | new | canonical docs |
| `docs/meta-schema.md`, `docs/history/{TODO.md,tasks/}` | move | contract + archaeology |
| `infra/{docker-compose.yml,Dockerfile,systemd/search-gateway@.service}` | new | infra |
| `.github/workflows/ci.yml` | new | CI |
| `tests/{test_cli,test_mcp_handshake,test_contract,test_models}.py` | new | (4 files; 2 exist) |
| `skills/**` (5 skills) | move + edit | de-path docs |
| `~/.config/opencode/opencode.jsonc` | edit | `command` → `["search-gateway"]` |
