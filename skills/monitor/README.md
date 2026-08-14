# Monitor Skill

Track recurring queries and report deltas via the search-gateway
`saved_queries` MCP tool.

## Layout

```
monitor/
├── SKILL.md   # workflow + interpretation guidance
└── README.md
```

## What it wraps

The gateway `saved_queries` tool (Redis-backed) — `save`, `list`, `delete`,
`run`, `diff`. This skill is the thin interpretation layer: it saves recurring
queries, diffs them, and reports `{new, removed, unchanged}` in plain language.

## One-liners

```
saved_queries(action="save", name="rag-weekly", query="retrieval augmented generation", freshness="month")
saved_queries(action="diff", name="rag-weekly", limit=10)
```
