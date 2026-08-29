# PHASE 8 — Post-Gatekeeper Consolidation Plan

*Companion to [PLAN.md](PLAN.md) + [LESSONS.md](LESSONS.md). Status:
APPROVED for execution (KBJ, 2026-08-23) — scope = Plans 1, 2, 3, 5, 6, 7.
Plans 4/8/9 (proxy pilot + Camoufox cutover) are **excluded** by KBJ and
remain parked until funded.*

---

## 1. Scope at a glance

| # | Plan | Kind | Release |
|---|------|------|---------|
| 1 | **Baidu hot-board repair** (R12 — live-broken) | code fix | 0.4.3 |
| 2 | **Zhihu hot-list source** (R11 — anonymous endpoint verified) | new source | 0.4.3 |
| 3 | Stealth-engine insurance matrix (R2) | doc | 0.4.3 |
| 5 | Douyin/XHS deferral decision (ADR) | doc | 0.4.3 |
| — | **D7.3 legacy flat-path removal** (scheduled for 0.4.3 by the handoff) | code | 0.4.3 |
| 6 | systemd service enablement (ops) | ops batch | — |
| 7 | L3 kernel-filter install (ops) | ops batch | — |
| 4/8/9 | Provider grammar / proxy pilot / Camoufox cutover | **PARKED** | — |

---

## 2. Research session (2026-08-23, executed before this plan)

All findings verified live from this machine or via the gateway's fused
search (LESSONS.md §1.5 conventions).

### 2.1 Live endpoint probes (read-only, this machine)

| Probe | Result |
|-------|--------|
| `top.baidu.com/api/board?platform=wise&tab=realtime` | HTTP 200. **Structure changed**: `data.cards[0] = {component:"tabTextList", content:[{content:[51 items]}]}`; items = `{isTop, index, url, word, hotTag, newHotName, newHotTag}`. **No `hotScore`.** The shipped parser reads `cards[]→word/hotScore` → **silent empty results. Confirmed broken.** |
| `www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc` | HTTP 200, 50 items, `Title`/`HotValue`/`Url`/`Label` — **parser fields match. Confirmed working.** |
| `api.zhihu.com/topstory/hot-list?limit=30` | **HTTP 200 anonymous.** `data[].target{title, url(api.zhihu.com/questions/<id>), excerpt, answer_count, follower_count, created}`. **30-item cap** (limit=50/100 still 30). No heat field — rank is the heat proxy. |
| `www.zhihu.com/api/v3/feed/topstory/hot-lists/total` | HTTP 401 `AuthenticationError` — cookie-gated (confirms the current search_v3 gating; the hot-list endpoint is the anonymous win). |

### 2.2 Fused-research findings

- **Baidu `tabTextList` shape is the current documented 2026 structure** —
  multiple independent sources describe the nested `cards[].content[].content[]`
  layout with `isTop`/`url`/`word`; our live capture matches. (A marketplace
  API description mentions `hot_score`/`rank` for a *different* endpoint —
  the raw board uses `hotTag`/`newHotName`.)
- **Zhihu hot list**: "no login or API key required" per independent
  scrapers/Apify; per-endpoint rate-limit specifics undocumented → rely on
  existing pacing + jitter + negative cache; UA + `Referer:
  https://www.zhihu.com/hot` + `x-requested-with: fetch` headers match the
  browser surface.
- **nodriver vs Patchright**: 7 anti-detect browsers × 31 Cloudflare targets —
  **only nodriver passed every gate clean**; Patchright included, no clean
  pass. Both remain 2026-recommended. Camoufox stays primary (D2); nodriver
  is the documented fallback.
- **XHS (2026 state)**: x-s/x-t/x-s-common required on
  `edith.xiaohongshu.com`; obfuscated `window._webmsxyw`; **drifts
  periodically** (replayed headers fail 461/sign-error); **since ~Mar 2026
  data APIs reject the `XYS_` format with HTTP 406**. Hostile to maintain.
- **Douyin**: x-gorgon is a 6-header suite (X-Gorgon/X-Argus/X-Khronos/
  X-Ladon/X-Helios/X-Medusa); implementations exist (unicorn emulation +
  JNI); difficulty very high; 2026 state unconfirmed. Deferred (D3) holds.
- **Camoufox**: `proxy` + `geoip` params on `AsyncCamoufox`; `geoip`
  recommended when proxied (TZ/locale inference) — recorded for Plan 9 when
  unfunded.
- **IPRoyal**: residential from $1.75/GB; sticky up to **7 days**; format
  `HOST:PORT:USERNAME:PASSWORD`; session control via the password segment
  (grammar differs from our username-based auto-build → verbatim-username
  escape covers it). Recorded for Plan 4 when funded.
- **SOAX**: 155M+ IPs, sticky + geo-targeting confirmed; grammar/pricing
  need official-docs fetch at pilot time (Plan 4).

### 2.3 Machine facts (this machine, verified)

- systemd **258** → `LoadCredential=` (≥247) and user-scoped encrypted creds
  (≥256) both fine; user manager running.
- **No `/etc/nftables.conf`** → nft rules do NOT survive reboot (persistence
  is a design input for Plan 7).
- **`sudo` requires a password** → automated rule loading needs a sudoers
  drop-in (operator action) or manual one-time load.
- Vault: `profiles/kaiser/{twitter.env, deepseek.env}` migrated (0.4.1);
  **`proxy.env` absent** → the hardened unit's `LoadCredential=proxy.env`
  would fail startup → create an empty 0600 proxy.env (vault layout
  completion).
- Service `kortex-search@8765.service` never enabled.

---

## 3. Release 0.4.3 — "CN truth + vault finalization" (code)

### 3.1 Plan 1 — Baidu hot-board repair

**Goal:** restore the realtime board; make any future shape drift loud.

**Design (engineered):**
- Dual-shape parser in `sources/baidu.py`:
  1. legacy: `data.cards[]` with `word`/`hotScore` directly;
  2. current: flatten `data.cards[].content[].content[]` — items carry
     `word`, `url`, `index` (string → int), `hotTag` (heat bucket string),
     `newHotName` (`热`/`新` → is_hot/is_new), `isTop` (pinned flag).
- **Shape-drift guard** (the doctrine fix): if the response has `cards`
  present but *zero* parseable items across both shapes → raise
  `SourceError("baidu board shape drift …")` — visible in doctor/envelope,
  never a silent empty. A genuinely empty `cards==[]` stays an empty result.
- Fixtures: today's live capture → `tests/fixtures/platforms/baidu_board.json`
  (+ inline legacy-shape fixture); hermetic parser tests for both shapes,
  drift guard, meta mapping, query filtering.
- Meta mapping: `hotTag`→`heat`, `newHotName`→`is_hot`/`is_new`,
  `index`→`rank`, `isTop`→`pinned`.

**AC:** baidu returns ≥30 board items live; legacy fixture parses; drift
guard raises on shape mismatch; suite green.

### 3.2 Plan 2 — Zhihu hot-list source (registry 22 → 23)

**Goal:** zhihu contributes zero-cookie (hot list) alongside the
cookie-gated search.

**Design (engineered):**
- New `sources/zhihu_hot.py`, `ZhihuHotSource` (`name="zhihu_hot"`,
  `source_type="forum"`), CN-gated like the rest of the tier.
- Endpoint `https://api.zhihu.com/topstory/hot-list?limit=min(limit,30)`;
  headers: desktop UA, `Referer: https://www.zhihu.com/hot`,
  `x-requested-with: fetch`.
- Parser: `data[].target` → Result; **URL rewrite**
  `api.zhihu.com/questions/<id>` → `www.zhihu.com/question/<id>`; meta:
  `answer_count`, `follower_count`, `rank` (position), `created` → published.
- Query filtering: substring match on title (consistent with baidu/toutiao);
  empty query → top of the board.
- Same shape-drift guard (200-but-unparseable → loud SourceError).
- Registry/contract in ONE commit: `ALL_SOURCES` +23, `SOURCE_TIERS["zhihu_hot"]
  = ("api",)`, `FALLBACK_CHAINS["zhihu_hot"] = ["zhihu-hot-api", "skip"]`,
  `health.check` 22→23, `tests/test_contract.py` EXPECTED_SOURCES +23,
  docs (project-map, README source table, api/tools, config-reference CN
  tier, deployment "22→23 sources" mentions, faq if present).
- Fixture: today's live capture → `tests/fixtures/platforms/zhihu_hot.json`.

**AC:** anonymous hot-list returns 30 ranked items; contract golden-updated;
fixtures green; live `doctor` probe reports `zhihu_hot: ok (30)`.

### 3.3 D7.3 — Legacy flat-path removal (scheduled 0.4.3)

**Goal:** close the one-release deprecation window opened in 0.4.1.

**Design:**
- `extract/vault.py`: `env_file_for(kind)` drops the legacy fallback (vault
  path only); remove `_legacy_used` tracking + the deprecation warning;
  `status()` drops the `legacy_in_use` key. `migrate()` KEEPS reading
  `LEGACY_PATHS` (it is the migration *source* for machines that never
  migrated — documented: migrate before upgrading).
- Tests: replace legacy-fallback tests with "legacy no longer honored"
  semantics; keep migrate tests; update the vault doctor-shape assertions.
- Docs: .env.example auth comment, config-reference auth section,
  deployment §3.1, security.md secret-handling — all updated to "removed in
  0.4.3".

**AC:** env_file_for ignores legacy paths; migrate still works from legacy;
suite green.

### 3.4 Plan 3 — Stealth-engine insurance matrix (doc)

`docs/extraction/stealth-matrix.md`: nodriver vs Patchright vs Camoufox ×
(Cloudflare/DataDome/Turnstile success, CDP control, session-auth support,
proxy support, maintenance status, adoption triggers). Recorded: nodriver
clean pass on 31-target benchmark; Patchright no clean pass; Camoufox
primary (D2). Fixture-vault entries (recorded challenge pages) deferred to
DR-1 — noted honestly in the doc.

### 3.5 Plan 5 — Douyin/XHS deferral ADR

`docs/adrs/0007-cn-signing-deferred.md`: hostile maintenance economics
(XHS drift + 406 since Mar 2026; Douyin 6-header emulation, very-high
difficulty, unconfirmed state) → deferred with explicit revival triggers:
(a) proxy tier funded AND (b) verified 2026 signing implementation AND
(c) a concrete research need. Registry stays 23 (was: 22 + zhihu_hot;
douyin/xhs still out).

### 3.6 Release mechanics (0.4.3)

- Version `0.4.3`; CHANGELOG; docs sync (config-ref count check, README,
  project-map, deployment, api/tools, security, faq, PLAN board, LESSONS
  journal incl. this research session + R11/R12 closure).
- Verify: `pytest -m "not slow"` green, ruff clean, coverage ≥85%, contract
  green, live doctor probes (baidu/zhihu_hot), crg refresh.
- Commit + push; **KBJ approval gate before the ops batch.**

---

## 4. Ops batch (no version bump; after 0.4.3 approval)

### 4.1 Plan 6 — systemd service enablement

1. Create `~/.config/kortex-search/gateway.env` (0600): non-secret config +
   `KORTEX_SEARCH_HTTP_TOKEN` (long random; required for HTTP transport).
2. Complete the vault layout: empty `profiles/kaiser/proxy.env` (0600) so the
   unit's `LoadCredential=proxy.env` resolves.
3. `systemctl --user enable --now kortex-search@8765.service`; verify with
   `systemctl --user status`, journal, and a token-authenticated HTTP call.
4. Coexistence: stdio client-spawned instances still work (share Redis;
   no port conflict).
5. Note: unit's `ExecStartPre=harden --install` writes the ruleset + marks
   pending (no sudo) — it does NOT load the table without sudo (Plan 7).

**AC:** service up, warm models, doctor-over-HTTP with token, survives
restart.

### 4.2 Plan 7 — L3 kernel-filter install

1. Prepare: `kortex-search harden --install` (writes the ruleset for the
   current cgroup + pending state; idempotent).
2. **Operator action (sudo password):** one copy-paste command —
   `sudo nft -f ~/.config/kortex-search/ks-egress.nft` (exact command
   delivered at execution; never handled by the agent).
3. Verify: `harden --status` → installed+covered; `harden --check` →
   enforceable; one browser-tier source query returns results (or the
   explicit refusal message pre-install).
4. **Reboot persistence (engineered decision):** recommend the sudoers
   drop-in `kortex-search-nft` (NOPASSWD for exactly
   `nft -f ~/.config/kortex-search/ks-egress.nft`) so the unit's
   ExecStartPre auto-loads on every start — created as a documented snippet
   for the operator to place (root-owned file), OR option A (manual re-run
   after reboot) if the operator prefers zero sudoers edits. Decision
   recorded in LESSONS.
5. Enforcement end-to-end: with the table live, browser-tier ops run; with
   it absent and `KORTEX_SEARCH_HARDEN=required`, the explicit
   `blocked (egress-unhardened)` message (already unit-tested).

**AC:** `harden --status` installed+covered; persistence choice recorded;
browser tier operational.

---

## 5. Sequencing & gates

```
[1] PHASE8-PLAN.md written (this file)
[2] Release 0.4.3  → verify → commit+push →  ⛔ KBJ approval
[3] Ops batch      → service + filter →     ⛔ KBJ approval (sudo command)
[4] LESSONS/PLAN board update; crg refresh; clean tree
```

Parked (Plans 4/8/9) revive triggers recorded in LESSONS.md so nothing is
lost: proxy funding approval → Plan 4 → Plan 8 → Plan 9.

---

## 6. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Baidu changes shape again | drift guard makes it loud + fixture regression; dual-shape parser |
| zhihu hot-list dies/locks | negative cache + block detection; source degrades loudly via available() |
| Registry growth breaks clients | contract test + health.check updated in the SAME commit (doctrine) |
| Legacy-path removal breaks a never-migrated machine | migrate() kept as the migration path; docs say "migrate before upgrading" |
| nft rules vanish on reboot | persistence decision (sudoers drop-in or documented re-run) in Plan 7 |
| Service enablement trips on missing credential file | empty 0600 proxy.env created as vault-layout completion |
| sudo unavailability blocks the filter | single operator command delivered; everything else automated |
