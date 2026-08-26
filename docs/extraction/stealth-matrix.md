# Stealth-Engine Insurance Matrix (R2)

*Companion to [PLAN.md](PLAN.md) (Phase 3, decision D2). Camoufox is the
primary anonymous engine; this matrix documents the verified fallback options
so an engine failure never leaves us starting from zero. Research:
2026-08-23 (PHASE8 §2.2).*

## Capability matrix (2026 field state)

| Dimension | **Camoufox** (primary, D2) | **nodriver** | **Patchright** |
|-----------|---------------------------|--------------|----------------|
| Engine | Firefox ESR fork + browserforge fingerprint randomization | CDP-native (attaches to real Chrome/Chromium) | maintained patched-Playwright |
| Cloudflare/DataDome benchmark | 36/40 vs 24/40 (DreamScrape) | **0 hard blocks / 31 targets** (only clean pass in 7-browser head-to-head) | no clean pass in the same head-to-head |
| Session/auth support | no (anonymous workhorse) | no (CDP attach to existing sessions possible) | Playwright-compatible (auth via storage state) |
| Proxy support | `proxy` + `geoip` params (official) | per-context proxy (CDP `--proxy-server` + rules) | Playwright proxy option |
| Python API | `AsyncCamoufox` (lazy seam in `extract/camoufox.py`) | async-native (`webdriver`-free) | Playwright's (patched) |
| Maintenance (2026) | active, fast-moving (API churn risk) | active | active |
| Our adapter seam | `extract/camoufox.py` (`launch`/`html`) | would reuse the same seam via CDP `Browser` | would reuse via patched Playwright |

## Adoption triggers (when to reach for the matrix)

| Trigger | Action |
|---------|--------|
| Camoufox API churn breaks `launch()`/`html()` | pin the version; if unmaintainable → evaluate **nodriver** (best benchmark) via a thin adapter behind the same seam |
| A target platform blocks Firefox-class fingerprints | nodriver/Patchright present Chrome-class fingerprints → shadow-run both, compare success |
| Anonymous tier needs authenticated-ish state (rare) | Patchright (Playwright storage-state) — otherwise never |

## Decision rules

1. **Never adopt without a shadow-run**: ≥200 queries per target, success/
   block/latency vs the current engine (bench.py browser tier methodology).
2. **One adapter at a time**: the `Source` contract is engine-agnostic
   (`extract/camoufox.py` is the seam) — a new engine is a new adapter, not a
   router change.
3. Coherence doctrine applies identically: proxy geo drives locale
   alignment regardless of engine.

## Fixture vault (DR-1)

Recorded challenge pages under `tests/fixtures/challenges/` (captured live
2026-08-25): **Cloudflare** (crunchbase managed-challenge, indeed challenge
page) and **DataDome** (g2.com — x-datadome: protected + datadome cookie
behind both vendors). The detector suite is now fixture-driven for these;
PerimeterX/Kasada/Akamai/Arkose live captures remain open (synthetic
markers cover them in unit tests).

Sources: proxycove.com stealth-browsers-2026 benchmark; dreamscrape
camoufox-vs-playwright-stealth; LESSONS.md §1.1/§1.5.
