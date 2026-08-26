---
name: master-router
description: >
  Use when a search or research request arrives and must be classified and
  routed — deciding between academic / web / social / forum / hybrid / news /
  code / quick-fact, choosing the right kortex-search tools and sources, and
  deciding between a full ledger-based deep-research run and a quick cited
  answer. Use before dispatching any non-trivial retrieval so the request goes
  through the correct path at the right effort.
---

# Master Router

Classify a research request, route it to the right kortex-search tools and
sources at the right effort, and decide whether it needs a full ledger-based
deep-research run or a quick answer. The router emits a short plan; it does not
perform the research itself.

## Classification (decision rules)

Map the request to one class using vocabulary and intent:

| Class | Signals |
|-------|---------|
| **Academic** | paper, literature, citation, survey, method, "review the literature", DOI/arXiv |
| **Web** | general lookup, product/company facts, official docs, "what is X", current info |
| **Social** | opinions, sentiment, "what are people saying", brand perception, discussions |
| **Forum** | troubleshooting, "how do I fix X", error messages, Q&A, "best practice" |
| **Hybrid** | product/opinion/brand research needing web **and** social, cross-reference |
| **News** | timeliness, "latest", "this week", announcements, breaking |
| **Code** | implementation, library usage, "how do I do X in code", repo/API |
| **Quick-fact** | single fact, date, definition, low stakes, time-boxed |

Tiebreakers: academic vocabulary → Academic; product/opinion/brand → Hybrid
(web+social); troubleshooting/technical Q → Forum (Stack Overflow + web);
code/implementation → Code (github + web); timeliness → News.

## Routing

Load [references/routing-table.md](references/routing-table.md) for the full
request-class → tools/sources/effort mapping, and
[references/paths.md](references/paths.md) for the per-path protocol.

## Protocol decision: ledger vs quick answer

- **Ledger** (delegate to the `deep-research` skill) when the request is
  multi-hop, evidence-heavy, contested, or the user says "deep/thorough/report/
  literature review/due diligence".
- **Quick answer** (`research_answer` or a single `search_*`) when it's a
  single fact, low stakes, or time-boxed.

## Router output contract

Always emit a short plan before executing, so the path is explicit and
reviewable:

```json
{
  "class": "academic",
  "tools": ["search_academic", "get_paper", "get_citations", "get_references"],
  "sources": ["arxiv", "openalex", "crossref"],
  "effort": "deep",
  "ledger_required": true,
  "initial_queries": ["<seed query 1>", "<seed query 2>"],
  "stop_conditions": ["high-impact claims supported", "counterevidence searched"]
}
```

## Gateway-first rule

Every tool named in the plan is a kortex-search MCP tool. Never route to a raw
platform CLI (`twitter`, `opencli`, `bili`, `yt-dlp`, `gh`, `curl`) — all
retrieval flows through or extends `kortex-search`.
