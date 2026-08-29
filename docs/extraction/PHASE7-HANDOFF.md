# Phase 7 — Session Handoff

*Where the Project Gatekeeper work stands, what was researched, what was
decided, and exactly what the next session must do. Written 2026-08-22 at the
close of the v0.4.0 session. Read this file, then `docs/extraction/PLAN.md` +
`docs/extraction/LESSONS.md` for depth.*

## TL;DR

v0.4.0 (Project Gatekeeper: extraction layer, bilibili wbi, CN tier, envelope
0.4) is **built, committed, pushed** (`6f38682` on `main`). Phase 7
(containment & observability) is **fully planned and researched, decisions
locked, zero code written**. The next session executes it in **two releases**:
**0.4.1** (L1 egress floor + secrets vault full migration + telemetry) and
**0.4.2** (L2 forced-proxy for anonymous engines + **mandatory** L3 kernel
egress filter + bench browser tier + hardened systemd unit).

## 1. Repo state (verified at handoff)

| Item | Value |
|---|---|
| HEAD | `6f38682` "feat: Project Gatekeeper extraction overhaul (v0.4.0)" — **pushed** to `main` |
| Version | `0.4.0` (`kortex_search/__init__.py`) |
| Tests | **199 green** (`pytest -m "not slow"`), ruff clean, coverage **85.47%** (gate 85%) |
| Sources | **22** registered (18 + zhihu/weibo/baidu/toutiao, CN-gated) |
| Code graph | refreshed at `6f38682` (crg build_or_update) |
| Working tree | clean at handoff |

What v0.4.0 shipped (for orientation): `kortex_search/extract/` package
(parse, detectors, router, scheduler, profiles, fingerprints, proxies, http,
camoufox), bilibili **wbi signing** (canonical-example-verified), read_url
multi-stage (Jina→Trafilatura→readability), envelope `extract{}`/`blocked[]`/
`auth{}`, docs/extraction/{PLAN,LESSONS,proxy-funding-guide,camoufox-migration}.

## 2. Machine/ops state the next session inherits

- **Redis is password-protected** (B6 hardening): plain `redis://127.0.0.1:6379/0`
  answers `NOAUTH`. The working credentials live in `~/.agent-reach/gateway.env`
  (`KORTEX_SEARCH_REDIS_URL=redis://:<pw>@…`), which `tests/conftest.py`
  loads at import. Tests pass because of that file — do not delete it.
- **Stale gateway processes** were killed in Phase 0 (3 orphans). Lesson:
  stdio MCP servers orphan when their client dies; they do NOT die on
  SIGTERM when stdin is gone (needed SIGKILL). If the gateway MCP channel is
  down, research fallback = `mcporter call exa.web_search_exa query="…"` and
  `curl -s https://r.jina.ai/<url>` (both verified working this session).
- **Redis keys `ks:bili:wbi:img` / `ks:bili:wbi:sub` were cleaned** at the end
  of the v0.4.0 session — do not expect cached wbi keys; the source refetches
  from the nav API on demand (that is the designed path).
- `~/.agent-reach/` currently holds flat auth files (`twitter-auth.env`,
  `deepseek.env`, `proxy.env`(absent), `gateway.env`) — **the vault migration
  in 0.4.1 relocates these**; see §5.2.
- Test infra: `RedisStub` fixture in `tests/conftest.py` binds
  `_get_client` for cache/ratelimit/stats/saved_queries/extract.profiles/
  extract.proxies. Any new module with a `_get_client` must be added to that
  bind list.

## 3. Phase 7 research findings (this session, all verified read-only)

Full citations below; fold these into `docs/extraction/LESSONS.md` as part of
execution (suggested: new §1.5 "Containment field state" + close parking-lot
R8/R13–R16).

1. **firejail is a suid binary with a root-escalation CVE history** — rejected
   as the sandbox mechanism (netblue30/firejail wiki "Comparison of firejail
   and systemd hardening options"; fedoraproject discussion #121109).
   **systemd eBPF** `IPAddressDeny=`/`IPAddressAllow=`/`SocketBindDeny=`/
   `RestrictAddressFamilies=` exist but several firejail primitives
   (`netfilter`, `dns`, `hosts-file`) have no systemd equivalent.
2. **nftables supports per-process egress filtering** via
   `socket cgroupv2 level 2 "<path>"` — the pam_authnft project proves the
   pattern: systemd transient scope pins PIDs to a cgroup → nftables chain
   dispatches per-cgroup. No suid binary, no kernel module, works for ad-hoc
   processes (spinics.net nftables thread; identd-ng/pam_authnft
   ARCHITECTURE.txt).
3. **IMDS SSRF is a real incident class**: hermes-agent's browser hybrid
   routing bypassed its pre-nav guard for the whole `169.254.0.0/16`
   (link-local qualifies as "private") → IAM credential theft. Their fix: an
   **always-blocked floor as an independent gate**, checked pre-nav AND
   post-redirect (NousResearch/hermes-agent PR #21228, issue #16234).
4. **Chrome 136+**: `--remote-debugging-port`/`--remote-debugging-pipe`
   require a **non-default `--user-data-dir`** (App-Bound Encryption);
   prefer `--remote-debugging-pipe` over an open port; "Chrome for Testing"
   recommended for automation (developer.chrome.com blog 2025-03).
5. **systemd credentials**: `LoadCredential=`/`LoadCredentialEncrypted=`/
   `SetCredentialEncrypted=` + `$CREDENTIALS_DIRECTORY` + credstore dirs.
   **systemd's own doctrine: env vars are NOT suitable for secrets** (world-
   readable via D-Bus, propagate across setuid boundaries). Issue #40333
   documents the `EnvironmentFile=%d/app-secrets` bridge
   (systemd.io/CREDENTIALS/; systemd/systemd#40333).
6. **Chromium forced-proxy egress is fully supported**:
   `--proxy-server="http://127.0.0.1:PORT"` routes everything;
   `--host-resolver-rules="MAP * 0.0.0.0, EXCLUDE 127.0.0.1"` pushes remote
   DNS through the proxy (chromium net/docs/proxy.md; superuser #1812598).

## 4. Locked decisions (KBJ, this session — do not re-ask)

| ID | Decision | Semantics |
|---|---|---|
| D7.1 | **L3 mandatory** | Browser-tier ops REFUSE to launch without the kernel filter installed. `KORTEX_SEARCH_HARDEN=required` (default) \| `permissive` (explicit opt-out for sandboxed CI). API/CLI tiers unaffected (default fan-out has no browser sources). systemd deployment gets it via the unit; ad-hoc gateways run `kortex-search harden --install --sudo`. |
| D7.2 | **L2 anonymous engines only** | Forced-proxy applies to Camoufox/anonymous launches (full flag control). OpenCLI authenticated tier keeps L1+L3; a bench live-test gate must pass before that policy ever changes. |
| D7.3 | **Vault: full migration now** | Move `twitter-auth.env`/`deepseek.env`/`proxy.env` into `~/.agent-reach/profiles/<persona>/` this cycle; legacy flat paths honored one release with a `doctor` deprecation warning (removed 0.4.3). |
| D7.4 | **Split into two releases** | 0.4.1 = L1 floor + vault migration + telemetry (zero-risk). 0.4.2 = L2 + L3 + bench + hardened unit (the sharp end). Commit + push each. |

## 5. Release 0.4.1 — floor, vault, telemetry

### 5.1 L1 egress floor — `kortex_search/extract/egress.py` (new)

- `ALWAYS_BLOCKED_NETWORKS`: `127.0.0.0/8`, `::1/128`, `10.0.0.0/8`,
  `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `100.64.0.0/10`,
  `fe80::/10`, `0.0.0.0/8`, `::/128` (plus IMDS specifics:
  `169.254.170.2/23` ECS, `100.100.100.200` Alibaba, `fd00:ec2::254` Azure).
- `ALWAYS_BLOCKED_HOSTNAMES`: `metadata.google.internal`, `metadata`,
  `169.254.169.254`, `100.100.100.200`, `169.254.170.2`, `169.254.170.23`,
  `metadata.azure.internal`, `localhost`, `*.localhost`, `*.local`.
- `is_always_blocked_url(url) -> tuple[bool, reason]` — pure IP parsing via
  `ipaddress` (NO DNS in the floor; fail-closed only on literals — the kernel
  layer catches what the floor can't see). **Checked pre-nav AND post-redirect**
  (hermes lesson).
- **Local-infra exemption only**: hosts of `SEARXNG_BASE` and `REDIS_URL`
  (the gateway's own loopback deps) + `KORTEX_SEARCH_FLOOR_EXEMPT`
  (comma-separated operator allowlist). Nothing else.
- Hooks: `extract/http.py` (all API-tier `request()`/`get_json` calls),
  `web.py::_read_*` (all three read_url stages), `camoufox.py::html`,
  `server.py::read_url` entry.
- Config: `KORTEX_SEARCH_EGRESS_FLOOR=1` (default ON), `KORTEX_SEARCH_FLOOR_EXEMPT=""`.
- Tests: `tests/test_egress.py` — IMDS variants (AWS/GCP/Azure/Alibaba/ECS),
  RFC1918/v6/CGNAT, searxng exemption, post-redirect, exempt-list override.

### 5.2 Secrets vault — `kortex_search/extract/vault.py` (new) + full migration

Target layout (persona from `KORTEX_SEARCH_PERSONA`, default `kaiser`):

```
~/.agent-reach/profiles/<persona>/
├── twitter.env       0600   (TWITTER_AUTH_TOKEN, TWITTER_CT0)
├── deepseek.env      0600   (DEEPSEEK_API_KEY)
├── proxy.env         0600   (KORTEX_SEARCH_PROXY_USERNAME/PASSWORD/GATEWAY)
├── fingerprint.json  0644   (bundle — NOT secret)
└── notes.md          0600
```

- Config default changes: `TWITTER_ENV_FILE`, `DEEPSEEK_ENV_FILE`,
  `PROXY_ENV_FILE` → the vault paths. `config.load_env_file` gains a
  **credentials-dir-aware loader** honoring `KORTEX_SEARCH_CREDENTIALS_DIR`
  (systemd `$CREDENTIALS_DIRECTORY` bridge).
- **Deprecation cycle**: legacy flat paths still honored for one release with
  a `doctor` warning; removal scheduled 0.4.3.
- `vault.hygiene() -> list[Finding]`: mode enforcement (0600), symlink-trap
  detection, stale files (>90d), out-of-vault `*_AUTH_FILE` vars.
  **Warn-not-fail** (degradation doctrine) but doctor colors it red.
- CLI: `kortex-search vault migrate [--dry-run]`, `kortex-search vault
  status`. Runs on this machine at execution time (moves the flat files;
  `gateway.env` for tests stays where it is — it is the test env, not a
  profile secret).
- Tests: `tests/test_vault.py` — mode enforcement, symlink trap, migrate
  dry-run/real on a tmp tree, legacy fallback + deprecation warning,
  credentials-dir bridge.
- Config: `KORTEX_SEARCH_VAULT_DIR` (default `~/.agent-reach/profiles`),
  `KORTEX_SEARCH_PERSONA` (default `kaiser`), `KORTEX_SEARCH_CREDENTIALS_DIR` (default `""`).

### 5.3 Telemetry

- `stats.py`: block-event reservoir `ks:bl:<source>:<vendor>` (bounded,
  TTL 24h) + counters; `record_block(source, vendor, level)` called from
  `base._blocked_error`, `orchestrator._extract_signals`, egress denials;
  `snapshot()` gains `blocks`. Config `KORTEX_SEARCH_BLOCK_RESERVOIR=120`.
- `health.py` doctor sections: `egress{floor, proxy, kernel, denied_count,
  last_denial}`, `vault{profiles, hygiene, findings}`, `blocks`, `profiles`
  (surface the Phase 2 `ProfileStore.status()`).
- `stats_report` gains `blocks` + `egress` (update docs/api/tools.md).
- Tests: reservoir behavior with `RedisStub`, doctor sections, envelope wiring.

**0.4.1 AC**: hermetic suite green; doctor shows four new sections; vault
migrate works on a temp tree; floor blocks every IMDS variant in fixtures;
ruff + ≥85% coverage; version bump `0.4.1` + CHANGELOG + docs (config-ref
70→79 vars; security.md threat table; deployment.md vault walkthrough).

## 6. Release 0.4.2 — L2, mandatory L3, bench, hardened unit

### 6.1 L2 forced-proxy — `egress.py` continues

- `EgressProxy`: asyncio CONNECT + absolute-URI proxy, bound to 127.0.0.1
  ephemeral port; every target through the floor → deny 403 + telemetry;
  allow → chain through residential tier when `proxies.enabled()`; singleton,
  lazy. **Anonymous engines only (D7.2).**
- Camoufox launch flags: `--proxy-server=http://127.0.0.1:<port>` +
  `--host-resolver-rules="MAP * 0.0.0.0, EXCLUDE 127.0.0.1"`.
- Config: `KORTEX_SEARCH_EGRESS_PROXY=1` (default ON for the anonymous tier),
  `=0` to disable.
- Tests: real asyncio sockets on loopback (no external net): CONNECT allow/
  deny, floor composition, chain-through-proxies mocked.

### 6.2 L3 kernel filter — `kortex_search/extract/harden.py` (new) + CLI `harden`

- `build_rules(cgroup_path) -> str` **pure function** (golden-tested): nft
  table `inet ks_egress`, `socket cgroupv2 level 2 "<path>"` verdict map →
  DROP chains for all private/link-local v4+v6, ACCEPT else.
- `install([--sudo])` idempotent: cgroup via `systemd-run --scope`, rules via
  `nft -f -`; refuses without `nft`/cgroupv2 (reports, never crashes).
- `status()` read-only (`nft list table inet ks_egress` + cgroup existence);
  `uninstall()`.
- **Enforcement (D7.1)**: browser-tier sources + anonymous engine check
  `harden.status()` before spawning; absent → `SourceError("blocked
  (egress-unhardened): run 'kortex-search harden --install --sudo'")` →
  negative-cache + envelope machinery names it. `KORTEX_SEARCH_HARDEN=
  required` (default) | `permissive`; `KORTEX_SEARCH_HARDEN_SUDO=1`.
- CLI: `kortex-search harden --install|--status|--uninstall [--sudo]`;
  `check` reports browser-tier enforceability.
- Tests: `tests/test_harden_rules.py` — golden ruleset string, `--status`
  parsing (mocked `nft`), no-`nft`/no-cgroupv2 degradation. NO kernel touched
  in CI.

### 6.3 bench + unit hardening

- `scripts/bench.py browser` (slow-marked): cold/warm launch, navigate→
  extract→teardown op cost, profile rotation, egress-proxy overhead (direct
  vs floor-checked p50/p90), RSS delta.
- `infra/systemd/kortex-search@.service` hardening: `LoadCredential=` for
  the vault, `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict` +
  `ReadWritePaths` for vault/profile dirs, `RestrictAddressFamilies`,
  `IPAddressDeny=169.254.0.0/16 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16
  100.64.0.0/10` at the service level (loopback stays open for Redis; the
  browser children get the strict cgroup). `ExecStartPre` verifies
  `harden --status`. Document walkthrough in docs/deployment.md.

**0.4.2 AC**: browser-tier ops fail with the explicit harden message until
installed (mocked status test); ruleset golden test; bench runs; unit doc
complete; suite + ruff + ≥85%; version `0.4.2` + CHANGELOG + docs.

## 7. Execution checklist (in order)

- [x] Fold Phase 7 research (§3 above) into LESSONS.md; close parking-lot R8/R13–R16
- [x] **0.4.1**: `egress.py` floor + tests → `vault.py` + migration + tests →
      stats reservoir + doctor sections + tests → config/.env.example/docs →
      version 0.4.1 + CHANGELOG → full verification → commit + push
- [x] **0.4.2**: `harden.py` + CLI + tests → EgressProxy + camoufox flags +
      tests → bench browser → systemd unit + deployment doc → config/docs →
      version 0.4.2 + CHANGELOG → full verification → commit + push
- [x] Update PLAN.md status board after each release; refresh crg graph;
      leave the working tree clean

## 8. Gotchas carried from the v0.4.0 build (see LESSONS.md §Changelog)

- Any module with `_get_client()` needs its Redis stub bound in
  `tests/conftest.py`'s `rds` fixture.
- HTTP facades must carry parsed payloads through, never re-parse `.text`
  from foreign clients.
- Outcome strings (`blocked (vendor/level)`, `auth: …`) are the load-bearing
  contract between sources and the envelope — keep the prefixes stable.
- MD5 in wbi is spec-mandated (noqa'd with reason); sha1 → sha256 elsewhere.
- Ruff select includes B/S/DTZ/BLE — new code must satisfy it; `--fix` for
  mechanical rules, manual noqas with reasons for the intentional ones.
- Tests must stub Redis-backed caches explicitly (the wbi key-cache polluted
  real Redis and broke later runs).
- RUF001 fullwidth-punctuation flags on intentional CJK test strings: assign
  to a variable first, then `# noqa: RUF001` on that line.
- Coverage gate is `--cov-fail-under=85`; the extract package needs ~100+
  lines of new coverage per release (target the lazy-import and pure-function
  seams).

## 9. Contact / authority

Decisions D7.1–D7.4 are locked; no open questions remain. KBJ's standing
doctrine applies unchanged: public-content research only, no captcha solving,
consistency-first stealth, everything env-gated, degrade explicitly never
silently, contract-tested. Kaiser Chen signs off on the containment layer.
