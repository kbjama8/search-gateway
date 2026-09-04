# Deployment

The gateway is a **host process**, not a container: it shells out to CLIs +
Chromium and uses a warm local Hugging Face model cache, so it does not
dockerize cleanly. Redis and SearXNG *do* dockerize. Deploy in capability tiers —
a fresh install degrades explicitly, and `kortex-search doctor` is the tier
report.

```mermaid
flowchart TB
    subgraph Host["host process"]
        GW["kortex-search serve"]
        CLI["opencli · twitter · mcporter · yt-dlp · uvx"]
        MOD["HF model cache — ~/.cache/huggingface"]
    end
    subgraph Docker["docker compose (infra/)"]
        RD[("redis 7-alpine · AOF")]
        SX["searxng · JSON :8888"]
    end
    DS["DeepSeek API"]
    AC["arXiv · OpenAlex · Crossref · S2 · StackExchange"]
    GW --> RD
    GW --> SX
    GW --> CLI
    GW --> MOD
    GW --> DS
    GW --> AC
```

## Capability tiers

```mermaid
flowchart LR
    T0["minimal<br/>pip install + network"] --> T1["web+neural<br/>+ mcporter"]
    T1 --> T2["social/vertical<br/>+ opencli/Chromium, twitter, yt-dlp, uvx"]
    T2 --> T3["answer synthesis<br/>+ DEEPSEEK_API_KEY"]
    T0 -.->|"doctor reports ok"| D0(("22 sources<br/>partially available"))
    T3 -.->|"doctor reports ok"| D3(("22 sources<br/>fully available"))
```

Each tier is additive — nothing in a lower tier stops working when you add a
higher one, and nothing in a higher tier is required to use a lower one.

| Tier | Sources | Requires |
|------|---------|----------|
| **minimal** | arxiv, openalex, crossref, stackoverflow, github, web/`read_url` (+ searxng if up) | `pip install .` + network |
| **web+neural** | + exa | `mcporter` on PATH |
| **social/vertical** | + twitter, reddit, facebook, instagram, xiaohongshu, linkedin, youtube | `opencli`+Chromium, `twitter`, `yt-dlp`, `uvx` |
| **answer synthesis** | `research_answer`, query expansion | `DEEPSEEK_API_KEY` |

## 1. Native install

```bash
git clone <this-repo> && cd kortex-search
pip install .                  # or: pip install -e . for development
kortex-search --help
kortex-search check           # gate: 23 sources + Redis reachable
```

Optional report-tooling extras:

```bash
pip install '.[report]'        # matplotlib, weasyprint, python-docx, playwright
```

The re-ranker runs on ONNX Runtime by default (dynamic-quantized INT8),
~2× faster than torch with a smaller footprint — no extra install step, it's a
core dependency:

```bash
kortex-search serve                                        # onnx_int8 by default
KORTEX_SEARCH_INFERENCE_BACKEND=torch kortex-search serve # original torch path
```

`onnx_int8` uses the pre-exported `onnx-community/bge-reranker-v2-m3-ONNX`
model, downloaded on first load; if it can't load, the reranker falls back to
torch automatically. Measured: rerank 30 pairs ~3s vs ~6s on torch, RSS ~1.6GB
vs ~2.6GB, ranking agreement Spearman ≈ 0.96.

## 2. Services (Redis + SearXNG)

```bash
cd infra
docker compose up -d           # redis (AOF) + searxng (JSON, :8888)
kortex-search doctor          # both should report ok
```

Verified: `docker compose config` parses clean, and the searxng image mounts a
JSON-enabled `settings.yml`. Without Docker, run Redis and SearXNG natively and
point `KORTEX_SEARCH_REDIS_URL` / `SEARXNG_BASE` at them.

## 3. Run as a host process

**stdio (default — client-spawned):** register the console script in your MCP
client (`docs/mcp-registration.md`); the client spawns `kortex-search` per
session.

**HTTP (long-running — systemd):**

```bash
mkdir -p ~/.config/kortex-search && touch ~/.config/kortex-search/gateway.env
chmod 600 ~/.config/kortex-search/gateway.env   # put DEEPSEEK_API_KEY etc. here
cp infra/systemd/kortex-search@.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kortex-search@8765.service
```

The unit runs `kortex-search check` before start (`ExecStartPre`), installs
and reports the L3 egress filter for its own cgroup, restarts on failure, logs
JSON to the journal, and keeps models warm across client disconnects. `%i` is
the HTTP port. Hardening (0.4.2): `LoadCredential=` for vault secrets,
`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict` (+ `ReadWritePaths`
for the vault/profile dirs and the HF cache), `RestrictAddressFamilies`,
`IPAddressDeny` for the service-level floor. Verified: `systemd-analyze
verify` exits 0 on the shipped unit; the HTTP transport answers `tools/list`
with 15 tools.

Model-load temp hygiene (0.7.1): `ProtectSystem=strict` makes /tmp read-only
inside the unit, which broke optimum's ONNX load (`No usable temporary
directory found`) and poisoned torch's artifact registry for every later
load. The unit therefore sets `TMPDIR=%h/.config/kortex-search/tmp` (created
by `ExecStartPre`; inside the unit's `ReadWritePaths`) instead of loosening
the sandbox. After deploying, preheat the gateway so the first agent search
is fast:

```bash
python3 -m kortex_search.cli warm   # preloads models in a throwaway process (CLI check)
# or over the MCP surface: tools/call warm  (off-loop, keeps the gateway hot)
```

### Managed profile farm (0.8.0)

The browser-backed social tier runs on self-managed Chrome profiles
(`extract/browserfarm.py`, ADR-0009). Setup:

```bash
sudo dnf install xorg-x11-server-Xvfb          # once
cp infra/systemd/xvfb.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now xvfb.service     # DISPLAY=:99

kortex-search farm status                      # per-profile browser state
kortex-search farm login reddit                # one-time headed login (QR/password)
kortex-search farm login twitter
kortex-search farm reap                        # shut down idle profiles
```

Login state persists in `~/.agent-reach/profiles/<platform>-<user>/` across
browser and gateway restarts. A login wall is reported as "profile not
logged in" (never quarantined); genuine blocks feed the healthy→cooldown→
quarantined state machine.

### OpenCode token export

The opencode remote registration reads `{env:KORTEX_SEARCH_HTTP_TOKEN}`.
Export it in `~/.bashrc` from the 0600 env file:

```bash
if [ -f "$HOME/.config/kortex-search/gateway.env" ]; then
  export KORTEX_SEARCH_HTTP_TOKEN="$(grep -m1 '^KORTEX_SEARCH_HTTP_TOKEN=' "$HOME/.config/kortex-search/gateway.env" | cut -d= -f2-)"
fi
```

## 3.1 Secrets vault (0.4.1+)

Since 0.4.1, secrets live in the per-persona vault
`~/.agent-reach/profiles/<persona>/` (0600 files, 0700 dirs — decision D7.3).
One-time migration from the legacy flat files:

```bash
kortex-search vault migrate --dry-run   # what would move (shows paths + status)
kortex-search vault migrate             # moves twitter.env / deepseek.env / proxy.env
kortex-search vault status              # layout + hygiene (modes, symlinks, staleness)
kortex-search doctor                    # `vault` section: hygiene ok + no legacy_in_use
```

The legacy flat paths (`~/.agent-reach/twitter-auth.env` etc.) were honored
through 0.4.2 and **removed in 0.4.3** (D7.3) — migrate before upgrading past
0.4.2 on any machine that never ran the migration. `gateway.env` for tests
(`~/.agent-reach/gateway.env`)
is the *test* environment, not a profile secret — the migration leaves it in
place by design.

For a host-process deployment under systemd, prefer `LoadCredential=` over
`EnvironmentFile=` for the vault secrets: secrets arrive as files in
`$CREDENTIALS_DIRECTORY` and never touch the process environment (systemd's
own doctrine — see `docs/security.md`). The hardened unit in 0.4.2 ships this;
manual setups can pass `KORTEX_SEARCH_CREDENTIALS_DIR` in the unit pointing
at the credential mount directory.

## 3.2 Kernel egress filter (0.4.2, decision D7.1)

Browser-tier operations **refuse to launch** until the L3 nftables egress
filter is installed (the explicit `blocked (egress-unhardened)` message names
it). The filter is an nftables `socket cgroupv2` rule set: sockets opened by
browser children in a scoped cgroup are dropped when they target any
private/link-local/metadata range — no suid binary, no kernel module
(LESSONS.md §1.5, pam_authnft pattern).

**Ad-hoc gateway** (browser children wrapped in a transient scope):

```bash
kortex-search harden --install --sudo   # derives the wrapper scope itself
kortex-search harden --status           # installed + covered state
kortex-search harden --check            # browser-tier enforceability report
```

`install` derives the ruleset path from a probe of the `ks-egress` transient
scope (the one `run_opencli` wraps browser children into) — the gateway
itself never sits under the strict cgroup, so its loopback (Redis/SearXNG)
stays open. The kernel floor exempts loopback by design (the browser's own
CDP/extension machinery + the L2 egress proxy live there) and absolutely
blocks link-local/IMDS, RFC1918, CGNAT and v6 equivalents for scoped
children. `run_opencli` wraps each browser child in
`systemd-run --user --scope --unit=ks-egress` (serialized — keep
`KORTEX_SEARCH_BROWSER_BUDGET=1` in ad-hoc scoped mode). For the Camoufox
anonymous tier the *gateway itself* must run inside the scope (Camoufox
spawns its own children):

```bash
systemd-run --user --scope --unit=ks-egress -- kortex-search serve
```

**systemd deployment**: the gateway unit keeps the full namespace sandbox
(ProtectSystem=strict etc.) and only *verifies* state (`harden --status`,
non-fatal). The privileged load lives in a **root systemd unit**
(`ks-egress.service`) that applies a **root-owned** ruleset copy from
`/etc/kortex-search/ks-egress.nft`. The gateway's `~/.config/kortex-search/`
ruleset file is a generation artifact only — it must never sit in a root
load path (a NOPASSWD grant on a user-writable ruleset would let any
kbj-uid process — including the browser automation — inject rules into the
nf_tables kernel surface; the old sudoers-drop-in design was retired for
this reason). One-time setup:

```bash
kortex-search harden --install --for kortex-search@8765.service   # write rules + state
sudo install -d -m0755 /etc/kortex-search
sudo install -m0644 ~/.config/kortex-search/ks-egress.nft /etc/kortex-search/
sudo cp infra/systemd/ks-egress.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ks-egress.service   # nft -c validates, then applies
kortex-search harden --mark-installed           # the receipt `status` reads
```

nft rules are volatile (they do NOT survive reboot) — the root unit is what
makes the floor survive reboots. If the gateway unit's name/port changes,
re-run the generation + copy steps (the ruleset targets that unit's cgroup).
Uninstall: `sudo systemctl disable --now ks-egress.service`,
`sudo rm /etc/kortex-search/ks-egress.nft`,
`kortex-search harden --uninstall`. Sandboxed CI that cannot run nft sets
`KORTEX_SEARCH_HARDEN=permissive` — the explicit opt-out, not the default.

## 4. Headless tier-1 image (CI / academic-only)

```bash
docker build -f infra/Dockerfile -t kortex-search .
docker run --rm -p 8765:8765 kortex-search
```

No models, no browser CLIs — the "minimal" tier only. **Not yet validated:** the
GitHub-hosted CI run and the Docker image build (they run in CI on push; see
`.github/workflows/ci.yml`).

## 5. External dependencies (machine-level)

| Dep | Default | Override |
|-----|---------|----------|
| Redis | `redis://127.0.0.1:6379/0` | `KORTEX_SEARCH_REDIS_URL` |
| SearXNG | `http://127.0.0.1:8888` | `SEARXNG_BASE` |
| DeepSeek | `https://api.deepseek.com` + key | `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` |
| `opencli` + Chromium | social sources | `KORTEX_SEARCH_OPENCLI_PROFILES` |
| `twitter` (twitter-cli) | twitter primary | — |
| `mcporter` | exa + linkedin | — |
| `yt-dlp` | youtube | — |
| `uvx` | linkedin | — |
| HF models (`~/.cache/huggingface`) | reranker · MiniLM · bge-m3 | model env vars + `*_REVISION` |
| arXiv / OpenAlex / Crossref / S2 / StackExchange | HTTP, no key | — |

`agent-reach` is a separate ecosystem: the gateway shells out to its CLIs but
does not bundle it.

## Troubleshooting

```mermaid
flowchart TD
    Start(["something's wrong"]) --> Q1{"kortex-search doctor —<br/>what's not ok?"}
    Q1 -->|"redis.ok = false"| R1["Redis down — see below"]
    Q1 -->|"sources.searxng = down"| R2["SearXNG down — see below"]
    Q1 -->|"rerank/embed .error set"| R3["model load/re-download — see below"]
    Q1 -->|"sources.<name> = down — 429"| R4["source rate-limited — see below"]
    Q1 -->|"everything ok, still slow"| R5["cold model latency — see below"]
```

**Reading `doctor`.** Run `kortex-search doctor` and read top-down: `redis`
and `sources` are the two fields `kortex-search check`'s exit code depends
on (`health.check()` fails if `len(ALL_SOURCES) != 23` or `redis.ok` is
false); `rerank`/`embed`/`llm` are soft signals that degrade the pipeline
without failing it. Since 0.4.1 the report also carries the containment
sections — `egress` (floor state + denial counters), `vault` (hygiene),
`blocks` (block-event reservoir), `profiles` (browser profile farm) — read
`vault.hygiene.ok` and `egress.floor.enabled` when auditing a host.
`stats_report` adds the rolling reliability/latency numbers `doctor` doesn't
carry, plus the same `blocks` reservoir.

**Redis down.** `cache.ping()` catches `redis.RedisError` and returns
`{"ok": false, "error": "<message>"}` — `doctor` surfaces this directly, and
`kortex-search doctor`'s exit code is `0` only when `redis.ok` is true. With
Redis down, `search` still returns results (every `cache.py` call site
catches `RedisError` and treats it as a miss/no-op), but every search pays
full source latency and per-source reliability weighting from `stats.py`
degrades to `1.0` for everyone (no history to read).

**SearXNG down.** Appears as `sources.searxng = "down — <reason>"` in
`doctor`. `search`, `search_web`, `search_news`, and `search_science` all
lose SearXNG's contribution to fusion but still return results from every
other fanned-out source — SearXNG is one of 22 sources, not a dependency of
the pipeline itself.

**Model re-download.** If `rerank.error` or `embed.error` mentions a network
fetch when you expected a cache hit, the pinned `*_REVISION` sha may not
match what's on disk (e.g. after a manual `huggingface-cli` operation).
Clear the affected model from `~/.cache/huggingface` and let
`kortex-search warm` re-fetch it once against the pinned revision — that's
the intended recovery path, not an unpinned override.

**Source 429s.** `doctor`'s `academic.<source>.rate_limited` flag is `true`
when that source's status string contains `"429"` or `"rate"` — check
`stats_report` for that source's `reliability` trend over the last 24h; a
sustained drop is `fusion.py`'s weighted RRF already compensating, and no
action may be needed beyond waiting out the window.

**Warm vs. cold model latency.** A cold process pays the full cross-encoder +
bi-encoder load time on its first `search` call — expect roughly 30 seconds.
`kortex-search warm` (or the systemd unit's warm-keep-alive behavior)
front-loads that cost so it never lands on a live request; `kortex-search
doctor`'s `rerank.loaded`/`embed.loaded` flags confirm whether the warm-up
already happened in this process.

**Redis AOF backup.** `infra/docker-compose.yml` enables Redis AOF, so
`saved_queries` and the reliability counters in `stats.py` survive a
container restart. Back up the AOF file (`appendonly.aof` under the Redis
data volume) before any `docker compose down -v` — that flag deletes volumes,
and an AOF backup is the only way to recover saved queries after it.

## Upgrade path

```bash
pip install -U .                    # or: pip install -U kortex-search (if published)
kortex-search version              # confirm the bump
kortex-search check                # re-verify 23 sources + Redis after upgrade
```

A minor bump (e.g. `0.2.0` → `0.3.0`) may add a tool — re-read
`docs/api/tools.md` for anything new, but nothing existing breaks. A major
bump changes a tool's surface or a `Result` field; read the changelog entry
and `docs/architecture.md#versioning` before upgrading a production
deployment.

Changing a pinned model revision (`KORTEX_SEARCH_RERANK_REVISION`,
`KORTEX_SEARCH_EMBED_REVISION`, `KORTEX_SEARCH_EMBED_CJK_REVISION`) is a
separate, independent upgrade: set the new sha, then run `kortex-search
warm` to force the re-fetch against it rather than waiting for the first live
query to pay that cost. Un-pinning (setting the var to an empty string) is
supported but re-introduces the commit-churn re-download risk
`docs/adrs/0005-pinned-model-revisions.md` exists to prevent.