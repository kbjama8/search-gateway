# Search Gateway — Task Checklist (Phases 2–4)

Drive from `tasks/plan.md`; mark each item done only after its acceptance
criteria are verified at runtime, per `references/definition-of-done.md`.

## Phase 2 — Orchestration Layer (Skills)

- [x] 2.0 Verify `B143KC47/deep-research-skill` ledger pattern (agent-reach).
- [x] 2.1 `deep-research` SKILL.md + README.
- [x] 2.2 `research_ledger.py` stdlib-only CLI.
- [x] 2.3 deep-research references (protocol / source-quality / query-playbook / report-template).
- [x] 2.4 `master-router` skill (SKILL.md + paths.md + routing-table.md + README).
- [x] 2.5 Three end-to-end runs (academic / hybrid / forum).

**Phase 2 acceptance:**
- [x] `research_ledger.py` runs stdlib-only; `init/add-hop/add-evidence/status/lint/export` work; `lint` catches missing evidence.
- [x] Academic run: classify → seed → verify → record → red-team → `lint` passes.
- [x] Hybrid run: `search_web` + `search_social` fan-out, cross-referenced claims, ledger.
- [x] Forum run: Stack Overflow prioritized by `accepted` + `engagement.score`.
- [x] Gateway untouched: `doctor` = 18 sources; `stats_report` + cache populate.

## Phase 3 — Report + Visual Package

- [x] 3.0 Install tooling (pandoc / mmdc / matplotlib / weasyprint / python-docx).
- [x] 3.1 `report` SKILL.md + report-template.md.
- [x] 3.2 `make_report.py`.
- [x] 3.3 `make_charts.py`.
- [x] 3.4 `make_diagrams.py`.
- [x] 3.5 `export.sh`.
- [x] 3.6 End-to-end report run.

**Phase 3 acceptance:**
- [x] Ledger → `report.md` with all 7 sections + `references.bib`.
- [x] `report.md` embeds ≥2 Mermaid diagrams + ≥2 matplotlib charts.
- [x] `export.sh` → PDF + DOCX + HTML; assets bundled + zipped.
- [x] End-to-end deep research + report, zero paid APIs.

## Phase 4 — Hardening & Polish

- [x] 4.1 Claim-level quality scoring (agreement/confidence_derived in `research_ledger.py`).
- [x] 4.2 Longitudinal monitoring / saved queries (gateway `saved_queries` tool + `monitor` skill).
- [x] 4.3 CJK embedding (`BAAI/bge-m3` lazy-load + `cjk_dominant` detection).
- [x] 4.4 Local research memory across runs (`memory-index`/`memory-check`/`memory-dedup`).
- [x] 4.5 Evaluation rubric skill (`research-rubric` → `eval_run.py` 0–100 self-review).
- [x] 4.6 Extend `doctor`/`stats_report` (academic health + ledger health).
- [x] 4.7 Regression guard (pytest: imports + 18 sources + smoke search + Phase-4 features).

## Cross-cutting

- [x] Register `deep-research`, `master-router` in AGENTS.md catalog + intent map.
- [x] Register `report` in AGENTS.md catalog.
- [x] Register `diagram-design`, `monitor`, `research-rubric` in AGENTS.md.
- [x] Update gateway README + `references/search-gateway.md` for `saved_queries`, CJK embed, ledger health.
- [ ] Update `docs/meta-schema.md` if any `Result.meta` / tool-surface change lands. (none needed — no `Result.meta` changes)
