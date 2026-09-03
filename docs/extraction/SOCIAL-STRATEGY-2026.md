# Social-Extraction Strategy 2026 — Research Synthesis

Evidence-backed strategy for the browser/cookie-backed social tier (Twitter/X,
Reddit, Facebook, Instagram, Xiaohongshu, Weibo, Zhihu), synthesized from a
deep-research run across the stealth-engineering state of the art, CN forums
(52pojie, V2EX, bilibili), RU forums/blogs (zenno.club, lolz.live, habr), and
red-team counter-sources. Ledger:
`~/research_runs/social-strategy-2026-09-03/` (9+ hops, 16 claims, 19 evidence
records, lint-clean; C1 correctly contested by the red-team pass).

## TL;DR — the five rules

1. **Protocol hygiene before everything.** Unpatched CDP `Runtime.enable`
   usage is *the* most reliable detection signal of 2026 (Cloudflare,
   DataDome, zhihu 40362). Proxies, fingerprints, and behavior are irrelevant
   if the protocol leaks. Every browser bridge must pass a self-test oracle
   (rebrowser-bot-detector / creepJS-class) before touching platforms.
2. **Browser for login-state only; plain HTTP for volume.** The repeatedly
   proven pattern for strong-risk-control sites (zhihu post-mortem): harvest
   complete cookies (incl. httpOnly via `Storage.getCookies`) from a real
   logged-in profile, then retrieve with a clean, fingerprint-less HTTP
   client. CDP-driven page rendering gets flagged even when logged in.
3. **Lifetime-sticky identity per account.** IP rotation per account is one
   of the strongest bot signals. CN platforms additionally ban at the
   *device* level: (device fingerprint, account, IP) is one atomic unit —
   a ban poisons all three. Never rotate any of them mid-life; retire the
   whole unit on a ban.
4. **The first 72 hours decide an account's fate.** Platforms score the
   registration fingerprint before the first action, then against a
   week-one behavior model. Warm-up must feed that model plausible data
   (gradual, jittered, geo-consistent) before any automation touches the
   account.
5. **Layered, not perfect.** The arms race is permanent (Camoufox's own
   2026 writeup admits a maintenance gap + newly found inconsistencies;
   crawlex shows patches becoming tells). Layer protocol + fingerprint
   consistency + behavior + IP reputation, and accept that no layer is
   ever finished.

## Findings by lane

### A. Stealth browser engineering (state of the art)

- **Camoufox (2026)**: C++-level spoofing beats JS shims (JS injection is
  always detectable), but the project had a ~1yr maintenance gap and the
  author lists newly discovered fingerprint *inconsistencies* — the arms race
  is explicit: "Anti-bot providers test Camoufox over and over again to find
  even 1 unique inconsistency, then immediately update their scripts."
- **rebrowser-patches**: the `Runtime.enable` CDP leak is the dominant
  vector; fixed via `addBinding`/`alwaysIsolated`. Ecosystem: patchright,
  brotector, harden-puppeteer. Self-test oracle: rebrowser-bot-detector.
- **Red team**: Foil — "CDP usage is detectable from inside the browser… the
  bind stealth tooling cannot escape." crawlex — "the patch itself becomes
  the new tell." Behavioral-biometrics research harnesses target cursor
  entropy + OS-level signals. FP-Radar (academic) — the fingerprint API
  surface keeps expanding (Gamepad, Clipboard, Visibility).

### B. CN platform ops (52pojie / V2EX / bilibili)

- **XHS signing is a moving target.** 52pojie thread 2104039 (2026-04)
  documents a *new* scheme (`XYS_` + `seccore_signv2` via VMP-obfuscated JS
  executed in Node); a 2024 thread covered the previous one
  (x-b3-traceid/x-xray-traceid). RedCrack (GitHub) reimplements the full
  XHS param suite in pure Python — but the community re-reverses on every
  drift. Production XHS access = Node execution of VMP'd JS, not a static
  port.
- **Device-level bans**: v2ex t/1175885 — XHS bans read-only accounts for
  automation AND the device (rooted + Xposed was the trigger). t/1016027 —
  post-deletion fast re-registration flags; device + phone stay blacklisted;
  mixed region signals (HK device + HK iCloud + CN store) trigger risk
  control. Bilibili — XHS support-guided deletion locks the phone +
  real-name permanently.
- **Zhihu ops (jishuzhan post-mortem, 2026-06)**: browser-for-login +
  plain-requests pattern; Chrome 127+ App-Bound Encryption makes profile
  copying useless (login state must be created natively in-place); Chrome
  136+ refuses debug ports on the default profile; httpOnly `z_c0` only via
  CDP `Storage.getCookies`; **system proxies triggered 200-no-content soft
  bans — direct CN-residential connection fixed it**; throttle = 6–14s per
  item + 30–55s every 5 items + 120s backoff on 40362; prefer embedded
  `js-initialData` over the signed API.

### C. RU market practice (zenno.club / lolz / habr)

- The RU automation stack (ZennoPoster/Browser/Droid + CapMonster +
  ZennoProxy) is the mature reference architecture: per-profile browser
  identity + captcha-solving + proxy gateway integration in one ecosystem.
- Operator data point (zenno.club): mobile-proxy page-load stalls fixed by
  **geo-matching the proxy gateway subdomain** (gw → gw-ru mirror) — exit
  geography must match the target, or latency and risk both spike.
- habr fingerprint articles (2025-07/2026): anti-fraud systems cross-check
  device history (Sift): a fingerprint that *changed* is itself a signal.
  Consistency across sessions matters more than the specific values.

### D. Proxy / IP hygiene

- Per-account **lifetime-sticky** residential/carrier-grade IP; rotation is
  the strongest bot signal (Conbersa 2026, ProxyVero 2026).
- ASN reputation is evaluated in <2ms and cross-checked against behavior
  (ProxyLabs 2026); Cloudflare ML v8 detects residential-proxy abuse
  *without IP blocks* — residential IPs alone no longer guarantee passage.

### E. Warm-up & behavior

- The registration fingerprint + first 72 hours decide the account
  (EnigmaProxy 2026); platforms score the account before its first action,
  then against a week-one model. Warm-up = feed the model plausible data:
  gradual activity, jittered pacing, geo-consistent network.

## Mapping to this codebase

| Finding | Status in kortex-search | Action |
|---|---|---|
| Profile health state machine (fail → cooldown → quarantine) | ✅ `extract/profiles.py` (exp-backoff cooldown, quarantine after N cycles) | Keep; quarantine = the "retire the atomic unit" rule |
| Per-profile sticky proxy + geo-alignment | ✅ `PROXY_STICKY_TTL` / `PROXY_GEO_ALIGN` | Default raised 30m → 24h (this sweep); lifetime-sticky for account farms |
| Jittered pacing | ✅ `scheduler.paced`, now also `ratelimit.wait_if_needed` (this sweep) | Default interval raised 2.5s → 5s (this sweep) |
| Block detection + negative cache | ✅ detectors / PLATFORM_COOLDOWN | Consider escalating cooldowns after repeated cycles |
| Cookie-harvest vs browser-render split | ⚠️ zhihu uses cookie+API (x-zse-96 absent → 401 risk); browser tier renders via OpenCLI | zhihu API calls need the x-zse-96 signature (execjs) or SSR+js-initialData fallback — roadmap |
| Self-test oracle gate | ❌ no stealth self-test | Roadmap: rebrowser-bot-detector/creepJS gate in CI + `harden`-style CLI check |
| Camoufox tier | ✅ stealth tier exists (`STEALTH_ENABLED`) | Keep off by default; pin Camoufox version and re-test consistency on upgrades |
| Warm-up automation | ❌ none | Roadmap: `kortex-search warm-account` scripted warm-up feeding the 72h model (manual gate) |
| CN proxy soft-ban risk | ⚠️ PROXY_ENABLED off by default | Document: CN cookie sources prefer direct CN-residential egress; proxies for CN need CN exits |

## Open items / explicit gaps

- **Social source class**: the OpenCLI/Chromium bridge was DOWN during the
  run (all four social sources timed out) — social-class evidence is a
  declared gap; also the immediate reason the browser tier is inoperable
  right now (restart Chromium + `opencli doctor`).
- **lolz.guru/xss.is depth**: thread-level content is auth-gated; only
  index-level signal was reachable (tags listing + zenno.club threads).
- **Weibo-specific** ops not covered in depth this run (bilibili/v2ex hits
  were XHS/zhihu-centric).

## Cited sources (ledger S001–S016)

camoufox.com/stealth · github.com/rebrowser/rebrowser-patches ·
zenno.club thread 128755 · 52pojie thread 2104039 · v2ex t/1175885 ·
v2ex t/1016027 · jishuzhan agent-browser zhihu post-mortem ·
conbersa.ai rotation + warmup · cloudflare ML resi-proxy detection ·
enigmaproxy warm-up schedules · shadowphone.io IG guide ·
usefoil.com puppeteer detection · blog.crawlex.net stealth-plugins-lose ·
github.com/jeffasante/behavioral-biometrics-research ·
arXiv 2112.01662 (FP-Radar) · IEEE ICAC 2024 ML+fingerprint bot detection.
