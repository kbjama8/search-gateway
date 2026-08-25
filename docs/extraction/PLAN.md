# PROJECT GATEKEEPER — Assignment & Plan

search-gateway v0.4 extraction-architecture overhaul.

| Field | Value |
|-------|-------|
| Status | **IN PROGRESS** |
| Author | Kaiser Chen (extraction architect) |
| Opened | 2026-08-22 |
| Companion | [LESSONS.md](LESSONS.md) — running research journal |
| Contract impact | minor bump → **0.4.0** (envelope gains optional fields, source count grows) |

## 1. Mission

Rebuild the gateway's extraction layer — how it reaches, reads, and parses
the web's hostile surfaces — to 2026 field standards, without burning the
persona masks and without violating the repo's own doctrine (zero paid APIs
by default, explicit degradation, calibrated honesty).

The problem, in one line: **the current browser layer is a single shared
Chromium bridge with no fingerprint control, no profile isolation, no block
detection, and no proxy path** — every modern anti-bot control plane is
designed to catch exactly that. The current parser layer is regex-over-CLI
output with no fixture coverage, so a platform's HTML change silently reads
as an empty result.

## 2. Doctrine & boundaries

Non-negotiable, applies to every phase:

1. **Public-content research only.** We extract what a logged-out or
   burner-authenticated visitor can see. No private data, no gated content
   circumvention beyond the burner model the repo already documents.
2. **No credential abuse, no account fabrication at scale, no captcha-solving
   services.** Captcha → skip + flag to operator. Solving is fragile, a tell,
   and a legal line.
3. **Consistency-first stealth.** One persona = one coherent story (rendering,
   hardware, locale, network). Modest randomization. No per-request tricks.
4. **Pacing is the cheapest anti-detection.** The existing rate-limit +
   daily-budget machinery stays, gains jitter, and extends per-profile.
5. **Everything env-gated, default OFF** for risky capabilities (proxy,
   stealth engine, impersonation, CN sources). The repo's existing pattern.
6. **Graceful degradation, never silent failure.** Envelope must name the
   state: `extract{tier, engine, profile?}`, `blocked?`, `auth?`.
7. **Contract-tested.** Every tool/source/envelope change bumps the golden
   contract test in the same commit.

## 3. Locked decisions (KBJ, 2026-08-22)

| ID | Decision |
|----|----------|
| D1 | Proxies: **env-gated optional tier** — architect fully, ship disabled; funding guide provided. |
| D2 | Browser engine: **dual-path now** (OpenCLI/Chromium = authenticated sessions; Camoufox = anonymous tier, experimental opt-in) + **full Camoufox migration plan** documented. |
| D3 | CN source order: **bilibili wbi upgrade → zhihu → weibo**; baidu/toutiao hot lists ride along as free JSON wins; douyin deferred (x-gorgon signing). |
| D4 | Contract: **minor bump 0.4.0** — envelope gains `extract`/`blocked`/`auth`; 18 → 23 sources. |
| D5 | Stealth posture: **consistency-first, modest randomization.** |
| D6 | Proxy funding (2026-08-22 follow-up): provider research → shortlist + cost model in `proxy-funding-guide.md`; recommendation **IPRoyal PAYG for pilot → SOAX for the farm**. |

## 4. Intelligence brief (research state, condensed)

Full findings + sources live in [LESSONS.md](LESSONS.md). The load-bearing
facts:

- **playwright-stealth is dead** (unmaintained since 2023; fails 2024+
  behavioral checks). 2026 leaders: **nodriver** (0 hard blocks/31 targets),
  **Camoufox** (Firefox ESR; 36/40 vs 24/40 on DataDome), Patchright.
- **X** moved to metered $0.005/post-read (Feb 2026); **Reddit** requires
  OAuth from hosted netblocks and gates bulk export; **YouTube** requires
  externally-provisioned **PO tokens** in yt-dlp.
- **Bilibili** requires **wbi signing** (w_rid/wts, dynamic keys) + buvid3
  cookie since 2023 — documented in `bilibili-API-collect`. **XHS** requires
  **x-s/x-t** header signing.
- **Fingerprint detection is a coherence check across four families**
  (rendering, hardware, locale, network). The classic kill: IP in one country,
  TZ/language in another. Fix: derive the fingerprint bundle from the egress
  geo at sticky-IP provision time.
- **Content extraction**: Trafilatura F1 0.937 / precision 0.978 (best
  precision, local); Jina Reader best on SPAs (21/25, ties Firecrawl);
  Readability best recall 0.929. → multi-stage `read_url`.
- **Proxy market 2026**: budget $1.75–3.50/GB (IPRoyal, Webshare, ProxyHat),
  mid $3.50–6/GB (SOAX — best geo precision + clean pool; Decodo ex-Smartproxy;
  NetNut), enterprise $8.50–12/GB (Bright Data, Oxylabs). Mobile $10–30/GB —
  not needed. Datacenter IPs instantly blocked on CF/Akamai targets.
- **Cost model for our load**: daily budget 300 source-queries × ~2 MB
  browser pages ≈ 18 GB/mo worst case → **$10–90/mo; realistic $10–30/mo**
  (only browser-tier + CN sources route through proxies).

## 5. Architecture phases

Each phase ships with acceptance criteria; no phase merges before its AC is
green. Feature flags default OFF unless stated.

### Phase 0 — Ops hygiene
- [ ] Kill stale `search-gateway` processes (3 found 2026-08-22); single
  systemd-managed instance; PID lock in the unit.
- [ ] `.env.example` + README: Redis `requirepass` note (B6 hardening).
- [ ] Baseline: full fast suite + `bench.py search` numbers recorded here.
- **AC:** one gateway process under systemd; suite green; baseline recorded.

### Phase 1 — Extraction tiering
`search_gateway/extract/router.py` + `scheduler.py`
- [ ] `TierRouter`: A public-API (cost 1) / B CLI (cost 3) / C browser
  (cost 10); extends `FALLBACK_CHAINS` semantics; cheapest-tier-first.
- [ ] `scheduler`: per-profile locks + global browser budget replace
  `OPENCLI_LOCK`; ±30% jitter in `ratelimit.wait_if_needed`.
- [ ] Envelope: `extract: {tier, engine, profile?}`.
- **AC:** `DEFAULT_SOURCES` behavior unchanged; scheduler unit tests
  (RedisStub); envelope field in contract test.

### Phase 2 — Profile farm & session manager
`search_gateway/extract/profiles.py`
- [ ] (platform × persona × purpose) registry; persistent `user-data-dir`
  sessions survive restarts.
- [ ] Health state machine `healthy → throttled → cooldown → quarantined`;
  exponential-backoff cooldowns; profile-level reliability feeds weighted RRF
  via `(source, profile)` seam in `fusion.py`.
- **AC:** profile manager unit tests; rotation logic tests; no default-fan-out
  change.

### Phase 3 — Stealth layer (dual-path)
`search_gateway/extract/fingerprints.py` + Camoufox adapter
- [ ] Path 1: OpenCLI/Chromium authenticated tier (unchanged surface).
- [ ] Path 2: Camoufox adapter (`Source`-contract), `SEARCH_GATEWAY_STEALTH`
  flag, experimental.
- [ ] Fingerprint bundles: persona-derived JSON; coherence across all four
  families; geo-alignment hook consumed by the proxy engine (Phase 3.5).
- [ ] Migration track: `docs/extraction/camoufox-migration.md` (parity →
  dual-run → per-platform cutover → OpenCLI retirement).
- **AC:** adapter unit tests with mocked Camoufox import; bundle validation
  (schema + coherence lint) tests; migration doc present.

### Phase 3.5 — Proxy subsystem (env-gated, default OFF)
`search_gateway/extract/proxies.py`
- [ ] Provider-agnostic gateway interface; username-targeting grammar
  (`country/sid/ttl`), sticky-per-profile sessions, TTL-bound.
- [ ] Geo-consistency engine: at sticky-IP provision, resolve egress geo →
  derive TZ/locale/language bundle → write into profile fingerprint bundle.
- [ ] Per-IP health scoring → feeds profile health + rotation.
- [ ] Config: `SEARCH_GATEWAY_PROXY_ENABLED=0` + provider/credentials/geo/
  sticky-TTL knobs. Secrets via `~/.agent-reach/` env files, never inline.
- [ ] `docs/extraction/proxy-funding-guide.md`: provider table, cost model,
  procurement checklist, setup walkthrough, gotchas.
- **AC:** unit tests (provider mock); geo-bundle derivation tests; funding
  guide present; zero behavior change when disabled.

### Phase 4 — Block & challenge intelligence
`search_gateway/extract/detectors.py`
- [ ] Signature matchers: CF (`__cf_bm`, `cf_chl_*`, "Just a moment",
  Turnstile), DataDome, PerimeterX/HUMAN, Kasada (`x-kpsdk-*`), Akamai
  (`ak_bmsc`), Arkose, CN equivalents (Bilibili 风控, XHS 操作过于频繁,
  Zhihu 人机验证).
- [ ] Classification ladder: transient / IP-level / account-level → act:
  retry-once → throttle → rotate profile → rotate IP → quarantine +
  negative-cache → envelope.
- [ ] Per-platform circuit breaker (≥N profiles blocked → stop for T).
- [ ] `blocked:` + `auth:` envelope fields; captcha → skip + flag.
- **AC:** detector unit tests on fixture HTML/headers; ladder tests; envelope
  fields in contract test.

### Phase 5 — Parser intelligence
`search_gateway/extract/parse.py` + `tests/fixtures/platforms/`
- [ ] Multi-shape pipeline: JSON → JSON-LD → CSS → regex → gated LLM-assist
  (validated), canonical `Result`/`meta` output.
- [ ] Fixture vault: recorded 2026 samples per platform; hermetic parser
  regression tests.
- [ ] `read_url` multi-stage: Jina (SPA) → Trafilatura (precision) →
  readability-lxml (recall) → html2text; per-stage telemetry.
- **AC:** fixture tests green; parser success-rate telemetry wired to stats.

### Phase 6 — CN expansion (D3 order)
- [ ] bilibili wbi upgrade: dynamic key fetch + mixin table + w_rid/wts +
  buvid3 cookie; fixtures.
- [ ] zhihu (new): web search API + hot list; cookies-gated.
- [ ] weibo (new): m.weibo.cn ajax + hot search; config-gated.
- [ ] baidu/toutiao hot lists (free public JSON, no auth).
- [ ] Register all in `ALL_SOURCES`; `FALLBACK_CHAINS` entries; doctor probes;
  negative-cache integration.
- **AC:** 23 sources; contract test updated; per-source parser fixtures.

### Phase 7 — Containment & observability
- [ ] Browser tier sandboxing: `NoNewPrivileges`, `PrivateTmp`, egress
  blocked to Redis/SSH-agent/Docker-socket/metadata; per-profile network
  namespaces (systemd or firejail).
- [ ] Per-profile secret vault under `~/.agent-reach/profiles/` (0600).
- [ ] Block/health/tier telemetry → stats reservoir → `doctor` section;
  `bench.py` browser-tier benchmarks.
- **AC:** sandbox unit smoke; doctor shows new sections; bench output.

### Phase 8 — Verification & rollout
- [ ] Contract tests: 23 sources, 14 tools (unchanged), envelope 0.4.
- [ ] Hermetic + slow-marked live tests; full suite + ruff + coverage gate.
- [ ] Docs: project-map, architecture, config-reference, CHANGELOG, api/tools;
  version bump `0.4.0`.
- **AC:** `pytest -m "not slow"` green; ruff clean; coverage ≥85%; graph
  refreshed; CHANGELOG entry.

## 6. Execution order & dependencies

```
Phase 0 ─┬─ Phase 1 ── Phase 2 ── Phase 3 ── Phase 3.5
         │                                  │
         ├─ Phase 5 ── Phase 6 (bilibili needs parse fixtures)
         └─ Phase 4 ── (independent; feeds 2/3/3.5 health signals)
Phase 7 after 3/3.5 (sandboxing the browser tier)
Phase 8 closes.
```

Critical path: 0 → 1 → 2 → 3 → 3.5 → 7 → 8. Value path: 5 → 6 (immediate
reliability wins) runs parallel to the critical path.

## 7. Research agenda

Ledger-based deep-research runs (executed with the `deep-research` skill
where the gateway is reachable; otherwise the agent-reach fallback channel):

| ID | Topic | Feeds |
|----|-------|-------|
| DR-1 | 2026 anti-bot control planes & stealth stack verification (Camoufox/nodriver/Patchright capability matrix; CF/DataDome/Kasada signals; CN equivalents) | Phase 3/4 |
| DR-2 | Proxy engineering: residential/ISP/mobile tiers, sticky sessions, geo-consistency, health scoring, cost math | Phase 3.5 |
| DR-3 | Platform playbooks 2026: X, Reddit, YouTube PO-token provisioning, IG/FB access + ban signals | Phase 4/6 |
| DR-4 | CN platforms: bilibili wbi+buvid3, XHS x-s/x-t, zhihu search API, weibo ajax, douyin signing | Phase 6 |
| DR-5 | Content extraction on our target corpus (CJK included): Trafilatura/Jina/Readability | Phase 5 |
| DR-6 | Browser containment & drive-by risk: firejail/bubblewrap, CDP security | Phase 7 |

## 8. Deliverables index

| File | Phase | Kind |
|------|-------|------|
| `docs/extraction/PLAN.md` | — | this assignment |
| `docs/extraction/LESSONS.md` | — | running research journal |
| `search_gateway/extract/__init__.py` + `router.py` + `scheduler.py` | 1 | code |
| `search_gateway/extract/profiles.py` | 2 | code |
| `search_gateway/extract/fingerprints.py` + `camoufox.py` | 3 | code |
| `docs/extraction/camoufox-migration.md` | 3 | doc |
| `search_gateway/extract/proxies.py` | 3.5 | code |
| `docs/extraction/proxy-funding-guide.md` | 3.5 | doc |
| `search_gateway/extract/detectors.py` | 4 | code |
| `search_gateway/extract/parse.py` + `tests/fixtures/platforms/` | 5 | code + fixtures |
| `search_gateway/sources/{bilibili,zhihu,weibo,baidu,toutiao}.py` | 6 | code |
| `search_gateway/extract/http.py` | 3 | code (impersonation seam) |
| config.py v0.4 block + `.env.example` updates | all | code |

## 9. Status board

- [x] Plan approved by KBJ (2026-08-22); decisions D1–D6 locked
- [x] PLAN.md + LESSONS.md drafted
- [x] Phase 0 — ops hygiene (stale processes killed; baseline 135 green)
- [x] Phase 1 — extraction tiering (`extract/router.py`, `scheduler.py`;
      envelope `extract{}`; browser budget default 1 preserves old behavior)
- [x] Phase 2 — profile farm (`extract/profiles.py`: registry + health
      state machine, Redis-backed, RedisStub-tested)
- [x] Phase 3 — stealth layer scaffolding (`extract/fingerprints.py` +
      `camoufox.py`, gated; `extract/http.py` impersonation seam;
      `camoufox-migration.md` written)
- [x] Phase 3.5 — proxy subsystem (`extract/proxies.py`: env-gated, sticky
      sessions, geo-consistency engine; `proxy-funding-guide.md` written)
- [x] Phase 4 — block & challenge intelligence (`extract/detectors.py`;
      base.py `_blocked_error` — blocks fail fast, never retried; envelope
      `blocked[]` + `auth{}`)
- [x] Phase 5 — parser intelligence (`extract/parse.py` multi-shape ladder;
      read_url multi-stage Jina→Trafilatura→readability; fixtures in
      test_sources_parsers)
- [x] Phase 6 — CN expansion: **bilibili wbi** (canonical-example-verified),
      **zhihu**, **weibo**, **baidu**, **toutiao**; registry 22 sources
- [x] Phase 7 — containment & observability — **COMPLETE (0.4.1 `3f79e15` +
      `0.4.2` `8d1601e`); see [PHASE7-HANDOFF.md](PHASE7-HANDOFF.md)**
- [x] Phase 7.1 (0.4.1) — **L1 egress floor** (`extract/egress.py`, pre-nav +
      post-redirect, IMDS/RFC1918/CGNAT, local-infra exemption, default ON) +
      **secrets vault** (`extract/vault.py`, D7.3 full migration run on this
      machine, `vault migrate|status`, hygiene) + **block telemetry**
      (`stats.record_block`, doctor sections egress/vault/blocks/profiles);
      config 79 vars; 250 fast tests green, ruff clean, coverage 85.6%
- [x] Phase 7.2 (0.4.2) — **L2 forced-proxy** for the anonymous tier
      (`egress.EgressProxy`, loopback CONNECT, floor-composed, residential
      chaining, Camoufox flags, D7.2) + **mandatory L3 kernel filter**
      (`extract/harden.py` + `harden` CLI, nftables cgroupv2 per-scope DROP,
      golden ruleset test, `blocked (egress-unhardened)` enforcement, D7.1) +
      **bench browser tier** (slow-marked) + **hardened systemd unit**
      (LoadCredential, NoNewPrivileges, ProtectSystem=strict, IPAddressDeny);
      config 82 vars; 296 fast tests green, ruff clean, coverage 86.8%
- [x] Ops batch (PHASE8 Plans 6-7) — systemd service ENABLED + verified
      (HTTP + auth + session); L3 filter LIVE via the companion loader unit
      (`search-gateway-harden.service`, sandbox-safe by design); reboot
      persistence via the sudoers drop-in; see LESSONS §2026-08-25 (ops)
- [x] Live smoke tests (2026-08-25) — browser tier (reddit/twitter via
      opencli), CN tier (zhihu_hot/baidu/toutiao boards), anonymous tier
      (Camoufox L2+L3, STEALTH on); four bugs fixed (expansion provenance,
      banner-noise parse, None snippets, camoufox API contract) — see
      LESSONS §2026-08-25 (smoke)
- [x] Phase 8 follow-ups (0.4.3, `PHASE8-PLAN.md`) — baidu shape repair +
      drift guard, zhihu_hot source (registry 23), D7.3 legacy removal,
      stealth-matrix doc, ADR-0007 (douyin/XHS deferral); 307 fast tests
      green, ruff clean, coverage 86.8%
- [x] Phase 8 (partial) — contract tests 23 sources, envelope 0.4 fields,
      config-reference/api-tools/README/architecture/project-map/faq/
      deployment/security updated, CHANGELOG 0.4.0, version bumped

> Note: plan predicted 23 sources; actual is **23** (douyin + XHS deferred
> per D3/ADR-0007; zhihu_hot joined in 0.4.3 — when XHS/douyin signing lands
> the registry grows again).

## 10. Open questions

| Q | Owner | Note |
|---|-------|------|
| Stale-process cleanup mechanics: systemd unit ownership of the gateway | KBJ | unit exists in `infra/systemd/`; verify enablement |
| Proxy pilot budget approval (if/when enabled) | KBJ | guide gives $10–30/mo realistic figure |
| Camoufox cutover per-platform sign-off | KBJ | migration doc defines the go/no-go gates |

## 11. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Ban-rate on burner accounts during dual-path testing | new engines run on *fresh* burner contexts, never the existing authenticated profiles; budgets apply |
| Contract churn breaking clients | all envelope changes additive + optional; contract test updated in same commit |
| Proxy spend surprise | default OFF; cost model in funding guide; per-IP health scoring drops spend on dead IPs |
| CN signing drifts (wbi/x-s rotate) | fixtures + negative caching + `doctor` auth-tier reporting; DR-4 keeps the implementations current |
| Drive-by/containment gaps in browser tier | Phase 7 sandboxing before any new browser engine goes beyond experimental flag |
