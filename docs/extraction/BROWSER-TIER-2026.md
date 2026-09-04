# Browser-Tier Architecture 2026 — Research Synthesis + Implementation

Evidence-backed redesign of the browser-backed social tier (Twitter/X, Reddit,
Facebook, Instagram, XHS). Deep-research ledger:
`~/research_runs/browser-tier-2026-09-03/` (6 hops, 7 claims, 10 evidence
records, red-team pass, lint-clean).

## The decision

**Managed Profile Farm over agent-browser (raw CDP) as the primary tier;
OpenCLI retained as fallback.** The OpenCLI bridge's structural weakness —
the whole tier dies when the operator's own browser isn't running — is
replaced by self-managed Chrome profiles with persistent login state. The
farm keeps the 2026 benchmark's only zero-block architectural class
(direct-CDP control plane, no Playwright shim) with an Apache-2.0 CLI.

## Evidence spine

| # | Claim | Sources |
|---|-------|---------|
| 1 | OpenCLI reuses the human's real logged-in browser; bridge-down = tier-down (observed live on this host) | agent-open-cli-http-util; local doctor |
| 2 | Automation-protocol fingerprinting is the decisive gate: direct-CDP beats every Playwright stack regardless of JS patches | ianlpaterson benchmark 2026 (N=3, 651 verdicts: nodriver-class 28/31 OK zero blocks; rebrowser == vanilla) |
| 3 | rebrowser-playwright is functionally vanilla + unmaintained; patchright's win came from `channel=chrome` | same benchmark |
| 4 | curl_cffi `impersonate=chrome` ties a 130MB patched Chromium fork on TLS-gated targets — the HTTP floor | same benchmark |
| 5 | agent-browser 0.27 (Apache-2.0): persistent `--profile` Chrome profiles, per-profile CDP, state save/load, proxy flags — P0-verified locally | local spike |
| 6 | Commercial anti-detect suites validate the profile-daemon pattern but are vendor-locked; self-hosted profiles give the same shape | Dolphin/AdsPower comparisons; ZennoBrowser API docs |
| 7 | Headless mode + datacenter IPs remain detection vectors regardless of control plane; the browser must live on the residential-IP host | nodriver #1848/#2249; benchmark FAQ |

Red-team: ByteTunnels — "starts clean ≠ evades modern fingerprinting"
(recorded as `contradicts` against the strongest reading of claim 5).

## What was built (v0.8.0)

- **`extract/browserfarm.py`** — the supervisor: idempotent per-profile
  launch (egress-gated, scoped under the L3 nft cgroup like the OpenCLI
  tier), Redis-backed CDP registry shared across gateway processes,
  per-profile locks, `exec_sync`, `health`, `shutdown(_all)`, `reap_idle`,
  `status`. Optional virtual display (`FARM_DISPLAY=:99`, Xvfb unit in
  `infra/systemd/xvfb.service`); headed-default fallback headless.
- **`sources/base.py::run_profile`** — source-visible primitive: jittered
  per-profile pacing + browser-budget lease + ensure + exec + block
  detection.
- **Ladders**: reddit = farm (old.reddit DOM eval) → opencli; twitter =
  twitter-cli → farm (x.com DOM eval) → opencli. Success/failure feeds the
  existing profile health state machine (healthy→cooldown→quarantined).
- **Ops**: `kortex-search farm status|login|reap`; doctor `farm` section;
  `FALLBACK_CHAINS` updated.

## Rollout status

- Farm infrastructure: shipped + tested (hermetic).
- `sudo dnf install xorg-x11-server-Xvfb` + enable the Xvfb unit: **pending
  operator action** (falls back to headless until then).
- `kortex-search farm login reddit` / `farm login twitter`: one-time human
  authentication per profile (headed window; login state then persists).
- Live account validation for twitter/fb/ig/xhs remains dependent on the
  burner personas' session health.

## Trade-offs accepted

- Persistent browsers consume RAM (~300–500MB per profile); capped by
  `FARM_IDLE_TTL` reaping and `BROWSER_BUDGET` concurrency.
- agent-browser is a moving dependency: version pinned in docs; `farm
  status` + a CI smoke keep it honest; Apache-2.0 allows vendoring.
- x.com DOM scraping is fragile by nature; twitter keeps three backends and
  the farm tier degrades honestly through the ladder.
