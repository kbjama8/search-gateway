# Voice — how this repo's docs write

Every document here speaks in one of two registers, both descended from the
gateway's own synthesis outputs — the `research_answer` MCP tool (short, cited,
honest) and the report skill's voice-card (long-form, editorial, decisive).
Which one a document uses depends on the job it's doing.

## Reference docs — the tables-and-contracts register

`docs/api/tools.md` · `docs/config-reference.md` · `docs/deployment.md` ·
`docs/mcp-registration.md` · `docs/security.md` · `docs/meta-schema.md`

- **Concise and direct.** State the fact; don't introduce it. No "This section
  covers…", no "It is important to note…".
- **Every load-bearing claim is traceable.** Anchor it inline — the file that
  defines it (`config.py`), the test that proves it
  (`tests/test_mcp_handshake.py`), or the verification that established it
  ("verified: `docker compose config` is valid").
- **Calibrated certainty.** Say `verified` only when something has been
  demonstrated. Use `expected` or `not yet validated` when it hasn't. A hopeful
  default must never read as a proven fact.
- **Gaps are findings, not omissions.** If something isn't verified, say so
  plainly. That is the `research_answer` rule: "if the sources don't answer it,
  say so rather than guessing."

### Worked example

**Before (templated):**

> This section describes the search tool. The search tool is used to perform
> searches. It is important to note that the search tool has several parameters.

**After (in-voice):**

> `search(query, sources?, category, limit, freshness?)` fans out to 18 sources
> and fuses the survivors. `tests/test_contract.py` asserts the surface against
> the live `tools/list`. A source that times out does not fail the request — the
> fan-out keeps whatever completed (`server.py`, `orchestrator.py`).

**Why it works:** the first sentence *is* the signature, not an introduction to
it. "Fuses the survivors" names the actual behavior instead of gesturing at
"search functionality." The test that guards the claim is named inline, not
footnoted. And the timeout behavior — the one fact a reader actually needs
before depending on this tool — is stated as a fact with its file anchors, not
buried in a caveats section at the bottom.

**A second before/after, showing calibrated certainty on a config claim:**

**Before:** "The timeout can be configured with an environment variable."

**After:** "`SEARCH_GATEWAY_TIMEOUT=50` bounds the whole fan-out in seconds
(`config.py`). Lower it when sources hang; raise it for slow verticals."

**Why it works:** the before-sentence is true of every env var in the file and
says nothing — it doesn't even name the variable. The after-sentence gives the
exact default, the exact unit, the file that defines it, and — the part a
reference doc is supposed to supply — the operational reason you'd move it in
either direction.

## Narrative docs — the thesis register

`README.md` · `docs/architecture.md`

- **Open with the interesting claim, and a thesis in the same breath.** The
  first two sentences should make the reader want the third *and* tell them
  where the document is going.
- **Zero filler.** No throat-clearing, no restating the question, no "in
  conclusion". Cut every sentence that isn't earning its place.
- **Concrete over abstract.** Name the number, the module, the file, the
  result — not "the system provides broad functionality".
- **Calibrated verbs.** `shows` (directly demonstrated), `suggests` (partial),
  `likely` (signals align, no proof). Never inflate a `suggests` into a `shows`.
- **A point of view.** The document takes a position and defends it with
  evidence — it does not bury the reader in a neutral inventory.

### Worked example

**Before (throat-clearing):**

> This document describes the architecture of the search gateway. The gateway
> has many components. These components work together to provide search.

**After (in-voice):**

> The gateway's entire design bet is this: the conformance check is the protocol
> handshake, so no client is the source of truth. That is why OpenCode, Claude
> Code, and a bespoke script all see the same 14 tools — and why the server
> never needs to know any of them exist.

**Why it works:** "many components... work together" is true of every piece of
software ever written and therefore says nothing; "the conformance check is the
protocol handshake" is a specific, falsifiable claim about *this* system. The
second sentence doesn't restate the first — it draws the consequence ("that is
why...") and names the three concrete parties (OpenCode, Claude Code, a bespoke
script) the abstract claim would otherwise leave vague.

**A second before/after, showing the difference a number makes:**

**Before:** "The pipeline uses several techniques to improve search quality,
including deduplication and reranking."

**After:** "Weighted RRF fuses 18 sources by their rolling 24-hour success
rate; a cross-encoder then re-ranks the top 30 candidates — never the full
set, to bound CPU latency on a 16 GB host."

**Why it works:** "several techniques... to improve search quality" is a
sentence that could describe almost any search system. Naming the fusion
method, the exact candidate count, the hardware constraint, and *why* the
scope is limited to 30 turns a vague quality claim into a specific, checkable
design decision — which is what a narrative doc is for: not just saying what
exists, but why it was built that way.

## Diagrams

Mermaid is the diagram tool for these docs. It renders natively on GitHub,
lives inside the Markdown (versioned with the prose), and needs no export
pipeline — unlike the report skill, which produces standalone editorial
diagrams via `diagram-design` for deliverables. Use Mermaid where a
relationship is clearer drawn than said: pipelines, topologies, sequences,
trust boundaries. Never draw what a sentence already states.