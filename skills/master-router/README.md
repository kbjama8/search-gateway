# Master Router Skill

Classifies a research/search request, routes it to the right search-gateway
tools and sources at the right effort, and decides between a full ledger-based
`deep-research` run and a quick cited answer.

## Layout

```
master-router/
├── SKILL.md                      # classification + routing + protocol decision
├── references/
│   ├── paths.md                  # per-path protocol definitions
│   └── routing-table.md          # request-class → tools/sources/effort
└── README.md
```

## What it emits

Every route ends in a short plan the agent executes:

```json
{
  "class": "academic",
  "tools": ["search_academic", "get_paper", "get_citations", "get_references"],
  "sources": ["arxiv", "openalex", "crossref"],
  "effort": "deep",
  "ledger_required": true,
  "initial_queries": ["..."],
  "stop_conditions": ["..."]
}
```

## Relationship to deep-research

- **master-router** classifies and decides *what* path and *whether* a ledger is
  needed.
- **deep-research** executes the ledger-based loop (Frame → Map → Seed → Extract
  → Verify → Synthesize) when `ledger_required` is true.
- **report** (Phase 3) consumes the finished ledger + final results to produce a
  structured report with visuals and multi-format export.
