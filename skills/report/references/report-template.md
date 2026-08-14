# Report Template — Section by Section

The authoritative structure for `make_report.py`. Seven required sections plus
a generated visualizations block. Keep section headings stable — the report
generator and export pipeline target them.

## 1. Executive summary

≤1 page. State the answer first. Include confidence and the most important
uncertainty. Reference evidence IDs (`[E1]`, `[E2]`) for high-impact claims.

## 2. Research question, scope, and methodology

- Question (restated)
- Deliverable
- Effort level (`quick` / `standard` / `deep` / `exhaustive`)
- Aspects mapped
- Paths / gateway tools used
- Hop modes used
- Method: Frame → Map → Seed → Extract → Verify → Synthesize

## 3. Evidence table

| claim | evidence IDs | confidence | stance | key sources |
|-------|--------------|------------|--------|-------------|

## 4. Key findings

One subsection per claim:

- **Claim:** `C#`
- **Evidence:** `E#` (each with title + locator + stance + quality)
- **Confidence:** high / med / low
- **Stance:** supported / contested / unresolved
- **Uncertainty:** none / single-source / weak / stale / contested / unknown

## 5. Counter-evidence and limitations

From the ledger's `counter_evidence` (derived from `stance=contradicts`). A
report with no counter-evidence should say so explicitly — a missing red-team
pass is a gap, not a clean result.

## 6. Recommendations / next actions

From unresolved `next_questions` in the hops + open claims. Calibrate: label
recommendations as action items, not findings.

## 7. Bibliography

Two forms:

1. **BibTeX** — `references.bib`, keyed `lastnameYear` (`@article` for papers,
   `@misc` otherwise).
2. **Human-readable list** — authors, year, venue, DOI/arXiv, citation count,
   `is_oa`, `pdf_url`.

## Visualizations (embedded by the generator)

- Mermaid (fenced ` ```mermaid ` blocks in `report.md`; `.svg`/`.png` renders in
  the export): process flow, claim→evidence→source graph, timeline, mind map.
- matplotlib (PNG images): source-class distribution, evidence-per-claim, year
  distribution, citation histogram.

## Claim language

- `shows` — the source directly demonstrates the claim.
- `suggests` — evidence is partial or context-dependent.
- `claims` — reporting what a source says without endorsing it.
- `likely` — multiple signals align but direct proof is incomplete.
- `unknown` — searched evidence does not settle the point.
