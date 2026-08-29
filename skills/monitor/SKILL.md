---
name: monitor
description: >
  Use when the user wants to track recurring queries over time — "watch this
  topic", "monitor X for me", "alert me when this changes", "set up a saved
  search". Saves queries via the kortex-search `saved_queries` tool and
  reports what's new, removed, or unchanged between runs. Not for one-off
  searches.
---

# Monitor

Track recurring queries and surface what changed since the last run. All
retrieval goes through the kortex-search `saved_queries` MCP tool; this skill
interprets the deltas and reports them.

## Gateway-first rule

Use the `saved_queries` gateway tool for everything — never a raw platform CLI.
It persists in Redis (the gateway owns Redis), re-runs the query through the
normal fusion/re-rank pipeline, and diffs against the last snapshot.

## Workflow

1. **Save** the recurring queries with a name, optional `sources`, and
   `freshness` (e.g. `freshness="week"` for fast-moving topics):

   ```
   saved_queries(action="save", name="rag-weekly", query="retrieval augmented generation",
                 sources=["searxng","arxiv","openalex"], freshness="month")
   ```

2. **Run** once to establish a baseline:

   ```
   saved_queries(action="run", name="rag-weekly", limit=10)
   ```

3. **Diff** on each check — it returns `{new, removed, unchanged}`:

   ```
   saved_queries(action="diff", name="rag-weekly", limit=10)
   ```

4. **Report** the deltas in plain language: what's new (with titles + URLs),
   what dropped off, and how much stayed the same. Flag anything that changed
   the answer to the original question.

5. **List / delete** to manage the set:

   ```
   saved_queries(action="list")
   saved_queries(action="delete", name="rag-weekly")
   ```

## Interpreting a diff

- **New items** — the topic moved; surface titles + URLs and say how they shift
  the picture.
- **Removed items** — either the source disappeared or ranking changed; note it
  rather than silently dropping.
- **Unchanged high** — the topic is stable; say so, don't manufacture a change.
- **Freshness** — keep the `freshness` filter tight for fast-moving topics so
  diffs reflect recency, not noise.

## Notes

- Saved queries are Redis keys (`ks:sq:*`); they survive until deleted (no TTL
  by design — a recurring query is meant to persist).
- Diffs are identity-based (canonical URL, then title fallback), matching the
  gateway's dedup identity.
