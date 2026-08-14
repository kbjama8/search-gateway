# Search Gateway — Remaining Phases (TODO)

This file tracks Phases 2–4 of the "single retrieval + ranking backbone"
research system. Phase 1 (retrieval extensions) is **complete**; its output is
summarized below for reference. Work incrementally, one phase at a time, and
after each phase demonstrate with a concrete end-to-end example that the
existing pipeline, caching, stats, rate-limit, and failure isolation remain
intact.

## Non-negotiable constraints (reaffirmed every phase)

1. **No competing parallel search MCPs.** All retrieval goes through or
   extends `search-gateway`. New sources subclass `Source` and emit `Result`.
2. **`Result` is the universal contract.** Only optional, backward-compatible
   `meta` fields are added (see `docs/meta-schema.md`).
3. **Skills, not the MCP process.** Multi-hop intelligence, evidence ledgers,
   protocols, and report generation live in Skills
   (`~/.config/opencode/skills/`), never inside the long-lived MCP process.
4. **Zero paid APIs.** Academic sources (arXiv/OpenAlex/Crossref/Semantic
   Scholar/Stack Exchange) are all free. DeepSeek is the only LLM (user key,
   already provisioned). Never introduce a paid search/academic key.
5. **Preserve the existing failure-isolation, caching, stats, rate-limit, and
   concurrency model** of the gateway (unchanged from Phase 1).

---

## Phase 1 — DONE (reference state)

- **18 sources** registered (`arxiv, bilibili, crossref, exa, facebook, github,
  instagram, linkedin, openalex, reddit, searxng, semantic_scholar,
  stackoverflow, twitter, v2ex, web, xiaohongshu, youtube`).
- **13 MCP tools**: `search`, `search_web`, `search_news`, `search_science`,
  `search_academic`, `get_paper`, `get_citations`, `get_references`,
  `search_social`, `research_answer`, `read_url`, `doctor`, `stats_report`.
- **Enriched `Result.meta`** (`docs/meta-schema.md`): `source_type`, `doi`,
  `arxiv_id`, `authors`, `year`, `venue`, `citation_count`, `is_oa`, `pdf_url`,
  `abstract`, `paper_id`, `score_raw`, `engagement`, `accepted`, `tags`, etc.
- **Filters** (`freshness`, `year_from`, `open_access_only`) threaded through
  the orchestrator and both cache tiers (filter-aware cache keys).
- **Pipeline** (unchanged): LLM query expansion → concurrent fan-out
  (`asyncio.wait`) → weighted RRF → 3-layer dedup → cross-encoder re-rank →
  MMR diversity → freshness filter → Redis cache (per-source + final).
- Models: `bge-reranker-v2-m3` (re-rank), `all-MiniLM-L6-v2` (embeddings),
  `deepseek-v4-flash` (LLM, thinking-aware).

---

# Phase 2 — Orchestration Layer (Skills)

Two new OpenCode skills. They call the gateway tools (above) in a controlled
loop. **No new MCP tools are added in this phase** (constraint #1/#3); the
Skills orchestrate what already exists.

## 2.1 Deep Research Skill — `~/.config/opencode/skills/deep-research/`

### Files
```
~/.config/opencode/skills/deep-research/
├── SKILL.md                      # trigger + workflow + tool-calling protocol
├── scripts/
│   └── research_ledger.py        # stdlib-only CLI (JSON ledger)
├── references/
│   ├── research-protocol.md      # Frame→Map→Seed→Extract→Verify→Synthesize
│   ├── source-quality.md         # how to score source quality 1–5
│   ├── query-playbook.md         # per-source-class query patterns
│   └── report-template.md        # (consumed by Phase 3 Report skill)
└── README.md                     # usage + examples
```

### SKILL.md — trigger & description (frontmatter)
- `name: deep-research`
- `description`: "Use when the user asks for a deep/evidence-based research
  run, literature review, due diligence, 'research X thoroughly', 'produce a
  cited report', or any multi-hop investigation. Routes through the
  search-gateway MCP tools and maintains a versioned evidence ledger."
- Body must state the **gateway-first rule**: every retrieval call is an
  `search_*` / `get_paper` / `get_citations` / `get_references` / `read_url`
  gateway tool — never a raw platform CLI.

### research_ledger.py — stdlib-only JSON ledger CLI
Modeled on the `B143KC47/deep-research-skill` pattern (reviewed during Phase 1
research), adapted to our gateway + meta schema. Commands:

| Command | Purpose |
|---------|---------|
| `init --question Q --out-dir D --effort E --deliverable D2` | create run dir + `ledger.json` (schema v1) |
| `add-hop --run-dir D --hop N --mode M --tool-or-source S --query-or-action Q --result-summary R --next-questions NQ` | record a hop (modes: seed/extract/verify/contradict/synthesize) |
| `add-evidence --run-dir D --hop N --source-id S --title T --url U --source-type ST --quality-score Q --stance S --claim C --quote-or-locator L --confidence C` | attach evidence to a claim |
| `add-claim --run-dir D --text T --confidence C` | register a claim |
| `status --run-dir D` | hop budget vs actual, coverage per source-class, open claims |
| `lint --run-dir D` | validate every claim has ≥1 evidence; every evidence has source-id+locator; no orphan hops |
| `export --run-dir D` | emit `ledger.md` (human-readable) next to `ledger.json` |

**Ledger schema (JSON, version 1):**
```json
{
  "schema": 1,
  "run_id": "uuid",
  "question": "…",
  "effort": "deep",
  "deliverable": "…",
  "created_at": "…",
  "aspects": ["…"],                 // from the Map step
  "claims": [{
    "id": "C1", "text": "…", "confidence": "high|med|low",
    "stance_summary": "supported|contested|unresolved",
    "evidence_ids": ["E1","E2"]
  }],
  "evidence": [{
    "id": "E1", "claim_id": "C1", "hop": 2,
    "source_id": "S001", "title": "…", "url": "…",
    "source_type": "paper|post|forum|web|video|repo",
    "doi": null, "arxiv_id": null, "year": 2024,
    "quality_score": 5,              // 1–5
    "stance": "supports|contradicts|context|weak",
    "quote_or_locator": "§3.2 / quote",
    "confidence": "high|med|low"
  }],
  "hops": [{ "n": 1, "mode": "seed", "tool": "search_academic",
             "query": "…", "result_summary": "…", "next_questions": "…" }],
  "counter_evidence": [{ "claim_id": "C1", "text": "…", "evidence_ids": ["E3"] }]
}
```

### Adaptive protocol (references/research-protocol.md)
1. **Frame** — restate question, decision, scope, freshness needs, effort.
2. **Map** — split into aspects, source classes, unknowns → aspect map.
3. **Seed** — several distinct routes before diving deep (`search_academic`,
   `search_web`, `search_social`, `search_science`) → initial source graph.
4. **Extract** — claims, locators, dates, versions, source quality → ledger.
5. **Verify** — `get_citations`/`get_references` for scholarly support;
   seek contradictions, stale facts, independent confirmation → confidence.
6. **Synthesize** — answer with evidence IDs + explicit uncertainty.

### Effort levels (hop budgets + source-class coverage)
| Effort | Hops | Source classes | Use |
|--------|------|----------------|-----|
| `quick` | 2–4 | 1+ | orientation / sanity check |
| `standard` | 5–8 | 3+ | normal researched answer |
| `deep` | 9–14 | 4+ | literature review, due diligence |
| `exhaustive` | 15+ | 5+ | high-stakes / contested |

Hop counts are **planning targets, not quotas** — stop when high-impact claims
are supported and remaining gaps are explicit.

### Counter-evidence / red-team pass (mandatory before readiness)
- For each claim with confidence ≥ "med", run at least one **contradiction
  query** (e.g., `search_academic("…limitations OR failure OR criticism")`,
  `search_web("… opposite view")`) and record `counter_evidence` entries.
- Stance must be able to be `contradicts`; a ledger with zero contradictions is
  a red flag, not a success.

### Readiness gate
Before Phase 3 report generation, the Skill must run `research_ledger.py lint`
and confirm all of: (a) ≥1 evidence per claim, (b) hop budget met or explicitly
exhausted, (c) required source-class coverage met, (d) a red-team pass ran,
(e) open claims are declared, not silently dropped.

## 2.2 Master Router Skill — `~/.config/opencode/skills/master-router/`

### Files
```
~/.config/opencode/skills/master-router/
├── SKILL.md                        # classification + routing + protocols
├── references/
│   ├── paths.md                    # per-path protocol definitions
│   └── routing-table.md            # request-class → tools/sources/effort
└── README.md
```

### Classification (SKILL.md)
Map the user's request to one of: **Academic / Web / Social / Forum / Hybrid /
News / Code / Quick-fact**. Decision rules: academic vocabulary (paper,
literature, citation, survey) → Academic; product/opinion/brand → Hybrid
(web+social); troubleshooting/technical Q → Forum (Stack Overflow + web);
code/implementation → Code (github + web); timeliness → News.

### Routing table (references/routing-table.md)
| Class | Gateway tools | Sources | Effort |
|-------|---------------|---------|--------|
| Academic | `search_academic`, `get_paper`, `get_citations`, `get_references` | arxiv/openalex/crossref (+semantic_scholar) | deep |
| Web | `search_web`, `research_answer` | searxng/exa | quick |
| Social | `search_social` | twitter/reddit/facebook/instagram | standard |
| Forum | `search` (stackoverflow source) + `search_web` | stackoverflow/searxng | standard |
| Hybrid | `search` (all) + `search_social` + `research_answer` | fast set + social | deep |
| News | `search_news` | searxng news/exa | quick |
| Code | `search` (github) + `read_url` | github/searxng | standard |

### Protocol decision
The Router decides **ledger-based deep research vs quick answer**:
- Ledger (full `deep-research` skill) when: multi-hop, evidence-heavy,
  contested, or user says "deep/thorough/report".
- Quick answer (`research_answer` or a single `search_*`) when: single fact,
  low stakes, time-boxed.

### Router output contract
The Router always emits a short plan the agent then executes: `{class, tools,
sources, effort, ledger_required(bool), initial_queries[], stop_conditions}`.

## Phase 2 acceptance criteria
- [ ] `research_ledger.py` runs on stdlib only; `init/add-hop/add-evidence/
      status/lint/export` all work; `lint` catches missing evidence.
- [ ] A "deep academic research on X" run: Router classifies Academic → Skill
      seeds via `search_academic`, verifies via `get_citations`, records
      evidence with DOI/locator/confidence, runs a red-team pass, passes `lint`.
- [ ] A "hybrid social+web product research" run: Router classifies Hybrid →
      fan-out `search_web` + `search_social`, cross-references claims, ledger.
- [ ] A "forum-driven technical investigation" run: Stack Overflow results
      prioritized by `accepted` + `engagement.score`, claims backed by answers.
- [ ] Gateway untouched: `doctor` still 18 sources; `stats_report` and cache
      still populate (skills make ordinary MCP calls only).

---

# Phase 3 — Report + Visual Package

Consumes a completed ledger (Phase 2) + final ranked results, produces a
Claude-tier structured report with local visuals and multi-format export.

## 3.1 Report Skill — `~/.config/opencode/skills/report/`

### Files
```
~/.config/opencode/skills/report/
├── SKILL.md                        # report structure + generation protocol
├── scripts/
│   ├── make_report.py              # ledger + results → report.md (+ BibTeX)
│   ├── make_charts.py              # matplotlib charts from ledger/evidence
│   ├── make_diagrams.py            # emit .mmd sources (mermaid) + render
│   └── export.sh                   # pandoc/WeasyPrint/python-docx pipeline
└── references/
    └── report-template.md          # section-by-section template
```

### Required report structure (SKILL.md / report-template.md)
1. **Executive summary** (≤ 1 page).
2. **Research question, scope, methodology, paths used, effort level.**
3. **Evidence table**: claim | evidence IDs | confidence | stance | key sources.
4. **Key findings** with explicit uncertainty per finding.
5. **Counter-evidence and limitations** (from ledger `counter_evidence`).
6. **Recommendations / next actions.**
7. **Bibliography** — BibTeX (`.bib`) + human-readable list (authors, year,
   venue, DOI/arXiv, citation count, is_oa, pdf_url).

### make_report.py
- stdlib + `pyyaml`/`jinja2`-optional; inputs: `ledger.json` + a `results.json`
  (final ranked `search_*` output, already JSON from the gateway).
- Outputs `report.md` (source of truth) + `references.bib`.
- BibTeX keys from DOI (`lastnameYear`) with `@article`/`@misc` heuristics.

## 3.2 Visuals (all local/free)
| Asset | Tool | Notes |
|-------|------|-------|
| Architecture / process flow | **Mermaid** (`.mmd`) → render via `mmdc` or Kroki | fall back to raw code block if `mmdc` missing |
| Citation/claim graph | Mermaid `flowchart` — claims→evidence→sources | generated from ledger |
| Timeline | Mermaid `gantt`/`timeline` from evidence `year` | |
| Mind map of aspects | Mermaid `mindmap` | from ledger `aspects` |
| Quantitative charts | **matplotlib** (`make_charts.py`) | citation-count histograms, source-class distribution, evidence-per-claim, year distribution |
- Assets saved **next to the ledger** (`<run-dir>/assets/`) and embedded in
  `report.md` via relative image paths + fenced ```mermaid blocks.

## 3.3 Export pipeline (local)
| Target | Tool | Command sketch |
|--------|------|----------------|
| Markdown | (native) | `report.md` |
| PDF | pandoc (→ LaTeX) **or** WeasyPrint | `pandoc report.md -o report.pdf --metadata-file=...` |
| DOCX | pandoc | `pandoc report.md -o report.docx` |
| HTML | pandoc (standalone, embeds mermaid) | `pandoc report.md -s -o report.html` |
- **Bundle**: `<run-dir>/deliverable/` containing report (all formats),
  `references.bib`, `assets/`, `ledger.json`, `ledger.md` → zip it.
- Verify at start of Phase 3 which tools are installed (`pandoc`, `mmdc`,
  `weasyprint`, `python-docx`, `matplotlib`); install what's missing locally
  (never a paid tool).

## Phase 3 acceptance criteria
- [ ] A completed Phase-2 ledger feeds `make_report.py` → `report.md` with all
      7 required sections + `references.bib`.
- [ ] `report.md` embeds ≥2 Mermaid diagrams and ≥2 matplotlib charts (rendered
      or as fenced source).
- [ ] `export.sh` produces PDF, DOCX, and HTML; all assets bundled + zipped.
- [ ] End-to-end: "deep academic research on X with a full report" → routed →
      gateway → ledger → report → bundled deliverable, with zero paid APIs.

---

# Phase 4 — Hardening & Polish

Done later, in priority order. Each item is backward-compatible (no changes to
the `Result` contract or the Skills' tool surface without updating
`docs/meta-schema.md`).

- [ ] **Claim-level quality scoring** — beyond source-level `quality_score`,
      score claims by agreement across independent evidence (e.g., 2+
      independent `supports` → higher confidence; a `contradicts` → demote).
- [ ] **Longitudinal monitoring / saved queries** — persist recurring queries +
      freshness in Redis; a `monitor` tool or skill reports deltas.
- [ ] **Stronger CJK embedding support** — swap `all-MiniLM-L6-v2` for
      `BAAI/bge-m3` (multilingual) for dedup/MMR when bilibili/v2ex/XHS dominate
      a run; keep the current model as the fast default.
- [ ] **Local research memory across runs** — deduplicate evidence by DOI/URL
      across ledgers; surface "you already have evidence for this claim".
- [ ] **Evaluation rubric for completed runs** — a rubric skill scoring a run
      on coverage, contradiction-handling, citation hygiene, uncertainty
      honesty; produces a self-review section.
- [ ] **Extend `doctor` / `stats_report`** — report academic-source health
      (arXiv/OpenAlex/Crossref/S2 latency + rate-limit status) and ledger health
      (run count, open claims, lint status) if ledgers are in a known dir.
- [ ] **Regression guard** — a small test script (or pytest) asserting the
      gateway still imports, all 18 sources register, and a smoke `search`
      returns fused results after any Phase 4 change.

---

# Deliverables checklist

- [ ] Updated gateway code (done in Phase 1; unchanged thereafter).
- [ ] Deep Research Skill (SKILL.md + `research_ledger.py` + protocol docs).
- [ ] Master Router Skill.
- [ ] Report Skill + visual helpers + export scripts.
- [ ] Docs: `Result.meta` schema, path protocols, ledger format, gateway calls.
- [ ] Three end-to-end example runs:
  - [ ] (a) pure academic literature review,
  - [ ] (b) hybrid social + web product research,
  - [ ] (c) forum-driven technical investigation.

# Success criteria (end-to-end)

A user says *"Do a deep academic research on X and produce a full report with
diagrams"* and the system:
1. [ ] Routes correctly (Master Router → Academic),
2. [ ] Uses the new academic sources via the gateway,
3. [ ] Builds a proper evidence ledger with multi-hop verification,
4. [ ] Generates a structured report with embedded Mermaid diagrams + charts,
5. [ ] Exports clean multi-format deliverables,
6. [ ] Never requires a paid search or academic API key.

# Open notes / loose ends

- Skills dir confirmed: `~/.config/opencode/skills/` (standard OpenCode global
  skills location — verify with `customize-opencode` conventions when writing
  SKILL.md frontmatter).
- Ledger format: JSON + stdlib CLI (per constraint; a Markdown export is
  generated, not authoritative).
- Report export stack to verify at Phase 3 start: `pandoc`, `mmdc` (or Kroki),
  `matplotlib`, `weasyprint`/`python-docx`.
- Semantic Scholar and Unpaywall are rate-limited/optional — never load-bearing;
  OpenAlex + Crossref are the primary academic backbones.
