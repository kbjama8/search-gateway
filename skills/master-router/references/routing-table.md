# Routing Table

Request class → gateway tools, sources, and effort. Sources are gateway
registered names; tools are gateway MCP tools. `ledger_required` is the router's
protocol decision (see `SKILL.md`).

| Class | Gateway tools | Sources | Effort | ledger_required |
|-------|---------------|---------|--------|-----------------|
| Academic | `search_academic`, `get_paper`, `get_citations`, `get_references` | arxiv / openalex / crossref (+ semantic_scholar) | deep | usually |
| Web | `search_web`, `research_answer` | searxng / exa | quick | no |
| Social | `search_social` | twitter / reddit / facebook / instagram | standard | sometimes |
| Forum | `search` (stackoverflow source) + `search_web` | stackoverflow / searxng | standard | sometimes |
| Hybrid | `search` (all) + `search_social` + `research_answer` | fast set + social | deep | usually |
| News | `search_news` | searxng news / exa | quick | no |
| Code | `search` (github) + `read_url` | github / searxng | standard | sometimes |
| Quick-fact | `research_answer` (or a single `search_*`) | fast set | quick | no |

## Source notes

- **fast set** = `searxng, exa, github, youtube, bilibili, v2ex` (the gateway's
  `DEFAULT_SOURCES`).
- **Academic** backbones are OpenAlex + Crossref; arXiv is always OA. Semantic
  Scholar is optional/rate-limited — never load-bearing.
- **Social** browser sources are serialized through one opencli bridge — keep
  them to `search_social` rather than mixing them into `search` unless needed.
- **Forum** ranking prefers Stack Overflow `meta.accepted == true` and higher
  `meta.engagement.score`.

## Effort selection

| Effort | Use when |
|--------|----------|
| quick | single fact, orientation, low stakes |
| standard | normal researched answer, one path, some cross-reference |
| deep | literature review, due diligence, multi-path, contested |
| exhaustive | high-stakes, fast-changing, legal/medical/financial/security |

## Freshness / filtering knobs (apply when relevant)

- `freshness=day|week|month|year` on `search` / `search_web` / `search`.
- `year_from` + `open_access_only` on `search_academic` / `search_science`.
- `category=general|news|science` on `search`.
