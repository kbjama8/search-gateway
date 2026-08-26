# PROJECT GATEKEEPER — Lessons Journal

Running research journal for the extraction-architecture overhaul. Companion
to [PLAN.md](PLAN.md).

**Conventions:** every entry is dated, carries its source (URL), states its
implication for our design, and is tagged with calibrated confidence:
`verified` (demonstrated), `suggests` (partial evidence), `needs-verification`
(claim seen, not yet checked). The repo's own rule applies here too: *if the
sources don't answer it, say so rather than guessing.*

---

## 1. Field intelligence — anti-bot & stealth (2026)

### 1.1 playwright-stealth is dead; three tools replaced it
**2026-08-22 · needs-verification (multiple vendor blogs, no independent repro)**

- `playwright-extra-plugin-stealth` has had no meaningful update since
  March 2023; its patches target Chrome 109–112-era detection patterns and
  fail modern Cloudflare/DataDome/PerimeterX behavioral checks.
- 2026 leaders: **nodriver** — claims 0 hard blocks across 31 targets
  because it attaches via CDP without leaving the automation-protocol trace
  that WebDriver/DevTools toggles produce; **Camoufox** — Firefox ESR fork
  with built-in fingerprint randomization (DreamScrape reports 36/40 vs
  24/40 DataDome success against playwright-stealth); **Patchright** —
  maintained patched-Playwright; also CloakBrowser, RayoBrowse, scrapling.
- **Implication:** do not adopt playwright-stealth; the experimental tier is
  Camoufox; Patchright/nodriver only if CDP-level control is needed (DR-1
  verifies before integration). Keep OpenCLI for authenticated sessions.

Sources: proxycove.com/en/blog/stealth-browsers-2026-nodriver-camoufox-patchright-benchmark;
scrapewise.ai/blogs/playwright-stealth-2026; dreamscrape.app/blog/playwright-stealth-vs-camoufox;
humanbrowser.cloud/blog/playwright-stealth-not-working-2026.

### 1.2 Detection is coherence, not uniqueness
**2026-08-22 · verified (two independent analyses agree)**

- A fingerprint is a vector across four signal families: **rendering**
  (GPU/WebGL/canvas strings *and actual output*), **hardware** (concurrency,
  memory, screen, touch), **locale/environment** (TZ, `navigator.languages`,
  fonts, `Accept-Language`), **network** (IP geo, UA, TLS, header order).
- Modern detection cross-checks families for *coherence*: the classic kill is
  a spoofed UA whose claimed platform contradicts the WebGL renderer string,
  or an egress IP whose geolocation contradicts the browser TZ/locale.
  `Accept-Language` must match `navigator.languages`; mobile UA must come
  with small screen + touch events; IP geo and TZ must agree.
- **Implication:** this validates D5 (consistency-first). Architecture: one
  persona = one fingerprint bundle derived from one source of truth, with the
  network family (proxy geo) *driving* the locale family at provision time —
  never patched independently. That is the geo-consistency engine in
  Phase 3.5.

Sources: clearcotelabs.com/research/anatomy-of-a-browser-fingerprint;
browserinsight.net/blog/browser-fingerprint-consistency.

### 1.3 Bot-management targets change fast; fixture the signals
**2026-08-22 · suggests**

- Cloudflare (Bot Fight Mode + Turnstile), DataDome, PerimeterX/HUMAN,
  Kasada, Akamai, Arkose are the named 2026 control planes; each leaves
  identifiable markers (`__cf_bm`, `cf_chl_*`, `datadome`, `_px`, `ak_bmsc`,
  `x-kpsdk-*`, `x-algolia`).
- **Implication:** detectors must be fixture-driven (recorded challenge
  pages), not live-tested; DR-1 fills the fixture vault.

Source: proxycove.com comparison of anti-bots 2026.

### 1.4 Cloudflare publishes its own challenge marker
**2026-08-22 · verified (Cloudflare docs, primary)**

- Every CF challenge response carries **`cf-mitigated: challenge`** — the
  official, reliable detection header (all Challenge Page types,
  content-type `text/html`). Turnstile pre-clearance issues a persistent
  `cf_clearance` cookie.
- **Implication:** `detectors.py` checks this header first — it is the only
  vendor-published signal; everything else is heuristic.

Source: developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/.

### 1.5 Containment field state (Phase 7 research, all verified read-only)
**2026-08-22 · verified (primary sources) · actionable — decisions D7.1–D7.4**

- **firejail is rejected as the sandbox mechanism**: it is a suid binary with
  a root-escalation CVE history; its `netfilter`/`dns`/`hosts-file` primitives
  have no systemd equivalent, but systemd eBPF (`IPAddressDeny=`,
  `IPAddressAllow=`, `SocketBindDeny=`, `RestrictAddressFamilies=`) covers the
  service-level floor. **Implication:** service-level denials via the unit;
  per-process egress via nftables (below). (Sources: netblue30/firejail wiki
  "Comparison of firejail and systemd hardening options";
  fedoraproject discussion #121109.)
- **nftables supports per-process egress filtering** via
  `socket cgroupv2 level 2 "<path>"` — proven pattern from the pam_authnft
  project: systemd transient scope pins PIDs to a cgroup → nftables chain
  dispatches per-cgroup. No suid binary, no kernel module, works for ad-hoc
  processes (the browser children outlive our process; a kernel-level floor
  is the only thing that still sees them). **Implication:** L3 kernel filter
  = nft table `inet sg_egress` + cgroupv2 scope. (Sources: identd-ng/
  pam_authnft ARCHITECTURE.txt; spinics.net nftables thread.)
- **IMDS SSRF is a real incident class**: hermes-agent's browser hybrid
  routing bypassed its pre-nav guard for the whole `169.254.0.0/16` (link-
  local qualifies as "private") → IAM credential theft; their fix is an
  **always-blocked floor as an independent gate, checked pre-nav AND
  post-redirect**. **Implication:** L1 floor checks literal IPs both before
  navigation and after redirect, and blocks the *whole* link-local range, not
  just the well-known 169.254.169.254. (Source: NousResearch/hermes-agent
  PR #21228, issue #16234.)
- **Chrome 136+**: `--remote-debugging-port`/`--remote-debugging-pipe`
  require a **non-default `--user-data-dir`** (App-Bound Encryption); prefer
  `--remote-debugging-pipe` over an open port; "Chrome for Testing" is the
  automation build. **Implication:** the anonymous tier's Camoufox launches
  always carry an explicit profile dir; forced-proxy flags (below) keep the
  browser's egress inside the floor. (Source: developer.chrome.com blog,
  2025-03.)
- **systemd credentials**: `LoadCredential=`/`LoadCredentialEncrypted=` +
  `$CREDENTIALS_DIRECTORY`; systemd's own doctrine is that **env vars are NOT
  suitable for secrets** (world-readable via D-Bus, propagate across setuid
  boundaries); Issue #40333 documents the `EnvironmentFile=%d/app-secrets`
  bridge. **Implication:** the hardened unit passes the vault through
  `LoadCredential=`, and the config loader honors
  `SEARCH_GATEWAY_CREDENTIALS_DIR` so files arrive via
  `$CREDENTIALS_DIRECTORY` without ever touching the process env.
  (Sources: systemd.io/CREDENTIALS/; systemd/systemd#40333.)
- **Chromium forced-proxy egress is fully supported**:
  `--proxy-server="http://127.0.0.1:PORT"` routes everything;
  `--host-resolver-rules="MAP * 0.0.0.0, EXCLUDE 127.0.0.1"` pushes remote
  DNS through the proxy (a browser whose resolver still talks to the host DNS
  would leak the target domain). **Implication:** L2 = loopback CONNECT proxy
  in front of Camoufox; localhost is exempted so the proxy itself still
  works. (Sources: chromium net/docs/proxy.md; superuser #1812598.)

---

## 2. Proxy economics & provider landscape

### 2.1 Market tiers 2026
**2026-08-22 · verified (pricing tables) · actionable**

| Tier | Providers | Price/GB |
|------|-----------|----------|
| Enterprise | Bright Data (72M+ IPs), Oxylabs (100M+ IPs, sub-0.6s) | $8.50–12 |
| Mid-market | Decodo (ex-Smartproxy), SOAX (city/ASN geo, clean pool), NetNut (ISP-direct) | $3.50–6 |
| Budget | IPRoyal ($1.75 PAYG — cheapest entry), Webshare (dev API), ProxyHat | $1.75–3.50 |
| Mobile | (CGNAT, max anonymity) | $10–30 — **not needed** |

- **Datacenter IPs are instantly blocked on Cloudflare/Akamai targets** —
  residential/ISP only. Self-hosted datacenter proxies are not an option for
  this workload.
- **Our cost model:** DAILY_QUERY_LIMIT=300 × ~2 MB per browser page ≈ 18
  GB/mo worst case → **$32–90/mo worst, $10–30/mo realistic** (only
  browser-tier + CN sources route through proxies).
- **ISP tier (static residential)** is worth planning for authenticated
  personas later: datacenter speed + residential-trust ASN, sticky identity,
  ideal for long-running sessions.
- **Implication:** funding guide recommends **IPRoyal PAYG for the pilot,
  SOAX once the farm is live** (geo-precision + aggressive pool cleaning
  matters more than raw IP count at our scale).

Source: trustmyip.com/blog/best-residential-proxy-providers (2026-05);
ziny.io/residential-isp-mobile-proxies-which-is-best (2026-02).

### 2.2 The sticky-per-context pattern is the industry standard
**2026-08-22 · verified (reference implementation) · actionable**

- Provider gateways use a **username-targeting grammar**: credentials carry
  `country/region/city/sid/ttl` tokens; a fresh `sid` mints a pinned IP that
  persists for `ttl`; omitting `sid` = rotate-per-request.
- Reference: `playwright-proxyhat` maps **one browser context → one sticky
  residential IP**, mirrors the real-user model (a user keeps one IP for a
  session), works with Chromium/Firefox/WebKit, per-context proxy option.
- **Implication:** `extract/proxies.py` implements exactly this grammar
  provider-agnostically; browser tier uses sticky-per-profile, never
  per-request rotation; TTL bound default 30m, env-overridable.

Source: github.com/ProxyHatCom/playwright-proxyhat.

### 2.3 Which proxy type for which job
**2026-08-22 · suggests**

- Residential: bulk diversity + geo reach (2–10 Mbps, 85–95% uptime).
- ISP: speed + consistent identity (50–100 Mbps, 99%+); occasionally
  ASN-flagged by the most advanced systems.
- Mobile: only when residential fails against account-level control (IG/TikTok
  class); CGNAT makes IP bans impractical for platforms.
- **Implication:** our mix = residential for anonymous bulk (CN sources,
  X fallback) + ISP later for authenticated personas. Mobile deferred.

Source: ziny.io (above).

---

## 3. Platform playbooks

### 3.1 X/Twitter — metered API vs public-page scraping
**2026-08-22 · verified (primary pricing doc cited)**

- Feb 2026: Basic/Pro tiers closed to new developers; metered pay-per-use
  $0.005/post-read, capped 2M reads/month, no minimum.
- Public-page scraping remains the zero-cost alternative; the math flips by
  volume (API wins below ~modest volumes for field-completeness; scraping
  wins at scale and for logged-out visibility).
- **Implication:** our twitter source stays CLI+browser tiered; the API is
  not a target under the zero-paid-APIs doctrine.

Source: themineworks.com/blog/x-api-pay-per-use-vs-scraping-2026 (2026-07).

### 3.2 Reddit — browser tier confirmed for research scale
**2026-08-22 · verified (Reddit's own help center)**

- Data API requires developer approval; **IPs in hosted-provider netblocks
  must have OAuth or a logged-in session**; bulk export is limited by
  default; non-commercial research sign-up exists; commercial use needs
  permission.
- **Implication:** keep Reddit in the browser tier (OpenCLI session); the
  netblock rule means even if we added OAuth, our IP class matters — the
  proxy layer (Phase 3.5) would change that equation; note in playbook.

Source: support.reddithelp.com/hc/en-us/articles/14945211791892.

### 3.3 YouTube — PO tokens are external dependencies
**2026-08-22 · verified (yt-dlp wiki)**

- YouTube progressively enforces **PO tokens** per client type/stream
  protocol/auth state; **yt-dlp cannot generate them** — they must be
  provisioned via extractor args or a plugin (e.g., bgutil-based providers).
- **Implication:** youtube source gains a `SEARCH_GATEWAY_YOUTUBE_PO_PLUGIN`
  seam (plugin name + extractor args passthrough), env-gated; search-only
  usage may not need tokens yet, but failure mode ("Sign in to confirm you're
  not a bot") must be detected and surfaced by Phase 4 detectors.

Source: github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide; Extractors wiki.

### 3.4 Bilibili — wbi signing, exact algorithm captured
**2026-08-22 · verified (canonical doc, includes Python demo)**

- Full algorithm from `bilibili-API-collect` docs/misc/sign/wbi.md:
  1. Fetch `img_key` + `sub_key` from the **nav API** (`wbi_img.img_url` /
     `sub_url` filenames, strip `.png`; the URLs are disguised tokens — never
     fetch them). Keys rotate **daily** → cache with refresh. (Alt: bili_ticket
     endpoint.)
  2. `mixin_key` = first 32 chars of `raw_wbi_key` (img_key + sub_key
     concatenated) reordered through the 64-entry `MIXIN_KEY_ENC_TAB`.
  3. `w_rid` = MD5( url-encoded params sorted by key + `wts` (unix seconds) +
     `mixin_key` ), where encoding must match **`encodeURIComponent`**:
     uppercase percent-hex, spaces as `%20` (NOT `+`).
  4. Append `w_rid` + `wts` to the original (unsorted) query.
- Wrong/missing signature returns `{"code":0,"data":{"v_voucher":…}}` — a
  tell our detector should recognize.
- **Implication:** implement in `bilibili.py`: cached nav-key fetch (Redis,
  TTL 23h), mixin table, uppercase quote via `urllib.parse.quote(..., safe=)`
  emulation, buvid3 cookie jar. Fixture-test against the doc's worked example
  (`ea1db124af3c7062474693fa704f4ff8`).

Sources: SocialSisterYi/bilibili-API-collect docs/misc/sign/wbi.md (fetched
via fork raw); issues #631/#885/#919.

### 3.7 Zhihu — v4 search API contract captured
**2026-08-22 · verified (working third-party implementation)**

- `GET https://www.zhihu.com/api/v4/search_v3` with params `t=general, q,
  correction=1, offset, limit(≤50), lc_idx=0, show_all_topics=0`.
- **Blocks anonymous access with HTTP 401.** Requires cookies `d_c0` +
  `z_c0` (env `ZHIHU_COOKIE`), headers: desktop Chrome UA, `Referer:
  https://www.zhihu.com/search`, `x-requested-with: fetch`.
- Response: `data[].object` with `type ∈ {answer, article, question}`;
  answers carry `question{name,id}`, content, voteup_count, comment_count,
  author, url, excerpt, created_time.
- **Implication:** `zhihu.py` ships with `auth: missing` semantics (the
  LinkedIn/XHS pattern): no cookie → graceful skip + envelope `auth:
  missing`. Hot-list endpoint still unverified → parking lot.

Source: github.com/SafeRL-Lab/cheetahclaws — research/sources/zhihu.py.

### 3.8 Weibo — endpoint map captured
**2026-08-22 · verified (two independent guides)**

- **Hot search:** `weibo.com/ajax/side/hotSearch` — no login, but strict
  mobile-UA validation + visitor cookie; returns 50 ranked topics +
  `hotgovs` pinned topics. This is the free win.
- Desktop ajax (`/ajax/statuses/mymblog`, `/ajax/side/searchAll?q=`) needs a
  **`SUB` cookie** (logged-in). m.weibo.cn feeds paginate via `since_id`.
- **Implication:** weibo source = hot-search first (visitor cookie + mobile
  UA), keyword search gated on `WEIBO_SUB` cookie, config-flagged.

Sources: webscrapinghq.com/blog/weibo-scraper-guide (2026-07);
17golang.com/article/532303.html (2026-03).

### 3.9 PO-token provisioning stack
**2026-08-22 · verified (yt-dlp wiki)**

- Recommended: **bgutil-ytdlp-pot-provider** (HTTP server + docker, yt-dlp
  maintainer) as the PO Token Provider plugin; fallback
  **yt-dlp-getpot-wpc** (generates tokens in-browser); base library BgUtils
  (BotGuard attestation). PO token ≠ guarantee against 403, but helps
  flagged-IP traffic look legitimate.
- **Implication:** youtube source gains
  `SEARCH_GATEWAY_YOUTUBE_PO_PLUGIN`/`..._PO_SERVER` seams; default off;
  detector flags the "Sign in to confirm you're not a bot" failure mode.

Source: github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide;
github.com/Brainicism/bgutil-ytdlp-pot-provider.

---

### 3.5 XiaohongShu — x-s/x-t header signing
**2026-08-22 · suggests (one primary CN writeup)**

- Web API (edith.xiaohongshu.com) signs requests with `x-s` (+`x-t`) headers
  generated from a JS-side mechanism (homefeed analyzed); community clients
  exist but drift.
- **Implication:** keep XHS in browser tier; an auth tier + signing adapter
  is Phase 6-late, gated; DR-4 verifies current state before any code.

Source: jishuzhan.net/article/2045344850162286593.

### 3.6 Chinese hot-list endpoints — free JSON wins exist
**2026-08-22 · needs-verification (saw API surface; endpoints unverified live)**

- Commercial "Chinese trending data" APIs cover Weibo/Baidu/Douyin/Bilibili/
  Zhihu/Toutiao (paid, RapidAPI) — off-table per zero-paid-APIs.
- Known public endpoints to verify during Phase 6: Baidu `top.baidu.com/api/
  board` (public JSON, no auth); Toutiao `hot-board` JSON; Zhihu hot-list
  JSON; Weibo `weibo.com/ajax/side/hotSearch` (cookie-gated).

Source: github.com/donald481/chinese-trending-data-api.

---

## 4. Content extraction tooling

### 4.1 The numbers that chose our stack
**2026-08-22 · verified (peer-reviewed eval + independent 2026 benchmark)**

| Tool | F1 / Precision / Recall (ORNL 2024) | 2026 markdown benchmark (25) | Strength |
|------|-------------------------------------|------------------------------|----------|
| Trafilatura | 0.937 / **0.978** / 0.920 | 19 | best precision; wiki/server-rendered prose; local; Apache-2.0 |
| Readability | 0.914 / 0.936 / **0.929** | 16 | best recall; Firefox Reader View algorithm |
| Jina Reader | — | **21** | best SPA/JS rendering (ties Firecrawl); free URL-prefix API |
| Newspaper3k | 0.903 / 0.912 / 0.928 | — | legacy; stalled |
| html2text | — | 10 | last resort |

- Statistical note: Trafilatura vs Readability F1/recall differences were
  **not** significant (p>0.05); Trafilatura's precision advantage was
  (p<0.05).
- Non-JS tools return an empty shell on SPAs — a browser-render step must
  front them.
- **Implication:** `read_url` = Jina first (JS-heavy), Trafilatura second
  (local, precision, zero cost), readability-lxml third (recall), html2text
  last. Cost: two pure-python deps. Success telemetry per stage.

Sources: doi.org/10.2172/2429881 (ORNL eval);
mdisbetter.com/blog/url-to-markdown-benchmark-10-tools-compared (2026-05).

### 4.2 Jina Reader control surface
**2026-08-22 · verified (official API docs)**

- Headers that matter for us: `X-Target-Selector` (return only that CSS
  subtree; implies `X-Wait-For-Selector`), `X-Wait-For-Selector`,
  `X-With-Links-Summary`, `X-Proxy-Url` (custom proxy, http/https/socks4/
  socks5 incl. auth — the hook we'll use when the proxy tier is enabled),
  `X-Proxy` (Jina's own proxy + optional country code).
- **Implication:** `read_url` forwards `X-Proxy-Url` when
  `SEARCH_GATEWAY_PROXY_ENABLED`, and passes `X-Target-Selector` for known
  platform article bodies (zhihu/weibo playbooks).

Source: r.jina.ai/docs.

---

## 5. Codebase archaeology — what this repo already teaches

### 5.1 Ops: three stale gateway processes + NOAUTH Redis (found 2026-08-22)
**2026-08-22 · verified (observed) · actionable**

- `pgrep` showed three concurrent `search-gateway` servers; the MCP channel
  died mid-session while they lived. Redis answers `NOAUTH` on the default
  URL — the B6 `requirepass` hardening is active but `.env.example` still
  shows the passwordless URL.
- **Implication:** Phase 0 items confirmed: PID lock + systemd ownership;
  `.env.example` gains the `redis://:<pw>@…` form; research must not depend
  on a single MCP channel (agent-reach fallback proved out).

### 5.2 The repo's own patterns to extend, not replace
- Env-var-first config with defaults (`config.py`), feature flags default OFF.
- `Source` ABC → `Result` contract; 4-step source addition; golden contract
  test — Phase 6 follows it verbatim.
- Redis as shared state (cache/stats/ratelimit) with in-memory fallback —
  profile health + proxy health use the same shape (`sg:ph:*`, `sg:px:*`).
- Graceful degradation everywhere; envelope names the failure — Phase 4
  extends the same honesty to `blocked`/`auth`.
- Subprocess env allowlist (`sources/base.py`) — the browser tier must get
  the same discipline for launch env.
- The LinkedIn/XHS "not authenticated, errors gracefully" docstring pattern
  generalizes into the `auth:` envelope field.

### 5.3 Personal-model hygiene
- `ratelimit.py` already implements cross-process min-interval + daily
  budget; the missing piece is jitter (fixed intervals are a fingerprint)
  and per-profile granularity (Phase 1/2).

---

## 5.5 HTTP impersonation — curl_cffi

**2026-08-22 · verified (project README)**

- `curl_cffi` (lexiforest, MIT): requests-like Python API over
  curl-impersonate; impersonates **JA3/TLS + HTTP/2 fingerprints** (recent
  browsers + custom); async with **per-request proxy rotation**; HTTP/2+3;
  precompiled wheels; faster than httpx.
- **Implication:** the Phase 3 impersonation seam (`extract/http.py`) is a
  thin httpx-compatible facade that swaps to curl_cffi when
  `SEARCH_GATEWAY_IMPERSONATE=1` and the source is on the impersonate
  allowlist (bilibili/XHS/weibo class). Default OFF; self-hosted + pure APIs
  keep httpx.

Source: github.com/lexiforest/curl_cffi.

---

## 6. Open research items (parking lot)

| # | Question | Feeds |
|---|----------|-------|
| R1 | ~~Camoufox API basics~~ → **DONE**: browserforge fingerprints, `os`/`Screen`/`fingerprint_preset` params (camoufox.com/python/usage). Remaining: proxy param + humanize surface — verify at Phase 3 | Phase 3 |
| R2 | ~~nodriver vs Patchright capability matrix~~ → **DONE**: stealth-matrix.md (nodriver clean 31-target pass; Patchright none) — fixture vault still DR-1 | DR-1 |
| R3 | ~~Zhihu search API~~ → **DONE**: endpoint + params + cookie contract (§3.7). Remaining: hot-list endpoint verify | Phase 6 |
| R4 | ~~Weibo ajax endpoints~~ → **DONE**: hotSearch visitor-cookie; SUB-gated search (§3.8) | Phase 6 |
| R5 | ~~yt-dlp PO-token plugins~~ → **DONE**: bgutil-provider + getpot-wpc (§3.9) | Phase 4/6 |
| R6 | ~~Jina headers~~ → **DONE**: X-Target/Wait-Selector, X-With-Links-Summary, X-Proxy-Url (§4.2) | Phase 5 |
| R7 | ~~curl_cffi~~ → **DONE**: impersonation + async + proxy rotation (§5.5) | Phase 3 |
| R8 | ~~firejail vs systemd sandboxing for browser tier~~ → **DONE**: firejail REJECTED (suid + CVE history); systemd eBPF for the service + **nftables cgroupv2** for per-process egress (L3, §1.5) | Phase 7 |
| R9 | ~~Cloudflare challenge markers~~ → **DONE**: `cf-mitigated: challenge` official header (§1.4); **DR-1 markers catalog DONE** (2026-08-25): x-datadome/x-datadome-cid, challenge-platform body, _abck, _px3, funcaptcha + 3 real fixture captures (CF×2, DD×1) | Phase 4 |
| R10 | IPRoyal/SOXA API specifics: geo grammar, sticky TTL caps, dashboard/API provisioning | Phase 3.5 |
| R11 | ~~Zhihu hot-list JSON endpoint (public?)~~ → **DONE**: `api.zhihu.com/topstory/hot-list` anonymous, 30-item cap (PHASE8 §2.1); shipped as `zhihu_hot` (0.4.3) | Phase 6 |
| R12 | ~~Baidu/Toutiao live verification~~ → **DONE**: toutiao fine; **baidu BROKEN** (tabTextList shape, no hotScore) → fixed with dual-shape parser + drift guard (0.4.3) | Phase 6 |
| R13 | ~~IMDS/SSRF incident class: always-blocked floor~~ → **DONE**: link-local `169.254.0.0/16` bypass → IAM theft; floor checked pre-nav AND post-redirect (hermes-agent PR #21228) (§1.5) | Phase 7 |
| R14 | ~~systemd credentials for secrets~~ → **DONE**: `LoadCredential=`/`$CREDENTIALS_DIRECTORY`; env vars rejected for secrets (systemd.io/CREDENTIALS, #40333) (§1.5) | Phase 7 |
| R15 | ~~Chrome 136+ automation constraints~~ → **DONE**: non-default user-data-dir required for remote debugging; CfT recommended (§1.5) | Phase 7 |
| R16 | ~~Forced-proxy egress for Chromium~~ → **DONE**: `--proxy-server` + `--host-resolver-rules="MAP * 0.0.0.0, EXCLUDE 127.0.0.1"` (chromium proxy.md) (§1.5) | Phase 7 |

---

## Changelog

- **2026-08-22** — Journal opened. Recorded: anti-bot/stealth field state (§1),
  proxy economics (§2), platform playbooks for X/Reddit/YouTube/Bilibili/XHS/CN
  hot-lists (§3), content-extraction benchmark (§4), codebase archaeology (§5).
- **2026-08-22 (implementation)** — v0.4 build learnings:
  - **wbi verified end-to-end**: `mixin_key(7cd0…77c, 4932…45) =
    ea1db124af3c7062474693fa704f4ff8` and the full worked `w_rid =
    8f6f2b5b3d485fe1886cec6a0be8c5d4` reproduce byte-for-byte from the
    canonical doc — the implementation is primary-source-verified, not
    heuristic.
  - **Test-hermeticity trap**: the wbi test polluted real Redis with cached
    keys, which then short-circuited later test runs (keys must be stubbed
    in the test, not assumed absent). Rule: any module with a Redis-backed
    cache needs an explicit stub in its tests.
  - **HTTP facade lesson**: wrapping foreign client responses into a unified
    `Response` must carry the parsed payload through, not re-parse `.text`
    (a fake whose JSON lives in a field, not text, breaks silently).
  - **Subprocess block detection works**: `run_cmd` now raises
    `blocked (vendor/level)` before the retry ladder — retrying a wall is
    the wrong move; tests confirm retries never touch challenges.
  - **Envelope signals parse outcome strings** (`blocked (…)`/`auth: …`) —
    the outcome string is the load-bearing contract between sources and the
    envelope; keep the prefixes stable.
  - **S314/S324 discipline**: MD5 in wbi is a mandated signature format
    (noqa'd with reason); sha1 for sticky ids upgraded to sha256.
  - **Phase 7 pending**: browser sandboxing (firejail/systemd egress rules),
    per-profile secret vault, bench.py browser tier — not yet implemented.
- **2026-08-23 (Phase 7 execution)** — containment research folded in (§1.5):
  firejail rejected, nftables-cgroupv2 chosen for L3, IMDS floor lesson
  (pre-nav + post-redirect), systemd credentials bridge, forced-proxy flags.
  Parking-lot R8/R13–R16 closed.
- **2026-08-23 (0.4.1 build)** — floor + vault + telemetry shipped (`3f79e15`):
  egress floor live on every extraction path; secrets migrated on this machine
  (legacy paths honored one release, removed 0.4.3); block telemetry at the
  raise site vs the envelope chokepoint split so events never double-count;
  test suite must bind `rds` on any fixture that can trigger a floor denial
  (the hook tests polluted real Redis once before that discipline was added).
- **2026-08-23 (0.4.2 build)** — L2 + L3 + bench + unit shipped (`8d1601e`):
  - **Empirical scoping fact**: `systemd-run --user --scope` places the scope
    under `app.slice/sg-egress-<unit>.scope` (sibling of the caller's unit
    path, NOT nested) — so `install()` must derive the rule path from
    `/proc/self/cgroup` at install time (run install inside the scope, or
    let the unit's `ExecStartPre` do it in the unit cgroup), and the
    `run_opencli` wrapper must reuse the FIXED unit name `sg-egress` so the
    paths agree. Serialized browser budget implied for ad-hoc scoped mode.
  - **CONNECT header hygiene**: a proxy must consume-and-discard the
    CONNECT request's remaining headers before replying 200 — leaking them
    into the tunnel makes the target read `Host:…` as its first bytes
    (caught by a real loopback echo test).
  - **Event-loop discipline**: asyncio servers started in a sync fixture's
    `asyncio.run` live in a *different* loop than the test — loopback tests
    must run the server loop in a background thread (`run_coroutine_threadsafe`).
  - **L2/L3 default posture**: egress proxy default ON for the anonymous tier
    only (D7.2); kernel filter `required` by default with an explicit
    `permissive` escape for sandboxed CI (D7.1); `nft` rules are kernel state
    and survive service restarts.
- **2026-08-23 (PHASE8 / 0.4.3 build)** — consolidation: baidu repair,
  zhihu_hot, D7.3 legacy removal, stealth-matrix, ADR-0007:
  - **Live probe discipline paid off**: R12 was not a theory — baidu's
    board had drifted to the `tabTextList` shape (no `hotScore`) and the
    shipped parser was returning silent empties. The fix pairs a dual-shape
    parser with a **shape-drift guard**: 200-with-cards-but-unparseable →
    SourceError, never `[]`. Guard applied to zhihu_hot too; toutiao's
    existing parser is verified against the live shape.
  - **zhihu_hot**: `api.zhihu.com/topstory/hot-list` is the zero-cookie win
    (the `hot-lists/total` variant 401s); 30-item endpoint cap; URLs come
    back as `api.zhihu.com/questions/<id>` and must be rewritten to the
    human surface.
  - **D7.3 executed on schedule**: legacy flat paths removed at runtime
    (vault path only); `migrate()` kept as the migration source so
    never-migrated machines have an upgrade path.
  - **Registry 22 → 23** — contract test + `check` gate + every doc count
    updated in the same commit (the repo's own rule).
- **2026-08-25 (ops batch, PHASE8 Plans 6-7)** — service + filter live; the
  containment layer's biggest lessons yet:
  - **The --user sandbox vs setuid law**: ANY namespace-based sandbox property
    (ProtectSystem=strict, ProtectHome, ProtectKernel*, ProtectControlGroups,
    LockPersonality, PrivateTmp) runs a --user unit in a user namespace
    mapping only the invoking uid — root-owned files read as overflow uid
    65534, so sudo (and any setuid binary) refuses with "must be owned by
    uid 0". NoNewPrivileges is a second, independent blocker. In-unit
    privileged loading is impossible BY DESIGN in --user units.
  - **Resolution**: the privileged nft load moved to a dedicated NON-sandboxed
    companion unit (search-gateway-harden.service) running After= the
    gateway; it installs rules for the gateway unit's cgroup (`--for` flag,
    resolved via systemctl show ControlGroup), loads via the sudoers drop-in,
    and records a mark-installed receipt. The gateway unit keeps the full
    sandbox and only verifies.
  - **Kernel-floor loopback exemption is load-bearing**: dropping
    127.0.0.0/8 locked the scoped process out of its own CDP/extension/proxy
    machinery — and, in a mis-scoped experiment, out of Redis entirely
    (connect timeouts across the whole session). Loopback is exempt; the
    floor absolutely blocks link-local/IMDS, RFC1918, CGNAT, v6 equivalents.
  - **nft loads validate the cgroup path at load time** — the target cgroup
    must exist (boot-time loads fail on not-yet-created unit cgroups; the
    companion's After= ordering solves it). systemd's escaped slice names
    (app-search\x2dgateway.slice) are accepted verbatim while alive.
  - **Unprivileged `nft list table` fails EPERM** — the enforcement probe
    falls back to the loader's installed_at receipt (the loader's success IS
    kernel-verified: `nft -f` both validates and applies).
  - **Test hygiene regression**: a CLI smoke test writing state to the REAL
    ~/.config/search-gateway/harden.json left a bogus installed_at (kernel
    had no table) — tests must patch STATE_PATH. Fixed.
  - **Service verified end-to-end**: 401 without token; MCP handshake over
    HTTP (initialize -> session -> tools/list = 14 tools); sg_egress table
    live in the kernel; loopback intact.
- **2026-08-25 (live smoke tests, PHASE8)** — browser + CN + anonymous tiers
  exercised through the hardened service; four more real bugs caught:
  - **Expansion provenance lie**: sources=['reddit'] + weak results → the
    query-expansion fan-out silently fused searxng/exa into the response
    while the envelope named only reddit. Fixed: expansion only for the
    default fan-out (sources=None) — pinned sources are strict.
  - **CLI banner noise**: systemd-run's 'Running as unit: …' + opencli's
    'Update available: …' broke JSON parses (→ silent 'ok (0)'). Fixed:
    --quiet on the wrapper + a quote/escape-aware outermost-JSON extractor
    in parse_json_or_yaml.
  - **None snippets**: toutiao emits snippet=None for Label-less items;
    fusion/dedup slice snippets unconditionally → TypeError on any CN board
    run. Root fix: Result.__post_init__ coerces None string fields to '';
    toutiao emits ''.
  - **Camoufox API contract**: AsyncCamoufox.start() RETURNS the Playwright
    Browser (the wrapper has no page API); headless=True = native Firefox
    headless (no Xvfb), 'virtual' requires Xvfb. The adapter default was
    'virtual' — refused to launch on this machine. All fixed + live-verified.
  - **Live anonymous-tier proof**: a process moved into the gateway unit's
    cgroup (cgroup.procs write — user-manager cgroups are user-writable)
    passed the L3 coverage gate, started the L2 egress proxy (ephemeral
    port), and fetched page content through the forced proxy under the
    kernel floor. SEARCH_GATEWAY_STEALTH=1 is now set in the service env.
  - **Empty-query crash** traced to the None-snippet bug (CN board runs);
  - Stale per-source/final caches repeatedly masked real behavior during the
    session — flush discipline: sg:s:<src>:* and sg:<category>:<src>:* keys.
- **2026-08-25 (DR-1)** — challenge fixture vault + marker catalog landed:
  - **Live captures**: crunchbase + indeed (Cloudflare managed challenges,
    marker `challenge-platform` at char ~127k — the classify window was
    capped at 4000 chars and MISSED real pages; now scans the full body) and
    g2.com (DataDome `x-datadome: protected` + `datadome` cookie + `__cf_bm`
    on the SAME response — vendor-specific walls must classify before the CF
    cookie heuristic, or the DataDome wall is masked).
  - New markers: `challenge-platform` (CF body), `x-datadome` header,
    `kpsdk` body (Kasada), `_abck` (Akamai bot manager), `_px3`
    (PerimeterX), `funcaptcha`/`arkose` body.
  - PerimeterX/Kasada/Akamai/Arkose live captures remain open; synthetic
    markers cover them in unit tests.
- **2026-08-26 (intense bug sweep)** — 12 bugs found + fixed across the
  pipeline, containment layer, and sources (commit `9236032`):
  - **ratelimit race**: read-then-set let concurrent callers fire together —
    ban-protection pacing defeated under concurrency. Now an atomic SET NX
    claim loop; stale slots deleted + reclaimed.
  - **_singleflight key**: (source, query) ignored limit/category — concurrent
    same-query different-limit requests returned the wrong count. Key now
    covers every outcome-shaping param (live-verified with an 8-way burst).
  - **run_cmd orphaned children**: a cancelled outer task (GLOBAL_TIMEOUT /
    disconnect) left subprocesses running — CancelledError now kills.
  - **Identifier path injection**: crossref/openalex/semantic_scholar
    interpolated user-supplied DOIs/IDs raw into URL paths (traversal/URL-
    breaking chars) — segments now quoted.
  - **Facade exception contract**: 8 sources bypassed extract.http (no floor,
    no impersonation seam). All migrated; HTTPStatusError ⊂ HttpError (one
    catch type); JSON parsed LAZILY (the eager parse broke arxiv's Atom
    feed — found by the live probe).
  - **Auth timing**: Bearer comparison → hmac.compare_digest.
  - **MMR floor**: all-below-floor returned [] → top-k fallback.
  - Test-infra lesson: payload-based global-httpx mocks silently broke under
    the lazy-parse facade — module-level facade patching (per-source queues)
    is the deterministic pattern.
