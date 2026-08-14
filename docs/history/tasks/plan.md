# Implementation Plan: Search Gateway Phases 2–4

## Overview

Phase 1 of the "single retrieval + ranking backbone" system is complete: the
`search-gateway` MCP server fuses 18 sources behind 13 tools and a standardized
`Result`/`Result.meta` contract. This plan operationalizes the remaining work in
`TODO.md` — the orchestration Skills (Phase 2), the report + visual package
(Phase 3), and hardening/polish (Phase 4) — into ordered, verifiable tasks.

Every phase preserves the gateway's existing failure-isolation, caching, stats,
rate-limit, and concurrency model unchanged. Skills (never the long-lived MCP
process) carry the multi-hop intelligence, evidence ledgers, and report
generation. Zero paid APIs: DeepSeek is the only LLM, and all academic sources
are free.

## Architecture Decisions

- **Skills orchestrate, gateway retrieves.** New sources subclass `Source` and
  emit `Result`; the Skills call `search_*` / `get_paper` / `get_citations` /
  `get_references` / `read_url` and never a raw platform CLI.
- **`Result` is the universal contract.** Only optional, backward-compatible
  `meta` fields are added (see `docs/meta-schema.md`); the ledger CLI and report
  scripts consume that contract, not per-source shapes.
- **Ledger is the source of truth between phases.** `research_ledger.py`
  produces a versioned JSON ledger (`schema` 1); `ledger.md` is a generated
  export, never authoritative. The report skill consumes the ledger.
- **Stdlib-first scripts.** `research_ledger.py` is stdlib-only; report scripts
  may add `pyyaml`/`jinja2` (already present) and `matplotlib`.
- **Effort is a planning budget, not a quota.** Hop counts are targets; the
  readiness gate (lint) is the real stop condition.
- **Two new skills + one report skill** under `~/.config/opencode/skills/`,
  registered in the AGENTS.md skill catalog + intent map.

## Task List

### Phase 2: Orchestration Layer (Skills)

- [x] Task 2.0 — Verify the `B143KC47/deep-research-skill` ledger pattern via agent-reach; capture design notes.
- [ ] Task 2.1 — `deep-research` SKILL.md (frontmatter + gateway-first rule + trigger) + README.
- [ ] Task 2.2 — `research_ledger.py` (stdlib-only CLI: init/add-hop/add-evidence/add-claim/status/lint/export).
- [ ] Task 2.3 — `deep-research` references: research-protocol.md, source-quality.md, query-playbook.md, report-template.md.
- [ ] Task 2.4 — `master-router` skill: SKILL.md + paths.md + routing-table.md + README.
- [ ] Task 2.5 — Three end-to-end runs: (a) academic, (b) hybrid social+web, (c) forum investigation.

### Checkpoint: Phase 2
- [ ] `research_ledger.py` stdlib-only; all commands work; `lint` catches missing evidence.
- [ ] Academic run classifies → seeds via `search_academic` → verifies via `get_citations` → records evidence → red-team → passes lint.
- [ ] Hybrid run fans out `search_web` + `search_social`, cross-references claims, ledger.
- [ ] Forum run prioritizes `accepted` + `engagement.score`.
- [ ] Gateway untouched: `doctor` still 18 sources; `stats_report`/cache still populate.

### Phase 3: Report + Visual Package

- [ ] Task 3.0 — Install tooling (pip matplotlib/weasyprint/python-docx; npm mermaid-cli; apt pandoc).
- [ ] Task 3.1 — `report` SKILL.md + report-template.md (7 sections).
- [ ] Task 3.2 — `make_report.py` (ledger.json + results.json → report.md + references.bib).
- [ ] Task 3.3 — `make_charts.py` (matplotlib charts).
- [ ] Task 3.4 — `make_diagrams.py` (mermaid .mmd + render, fallback fenced).
- [ ] Task 3.5 — `export.sh` (markdown/PDF/DOCX/HTML + bundle + zip).
- [ ] Task 3.6 — End-to-end report run.

### Checkpoint: Phase 3
- [ ] Completed ledger feeds `make_report.py` → `report.md` with all 7 sections + `references.bib`.
- [ ] `report.md` embeds ≥2 Mermaid diagrams + ≥2 matplotlib charts.
- [ ] `export.sh` produces PDF, DOCX, HTML; assets bundled + zipped.
- [ ] End-to-end deep research + report with zero paid APIs.

### Phase 4: Hardening & Polish

- [ ] Task 4.1 — Claim-level quality scoring (agreement across independent evidence).
- [ ] Task 4.2 — Longitudinal monitoring / saved queries (Redis + `monitor` report deltas).
- [ ] Task 4.3 — Stronger CJK embedding (`BAAI/bge-m3`) fallback for dedup/MMR.
- [ ] Task 4.4 — Local research memory across runs (dedupe evidence by DOI/URL).
- [ ] Task 4.5 — Evaluation rubric skill (coverage/contradiction/citation hygiene/uncertainty honesty).
- [ ] Task 4.6 — Extend `doctor`/`stats_report` (academic-source + ledger health).
- [ ] Task 4.7 — Regression guard (pytest: imports, 18 sources register, smoke search).

### Checkpoint: Complete
- [ ] All acceptance criteria met.
- [ ] Ready for review.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Phase 4 items touch gateway code and could regress Phase 1 behavior | Med | Keep changes backward-compatible; run the 4.7 regression guard + `doctor` after each. |
| `semantic_scholar` (429) and `linkedin` (blocked) are down | Low | Declared optional/non-load-bearing; OpenAlex + Crossref are the primary backbones. |
| Phase 3 export tools missing | Med | Install all free tools at Phase 3 start; fall back to fenced Mermaid + Markdown-only if a renderer is unavailable. |
| CJK dedup degraded (English-only embed model) | Low | Title-similarity fallback already covers CJK; Phase 4.3 adds bge-m3. |
| Skills not discoverable without AGENTS.md registration | Med | Register each new skill in the catalog + intent map as it lands. |

## Open Questions

- None blocking. Ledger schema v1, routing table, and report structure are fully
  specified in `TODO.md`; the remaining work is faithful implementation + verification.
