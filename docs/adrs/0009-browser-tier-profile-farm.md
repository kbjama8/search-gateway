# ADR-0009: Browser Tier — Managed Profile Farm over Direct CDP

- Status: **accepted** (2026-09-04)
- Decision owner: KBJ
- Related: `docs/extraction/BROWSER-TIER-2026.md`,
  `docs/extraction/SOCIAL-STRATEGY-2026.md`, ledger
  `~/research_runs/browser-tier-2026-09-03/`

## Context

The browser-backed social tier (twitter/reddit/facebook/instagram/xhs)
depended on the OpenCLI bridge, which reuses the operator's own logged-in
browser via an extension. When that browser is not running, the entire tier
is down — observed on this host (all four social sources timed out).
Research (2026 benchmark, N=3, 651 verdicts) additionally showed that
automation-protocol fingerprinting is the decisive anti-bot gate, and that
direct-CDP control planes (no Playwright shim) are the only zero-block
architectural class.

## Decision

1. **Primary tier: a managed profile farm** — self-managed Chrome profiles
   (one user-data-dir per platform×persona, login state persistent across
   restarts) launched and driven by `agent-browser` (raw CDP, Apache-2.0),
   supervised by `extract/browserfarm.py`.
2. **OpenCLI demoted to fallback** in the per-source ladders
   (`FALLBACK_CHAINS` updated).
3. **Headed-under-Xvfb** rendering by default (headless-new is a measured
   detection vector); systemd unit `infra/systemd/xvfb.service`.
4. **Same containment as before**: farm launches are gated by the L3
   egress filter and scoped under the kernel cgroup (`ks-egress-<profile>`
   transient scopes).
5. Profile health (success/failure/block signals) feeds the existing
   healthy→cooldown→quarantined state machine; quarantined profiles are
   never auto-revived.

## Consequences

- The tier no longer depends on the operator's desktop session.
- Persistent browsers cost ~300–500MB RAM each; bounded by
  `FARM_IDLE_TTL` reaping and `BROWSER_BUDGET`.
- agent-browser becomes a pinned operational dependency (Apache-2.0 —
  vendoring is permitted if it drifts).
- One-time human login per profile remains a manual bootstrap step
  (`kortex-search farm login <platform>`).
