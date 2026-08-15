# 0001: stdio is the default transport; HTTP/SSE are opt-in

**Status: Accepted**

## Context

An MCP server needs a transport before it needs anything else — the choice
determines whether a client spawns the server per-session or connects to an
always-running process. `cli.py`'s `serve` subcommand defaults `--transport`
to `stdio` and only reads `--host`/`--port` when `--transport` is `http` or
`sse`; the bare `search-gateway` command (no subcommand) routes to the same
default. Every MCP client — OpenCode, Claude Code, a bespoke script — needs
one conformance check it can run without trusting the other party's
documentation.

## Decision

stdio is the default transport, spawned per-client-session. `http`/`sse` are
available via `search-gateway serve --transport http|sse` for a long-running
host process (`docs/deployment.md`'s systemd path), but the server does not
default to them. The conformance check for *any* client integration is the
raw `initialize` → `tools/list` MCP handshake, not that client's
documentation or config UI — `tests/test_mcp_handshake.py` automates exactly
this against the bare `search-gateway` command.

## Consequences

- Adding client #4, #5, #6 (`docs/mcp-registration.md` covers six today)
  never requires a server-side change — the server doesn't know any client
  exists, by construction.
- stdio's cost is per-spawn cold-model latency unless the client reuses the
  process; HTTP's cost is running and monitoring a long-lived service. Both
  are real trade-offs, not a strictly-better option — `docs/mcp-registration.md#stdio-vs-http-tradeoff`
  has the comparison.
- A client integration bug reported as "the server doesn't work" is, by this
  decision, almost always a `search-gateway check` failure surfaced through
  the client's spawn/connection error — `docs/mcp-registration.md#troubleshooting`
  and `docs/deployment.md#troubleshooting` both start from that assumption.