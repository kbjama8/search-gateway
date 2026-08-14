# Path Protocols

Per-class execution protocol. Each path names the gateway tools, the order to
call them, and how it hands off (to `deep-research` if ledger-required, or to a
quick answer).

## Academic

1. Seed: `search_academic(query, year_from?, open_access_only?)` — 2–3 distinct
   seed queries across arxiv/openalex/crossref.
2. Anchor: `get_paper(doi_or_arxiv)` on the 2–3 most relevant hits.
3. Verify: `get_citations(id)` and `get_references(id)` on the anchor papers.
4. Contradict: `search_academic("<topic> limitations OR failure OR criticism")`.
5. Hand off to `deep-research` with a ledger (effort `deep`).

## Web

1. `search_web(query, freshness?)` → top results.
2. `read_url(url)` on official/primary pages to extract claims.
3. `research_answer(query)` for a quick cited synthesis.
4. No ledger — quick answer, unless the user asks for verification or a report.

## Social

1. `search_social(query)` → discussions/sentiment.
2. Cross-reference 2–3 claims against `search_web` for corroboration.
3. Ledger only if the request is evidence-heavy or contested; else quick answer.

## Forum

1. `search(query, sources=["stackoverflow"])` → Q&A.
2. Prioritize `meta.accepted == true` and higher `meta.engagement.score`.
3. `search_web(query)` for context/official docs.
4. `read_url(url)` on the accepted answer + any linked docs.
5. Ledger if multi-step troubleshooting needs auditable claims; else quick.

## Hybrid

1. Fan out `search_web(query)` + `search_social(query)` (parallel).
2. `search(query)` with the fast set for breadth.
3. Cross-reference claims across paths; `read_url` key primary sources.
4. `research_answer(query)` for an initial synthesis.
5. Hand off to `deep-research` with a ledger (effort `deep`).

## News

1. `search_news(query)` → recent coverage.
2. Verify against `search_web` (official source) when the claim is consequential.
3. No ledger — quick answer with a freshness label.

## Code

1. `search(query, sources=["github"])` → repositories/code.
2. `read_url(url)` on README, source files, releases, or issues.
3. `search_web(query)` for library docs/API references.
4. Ledger only for implementation recommendations or due diligence.

## Quick-fact

1. `research_answer(query)` (or a single `search_web`/`search`).
2. Return the answer with citations; no ledger.

## Stop conditions (common)

- high-impact claims have evidence IDs + locators;
- required source classes checked or explicitly ruled out;
- counterevidence searched when the topic is debatable/current/technical;
- remaining gaps labeled, not hidden.
