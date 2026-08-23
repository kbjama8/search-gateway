# Camoufox Migration Track

How the anonymous browser tier migrates from OpenCLI/Chromium to Camoufox —
staged, per-platform, reversible. Companion to PLAN.md Phase 3 (decision D2:
dual-path now, full migration planned).

## Why

Research (2026-08-22, LESSONS.md §1.1): `playwright-stealth` is dead
(unmaintained since 2023, fails 2024+ behavioral checks); **Camoufox**
(Firefox ESR + browserforge fingerprints) leads anonymous extraction
against DataDome-class control planes — 36/40 vs 24/40 usable pages in the
independent 2026 benchmark. OpenCLI/Chromium stays as the *authenticated*
tier (cookie sessions for Twitter/Reddit/FB/IG) because Camoufox is not a
session-authenticator — it is the anonymous workhorse.

## End-state architecture

```
Tier B (CLI)        twitter-cli, yt-dlp+PO, mcporter
Tier C (browser)    ├─ authenticated: OpenCLI/Chromium (persona sessions)
                    └─ anonymous:     Camoufox  ← this track
```

The `Source` contract is identical for both engines — the tier router
(`extract/router.py`) already selects by source preference. Migration is
therefore *per-source cutover*, not a rewrite.

## Stages

### Stage 1 — Parity (experimental flag, current state)

- `extract/camoufox.py` provides `launch(profile)` + `html(url)` behind
  `SEARCH_GATEWAY_STEALTH=1`; lazy import; every failure degrades to
  `(None, reason)`.
- **Go/no-go:** `search-gateway doctor` reports the stealth tier status;
  one anonymous read via the adapter succeeds.

### Stage 2 — Dual-run (shadow traffic)

- New anonymous sources (zhihu/weibo/XHS when they join the browser tier)
  run **only** on Camoufox; no authenticated persona touches it.
- Benchmarks per target: success rate, block rate, latency, cache-hit shape
  (extend `scripts/bench.py` with the browser tier).
- **Go/no-go:** per-platform success ≥ OpenCLI baseline on the same target
  set, measured over ≥ 200 queries (needs the proxy tier or strong pacing).

### Stage 3 — Per-platform cutover

- Flip `SOURCE_TIERS` entries from `("browser",)` (OpenCLI) to
  (`"browser"`,) with `STEALTH_ENABLED` — the router reads the same table,
  so the cutover is a one-line change per source.
- Keep the OpenCLI engine for authenticated-session sources only.
- **Go/no-go:** KBJ signs off per platform; negative-cache + block-ladder
  telemetry clean for 7 days.

### Stage 4 — OpenCLI retirement

- Remove `run_opencli` once no source uses it; delete the extension loading
  from docs; archive the OpenCLI profile dirs.
- **Go/no-go:** full suite green with the extension gone; `doctor` clean.

## Fingerprint discipline during migration

- Camoufox generates coherent fingerprints by default (browserforge:
  OS/screen/UA families). Our added value is **locale/network coherence**:
  the proxy engine derives TZ/locale/languages from the sticky egress
  (`extract/proxies.align_bundle`) — Camoufox's preset + our geo alignment
  is the complete story (LESSONS.md §1.2).
- `SEARCH_GATEWAY_STEALTH_PROFILE` pins a bundled preset (random by default)
  — pin per persona so the same persona presents the same story session to
  session.
- Never run the authenticated OpenCLI sessions and anonymous Camoufox
  sessions from the same IP (proxy engine enforces separate sticky sessions).

## Risks

| Risk | Mitigation |
|------|-----------|
| Camoufox API churn (fast-moving project) | adapter is a thin seam; pin the version; fixtures in DR-1 |
| Firefox-based fingerprint rarer than Chrome → outlier | browserforge presets randomize OS/browser; coherence > rarity |
| Double engine maintenance during dual-run | Stage 2 is time-boxed; cutover removes the OpenCLI path |
| Bot-management catches up | the ladder (detect → throttle → rotate → quarantine) applies identically; no engine is immune |

## Current status

- Stage 1 scaffolding: **done** (`extract/camoufox.py`, gated).
- Stage 2+: pending KBJ's proxy-budget sign-off (browser tier without
  proxies has a ceiling; see `proxy-funding-guide.md`).
