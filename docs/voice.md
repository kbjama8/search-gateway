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

## Diagrams

Mermaid is the diagram tool for these docs. It renders natively on GitHub,
lives inside the Markdown (versioned with the prose), and needs no export
pipeline — unlike the report skill, which produces standalone editorial
diagrams via `diagram-design` for deliverables. Use Mermaid where a
relationship is clearer drawn than said: pipelines, topologies, sequences,
trust boundaries. Never draw what a sentence already states.
