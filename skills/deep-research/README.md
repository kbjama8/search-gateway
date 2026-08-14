# Deep Research Skill

Adaptive, evidence-backed research orchestration for the KBJ Singular Core
Ecosystem. This skill drives the `search-gateway` MCP tools in a controlled loop
and maintains a versioned JSON evidence ledger, so every claim is auditable and
every source is re-checkable.

## What it does

- Routes every retrieval through the search-gateway (`search_*`, `get_paper`,
  `get_citations`, `get_references`, `read_url`) — never a raw platform CLI.
- Runs an adaptive loop: Frame → Map → Seed → Extract → Verify → Synthesize.
- Maintains `ledger.json` (schema v1) via `scripts/research_ledger.py`
  (stdlib-only), with a mandatory red-team / counter-evidence pass and a lint
  readiness gate before reporting.
- Hands a completed ledger to the Phase 3 `report` skill for report generation.

## Layout

```
deep-research/
├── SKILL.md                    # trigger + gateway-first rule + workflow
├── scripts/research_ledger.py  # stdlib-only JSON ledger CLI
├── references/
│   ├── research-protocol.md    # Frame→Map→Seed→Extract→Verify→Synthesize
│   ├── source-quality.md       # 1–5 source scoring + gateway signals
│   ├── query-playbook.md       # per-source-class query patterns
│   └── report-template.md      # consumed by the Phase 3 report skill
└── README.md
```

## Quick start

```bash
LEDGER="$SKILL_DIR/scripts/research_ledger.py"   # $SKILL_DIR = this skill's dir
python3 "$LEDGER" init --question "Are RAG retrievers a bottleneck?" \
  --out-dir ~/research_runs --effort deep --deliverable "cited report"
```

Then `add-hop` after each retrieval, `add-claim` + `add-evidence` as you extract
from sources, `status` to see budget vs actual, `lint` before reporting, and
`export` for a human-readable `ledger.md`.

## Effort levels

| Effort | Hops | Source classes |
|--------|------|----------------|
| quick | 2–4 | 1+ |
| standard | 5–8 | 3+ |
| deep | 9–14 | 4+ |
| exhaustive | 15+ | 5+ |

Hop budgets are planning targets, not quotas — the lint readiness gate is the
real stop condition.

## Design notes

- **Ledger is JSON, not Markdown** — `ledger.json` is authoritative; `ledger.md`
  is a generated export.
- **Counter-evidence is derived** from evidence with `stance=contradicts` and
  recomputed on every write, so the file is always self-consistent.
- **Secrets are auto-redacted** — the CLI replaces credential-like strings with
  `[REDACTED]` and `lint` flags any it detects.
- Modeled on the `B143KC47/deep-research-skill` pattern, adapted to the
  gateway's `Result.meta` schema (doi/arxiv_id/year/source_type) and its tool
  surface.
