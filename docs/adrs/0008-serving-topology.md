# ADR-0008: MCP Serving Topology — One Persistent Gateway, Event-Loop-Safe Inference

- Status: **accepted** (2026-09-03)
- Decision owner: KBJ
- Related: `docs/faq.md` (stdio vs HTTP), `docs/mcp-registration.md`,
  `infra/systemd/kortex-search@.service`, sweep journal 2026-09-03

## Context

The ecosystem kept hitting two failure modes on the kortex-search MCP:

1. **Crash (`-32000: Connection closed`)** — reproducible with the official
   MCP client: any concurrent traffic (a second search, a ping) while a
   source fan-out ran `mcporter` killed the server process mid-request with a
   *clean* rc=0. Pipe-inode forensics showed the root cause: `run_cmd`
   spawned children with inherited stdio, and the mcporter → npx → exa-MCP-
   server chain is itself an MCP stdio server that *reads its stdin* — the
   same pipe the kortex server reads. It stole client messages; the session
   receive loop starved and unwound; every in-flight call died.

2. **Timeout (`-32001: Request timed out`)** — CPU-bound model work
   (imports, lazy loads, batches) ran synchronously on the asyncio event
   loop (a single measured 16.9s blocking stretch), pushing tool calls past
   the client's request budget, and compounding whenever searches ran
   concurrently.

Agents then fell back to WebFetch / ad-hoc curl hacks (204 webfetch calls
and a /tmp HTTP helper observed in session history), exactly what the
reporting user complained about.

## Decision

1. **Subprocess fd isolation**: every subprocess the server spawns uses
   `stdin=DEVNULL`. Children must never inherit the MCP protocol pipe.
   (`sources/base.py::run_cmd`, `extract/harden.py` probes.)

2. **Off-loop inference**: all encode/rerank work runs on a dedicated
   single-worker `ThreadPoolExecutor` (`kortex_search/inference.py`).
   `max_workers=1` both serializes CPU bursts (memory ceiling) and
   singleflights cold model loads. The event loop stays live: pings,
   cancellations, and other requests are serviced while a batch runs.

3. **End-to-end budget discipline**: `KORTEX_SEARCH_TOTAL_TIMEOUT` (45s),
   `KORTEX_SEARCH_EXPANSION_LLM_TIMEOUT` (12s),
   `KORTEX_SEARCH_ANSWER_LLM_TIMEOUT` (25s) bound every leg; slow LLM legs
   degrade (expansion → no variants; synthesis → explicit timeout answer)
   instead of holding the pipeline.

4. **One persistent gateway for MCP clients**: opencode registers the
   systemd-managed HTTP gateway (single warm process) instead of spawning a
   per-session stdio child. Rationale: per-spawn cold-model cost (imports +
   loads, 10-20s on the first search of *every* session) and model RSS
   duplication across concurrent sessions on a 15GB machine. stdio remains
   the default for direct dev/other clients.

5. **Gateway temp-dir hygiene**: the hardened unit sets
   `TMPDIR=%h/.config/kortex-search/tmp` (inside its ReadWritePaths) —
   `ProtectSystem=strict` made /tmp read-only, which broke optimum's ONNX
   load *and* poisoned torch's artifact registry for every later load in
   the process.

## Consequences

- Client-visible search latency is bounded and honest (partial/pending
  envelope semantics unchanged).
- The stdio transport remains fully supported and now survives concurrent
  traffic; the HTTP gateway is the recommended deployment for interactive
  agent sessions.
- Trade-off accepted: model inference serializes through one worker —
  concurrent searches queue their CPU stages instead of running in
  parallel. Per-request CPU is seconds on warm models; the loop stays
  responsive throughout.
