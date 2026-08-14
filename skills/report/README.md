# Report Skill

Produces a structured, cited report from a completed deep-research ledger, with
Opus-tier prose in an ENTP × INTJ synthesis, editorial diagrams (diagram-design,
not Mermaid), and Markdown/PDF/DOCX/HTML export.

## Layout

```
report/
├── SKILL.md                      # workflow + structure + voice + diagrams
├── scripts/
│   ├── make_report.py            # ledger + results → report.md (7 sections) + references.bib
│   ├── make_charts.py            # matplotlib charts from ledger/evidence
│   ├── export_diagram.py         # diagram-design HTML → .svg + .png (Playwright)
│   └── export.sh                 # pandoc / WeasyPrint pipeline + bundle + zip
└── references/
    ├── report-template.md        # section-by-section template
    ├── voice-card.md             # Opus-tier ENTP × INTJ prose contract + worked example
    └── diagram-type-chart.md     # all 27 diagram types: what/why/how/where/when
```

## One-liner

```bash
bash "$SKILL_DIR/scripts/export.sh" \   # $SKILL_DIR = this skill's dir
  --run-dir <run-dir> [--results <results.json>]
```

## The three layers

| Layer | Source | Notes |
|-------|--------|-------|
| **Prose** | agent-authored (voice-card) | exec summary, key findings, recommendations |
| **Data** | `make_report.py` | evidence table, counter-evidence, bibliography (deterministic) |
| **Visuals** | `make_charts.py` (matplotlib) + `diagram-design` skill (editorial) | charts + diagrams |

## Tooling (all local/free)

| Tool | Role |
|------|------|
| `make_report.py` | stdlib-only; 7-section `report.md` + `references.bib`, prose markers |
| `make_charts.py` | matplotlib (Agg) → PNG charts |
| `export_diagram.py` | diagram-design HTML → standalone SVG + transparent PNG (Playwright) |
| `export.sh` | pandoc (HTML/DOCX) + WeasyPrint (PDF) + zip bundle |

## Relationship to the rest of the backbone

- `master-router` classifies the request and decides ledger vs quick answer.
- `deep-research` builds the ledger (evidence, claims, red-team pass, lint).
- `diagram-design` supplies the editorial visual vocabulary (27 types).
- `report` consumes the finished ledger + final results → prose + visuals +
  deliverable bundle.
