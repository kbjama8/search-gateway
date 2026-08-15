# Security & Threat Model

This is a local, best-effort MCP server — not a sandbox, not a network service
by default. The trust boundary is small, and drawing it keeps the mitigations
honest:

```mermaid
flowchart LR
    subgraph Trusted["trusted — you + localhost"]
        C["your MCP client"]
        GW["search-gateway"]
        RD[("Redis")]
        SX["SearXNG"]
    end
    subgraph Untrusted["untrusted — the internet"]
        WEB["fetched content · arbitrary URLs (read_url)"]
        API["arXiv · OpenAlex · Crossref · S2 · DeepSeek"]
        CL["CLIs + browser sessions (opencli · twitter)"]
    end
    C --> GW
    GW --> RD
    GW --> SX
    GW --> WEB
    GW --> API
    GW --> CL
```

The server fetches from the untrusted side at your request, synthesizes with
DeepSeek, and never exposes a secret to it. The mitigations below are the
specifics.

| Threat | Mitigation |
|--------|-----------|
| Untrusted fetched content → DeepSeek (prompt injection) | `research_answer` prompt is scoped "use ONLY the numbered sources"; synthesis refuses out-of-scope. Best-effort, **not** a sandbox. |
| Social auth tokens in subprocess env (`TWITTER_AUTH_TOKEN` / `CT0`) | child-process env only, never logged; `.gitignore` blocks `*.env`; `doctor`/`check` never echo secrets. |
| Model download supply chain | pinned `*_REVISION` (empty = unpinned) fixes commit-churn re-downloads and pins provenance. |
| `read_url` fetching arbitrary URLs (SSRF) | local, user-initiated tool; no secret-bearing reach beyond the user's own request. |
| Secret leakage via logs | logs go to stderr with `SEARCH_GATEWAY_LOG_FMT`; JSON formatter never serializes env/tokens. |
| Saved-query loss on Redis reset | Redis AOF enabled in `infra/docker-compose.yml`; backup documented in `docs/deployment.md`. |

## Per-tool attack surface

Not every tool touches the untrusted side the same way — this walks the 14
tools by what they actually reach, so "is this tool safe to expose" has a
concrete answer instead of a blanket one.

| Tool | Reaches | Attack surface |
|------|---------|-----------------|
| `search` / `search_web` / `search_news` / `search_science` / `search_academic` / `search_social` | up to 18 third-party APIs/CLIs, chosen by the caller via `sources` | The caller picks the source list — no privilege escalation, since every source is already reachable via `ALL_SOURCES`; the risk is purely upstream (a compromised or malicious search backend returning adversarial content), not a gateway-side vulnerability. |
| `get_paper` / `get_citations` / `get_references` | Crossref, OpenAlex, arXiv, Semantic Scholar | Same shape as search — read-only, keyless HTTP APIs. `GITHUB_TOKEN`, the only credential these paths could brush against indirectly, is never passed to non-GitHub sources. |
| `research_answer` | search sources + DeepSeek | The one place untrusted fetched content reaches an LLM. The prompt's scoping line ("use ONLY the numbered sources… if the sources don't answer it, say so") is the only mitigation — this is prompt-level, not sandboxed, so a sufficiently adversarial page in the result set could still attempt injection. Treat `research_answer` output as advisory, not as ground truth to act on unreviewed. |
| `read_url` | any URL the caller passes | The most direct untrusted-content path in the surface: fetches an arbitrary URL as Markdown via Jina Reader and returns the raw text. It is a **local, user-initiated fetch** — there's no server-side credential it could exfiltrate, since the fetch happens with no auth header of the gateway's. The realistic risk is fetching something the user didn't intend to (SSRF-style if the URL came from an untrusted upstream source rather than the user directly). |
| `doctor` / `stats_report` | Redis, all 18 sources' `available()` probes, the ledger directory | Read-only introspection. Status strings never include secret values — `health.report()` returns `"ok"`/`"down — <reason>"` strings, not raw exception payloads containing credentials. |
| `saved_queries` | Redis only, plus whatever `run`/`diff` re-triggers through `orchestrator.search()` | `save`/`list`/`delete` never leave Redis. `run`/`diff` inherit the same attack surface as `search` itself, scoped to whatever `sources` was saved with. |

The pattern across all 14: nothing in this server holds a secret that a tool
call can leak, because the two places secrets exist —
`DEEPSEEK_API_KEY`/`GITHUB_TOKEN`/social auth env — are read once into memory
and passed only as outbound `Authorization` headers to their own API, never
echoed back into a tool's return value.

## Hardening checklist

- **Pre-push secret scan.** Run a secret scanner (e.g. `gitleaks`,
  `detect-secrets`) before every push — `.gitignore` blocking `*.env` prevents
  accidental commits, but doesn't catch a secret pasted into a commit message
  or a debug print left in a diff.
- **Token rotation.** Rotate `DEEPSEEK_API_KEY`, `GITHUB_TOKEN`, and the
  social auth tokens in `~/.agent-reach/*.env` on a fixed schedule, not just
  after a suspected leak — cookie-based social auth in particular has a
  shorter natural expiry, and a stale token failing silently is a worse
  failure mode than a rotation reminder.
- **Minimal permissions.** `GITHUB_TOKEN` needs read-only public-repo scope
  for the GitHub source's rate-limit boost — nothing here needs write access
  to anything. Scope it down explicitly rather than reusing a broader
  personal token.
- **`LOG_FMT` in production.** Set `SEARCH_GATEWAY_LOG_FMT=json` for any
  host-process deployment (`docs/deployment.md`'s HTTP/systemd path) — one
  JSON object per line is what makes `journalctl`/log-aggregation queries
  possible; the `text` default is for interactive/local use only.
- **Review `research_answer` output before acting on it.** Given the prompt
  injection surface above, treat its `answer` field as a summary to verify
  against `results[]`, not as a pre-validated fact — the tool's own
  scoping instruction is the only defense, and it's a best-effort prompt
  constraint, not a guarantee.

## Secret handling

- Secrets live in `~/.agent-reach/*.env` (0600) — outside the repo.
- `.env.example` ships placeholders only; `.gitignore` blocks `.env`, `*.env`,
  `*.pem`, `*.key`, `*.log`.
- The systemd unit reads `~/.config/search-gateway/gateway.env` (0600) via
  `EnvironmentFile=` — that file is never committed.
- `log.py`'s `JsonFormatter` constructs its payload from exactly five fields
  (`ts`, `level`, `logger`, `msg`, `exc`) — it does not serialize arbitrary
  record attributes, so an accidental `logger.info(os.environ)` call would
  still leak via `msg`, but there is no broad-serialization path that could
  leak a secret passed as a *keyword* logging argument.