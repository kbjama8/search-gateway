# Report Template

Default structure for a deep-research deliverable. This template is **consumed
by the Phase 3 `report` skill** (`make_report.py` turns `ledger.json` +
`results.json` into `report.md`); keep section names stable so the report
generator can target them.

```markdown
# [Research title]

## Executive summary
[≤1 page. State the answer first. Include confidence and the most important
uncertainty. Use evidence IDs like [E1] for high-impact claims.]

## Research question, scope, and methodology
- Question: [restated]
- Decision / deliverable: [what the user needed]
- Scope: [in / out of scope]
- Freshness requirement: [none / dates matter]
- Effort level: [quick | standard | deep | exhaustive]
- Paths used: [academic / web / social / forum / code / hybrid]
- Method: Frame → Map → Seed → Extract → Verify → Synthesize

## Evidence table
| claim | evidence IDs | confidence | stance | key sources |
|-------|-------------|------------|--------|-------------|
| C1: [text] | [E1], [E2] | high | supported | [title (doi/arxiv)] |

## Key findings
### 1. [Finding]
- Claim: [specific claim] [E1]
- Why it matters: [decision relevance]
- Confidence: high / med / low
- Uncertainty: none / single-source / weak / stale / contested / unknown

### 2. [Finding]
...

## Counter-evidence and limitations
- [Contradiction or limitation, with evidence IDs for each side]
- [Stale or missing evidence]
- [Assumption made]

## Recommendations / next actions
- [Next action or recommended option, with rationale]

## Bibliography
[`references.bib` (BibTeX) + human-readable list: authors, year, venue,
DOI/arXiv, citation count, is_oa, pdf_url]
```

## Claim language

Use calibrated language:

- `shows` — the source directly demonstrates the claim;
- `suggests` — evidence is partial or context-dependent;
- `claims` — reporting what a source says without endorsing it;
- `likely` — multiple signals align but direct proof is incomplete;
- `unknown` — searched evidence does not settle the point.

## Short-answer variant

When the user wants a short answer, still run the ledger internally, then emit:

1. answer first;
2. 3–5 supported findings;
3. one caveat paragraph;
4. compact source list or evidence table.

## Literature-review variant

Add a literature map and open research questions:

```markdown
## Literature map
| cluster | representative papers | core idea | evidence | limitations |
|---------|-----------------------|-----------|----------|-------------|

## Open research questions
[What remains unresolved across the literature]
```
