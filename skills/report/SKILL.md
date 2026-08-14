---
name: report
description: >
  Use when producing a structured, cited report from a completed deep-research
  ledger — the user asks for a full report, deliverable, write-up, or literature
  review of research findings. Generates a 7-section report with editorial
  diagrams (diagram-design style) and matplotlib charts, plus BibTeX and
  Markdown/PDF/DOCX/HTML export. Use only after a deep-research run has a ledger
  that passes `lint`; never before evidence is recorded.
---

# Report

Turn a completed deep-research ledger into a report with **Opus-tier prose in
an ENTP × INTJ synthesis for research & learning**, editorial diagrams (not
Mermaid), and multi-format export. The narrative sections are authored in the
voice-card register; the data sections (evidence table, counter-evidence,
bibliography) stay deterministic. `report.md` (Markdown) is the source of truth
and primary deliverable.

## Prerequisites

- A `ledger.json` from the `deep-research` skill; `research_ledger.py lint`
  passes (no hard errors).
- Optional `results.json` — the final ranked `search_*` output (enriches the
  bibliography with `authors`, `venue`, `citation_count`, `is_oa`, `pdf_url`).
- The `diagram-design` skill installed (for the editorial diagrams).

## Workflow

1. **Charts** — `make_charts.py` writes matplotlib PNGs (`assets/*.png`).
2. **Diagrams** — author the editorial diagrams with the `diagram-design` skill
   (see below), saving each as `assets/<slug>.html`, then rasterize with
   `export_diagram.py` (→ `.svg` + `.png`).
3. **Assemble** — `make_report.py` generates `report.md` (7 sections, evidence
   table, bibliography, embedded visuals) with `<!-- PROSE -->` markers at the
   three narrative sections.
4. **Write prose** — rewrite the executive summary, key findings, and
   recommendations in the voice-card register ([references/voice-card.md]).
   Keep the structured data under each finding as the auditable spine.
5. **Self-review** — score the run with the `research-rubric` skill and append
   the `--md` output as a `## Self-review` section (before the bibliography).
6. **Export** — `export.sh` bundles `report.{md,html,pdf,docx}` + `assets/` +
   `references.bib` + ledger into `deliverable/` and zips it.

```bash
R="$SKILL_DIR/scripts"   # $SKILL_DIR = this skill's dir
python3 "$R/make_charts.py" --run-dir <run-dir> [--results <results.json>]
python3 "$R/export_diagram.py" <run-dir>/assets/method.html
python3 "$R/make_report.py" --run-dir <run-dir> [--results <results.json>]
# … author prose into report.md …
bash "$R/export.sh" --run-dir <run-dir> [--results <results.json>]
```

## Report structure (7 sections)

Load [references/report-template.md](references/report-template.md) for the
section-by-section template:

1. Executive summary (≤1 page).
2. Research question, scope, methodology, paths used, effort level.
3. Evidence table (claim | evidence IDs | confidence | stance | key sources).
4. Key findings with explicit uncertainty per finding.
5. Counter-evidence and limitations.
6. Recommendations / next actions.
7. Bibliography — BibTeX (`references.bib`) + human-readable list.

Plus a generated **Visualizations** section.

## Voice

The narrative sections are written in the **voice-card register**
([references/voice-card.md](references/voice-card.md)): Opus-tier prose — a
synthesis of ENTP curiosity and INTJ rigor — sharp, convergent, evidence-anchored,
zero corporate speak, written to make a smart skeptical reader *learn*. Every
load-bearing claim carries its `[E#]`; uncertainty is stated, never hidden.

## Diagrams (diagram-design, not Mermaid)

Author editorial diagrams using the **`diagram-design`** skill — self-contained
HTML + inline SVG, the paper/ink/accent editorial skin, 4px grid, 1–2 focal
nodes. Pick the type with
[references/diagram-type-chart.md](references/diagram-type-chart.md) (the full
27-type what/why/how/where/when reference). The four report-standard diagrams:

| Diagram | Type | Slug |
|---------|------|------|
| Research method (Frame→…→Synthesize) | `process` | `assets/method.html` |
| Claim → evidence → source graph | `flowchart` | `assets/claim-graph.html` |
| Evidence by year | `timeline` | `assets/timeline.html` |
| Aspect map | `tree` | `assets/aspect-tree.html` |

Author each as `assets/<slug>.html`, then `export_diagram.py <html>` produces
`<slug>.svg` + `<slug>.png` (Playwright, transparent bg, @2x). `make_report.py`
embeds the PNGs. Quantitative charts stay matplotlib.

## Gotchas

- Run `lint` first — a report from a ledger with missing evidence misleads even
  if it renders.
- The voice-card prose is the point: don't ship the scaffolded `<!-- PROSE -->`
  sections unrewritten.
- Keep `assets/` next to `report.md` so relative image paths resolve in
  HTML/PDF.
