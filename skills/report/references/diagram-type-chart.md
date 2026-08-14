# Diagram Type Reference — What / Why / How / Where / When

The complete 27-type visual vocabulary from the `diagram-design` skill, with
selection guidance. Use this to pick the right visual for a research report (or
any artifact) before authoring it. Each type has its own draw spec in
`references/type-*.md` (from the `diagram-design` skill); this chart is
the **selection** layer that tells you which one to load.

## How to use this chart

1. Find your intent in the **decision matrix** (below) → it names a type.
2. Read that type's **What / Why / When / Parameters / Report-fit** entry.
3. Load the matching `type-*.md` and author the HTML (never hand-author SVG).

## Canvas + detail dials (apply to every type)

From `diagram-design` `output-spec.md`. Set before drawing.

| Dial | Values | Default | What it controls |
|------|--------|---------|------------------|
| **Format** | html / svg / png | html | deliverable (HTML is source of truth; SVG/PNG derived) |
| **Size** | doc-inline `960×600` · doc-wide `1280×720` · slide-16x9 `1280×720` · slide-4x3 `1024×768` · social-og `1200×632` · print-a4-landscape `1120×792` · fit | doc-inline | canvas + type ramp |
| **Detail** | faithful ≤24 nodes · balanced ≤12 · simplified ≤7 | balanced | how many elements survive |
| **Audience** | engineer / mixed / executive | mixed | what nodes are *called* |

House rules (all types): 4px grid; 40px outer margin; 1–2 focal (`accent`)
nodes max; density ~4/10; above 9 nodes → zone them, above 24 → split.

---

## Decision matrix

| If you need to show… | Use | Type |
|----------------------|-----|------|
| Components + connections in a system | Architecture | `architecture` |
| Legacy landscape grouped by phase (the "before") | IT current-state | `it-state` |
| Decision logic, branches, "should I…?" | Flowchart | `flowchart` |
| Time-ordered messages between actors | Sequence | `sequence` |
| States + transitions + guards | State machine | `state` |
| Entities + fields + relationships | ER / data model | `er` |
| Events positioned in time | Timeline | `timeline` |
| Cross-functional process with handoffs | Swimlane | `swimlane` |
| Two-axis positioning / prioritization | Quadrant | `quadrant` |
| 3–5 entities scored across 3–5 criteria | Radar / Spider | `radar` |
| Reinforcing cycle / flywheel with shared hub | Loop | `loop` |
| Hierarchy through containment / scope | Nested | `nested` |
| Parent → children relationships | Tree | `tree` |
| Ownership / reporting / routing | Org chart | `org-chart` |
| Stacked abstraction levels | Layer stack | `layers` |
| Overlap between sets | Venn | `venn` |
| Ranked hierarchy or conversion drop-off | Pyramid / funnel | `pyramid` |
| Quantitative comparison across categories | Bar chart | `bar` |
| Continuous trend over time | Line chart | `line` |
| Tasks + phases on a timeline | Gantt | `gantt` |
| Correlation / clusters between two variables | Scatter | `scatter` |
| End-to-end data stack on a cluster | High-Level | `high-level` |
| Multi-actor sequential process w/ data handoffs | Process | `process` |
| Multi-tier data storage with quality levels | Medallion | `medallion` |
| Role-scoped data flow (who does what) | Data flow | `data-flow` |
| Integration topology (sources → core → consumers) | DP integration | `dp-integration` |
| Access permissions matrix (who can do what) | DP security matrix | `dp-security-matrix` |

---

# Structure & hierarchy

## Architecture
- **What** — a schematic of components and their connections in a system.
- **Why** — makes topology, integration points, and data movement legible at a glance; the workhorse for system overviews.
- **When/Where** — system overviews, data-flow diagrams, integration maps, infra topology. Report section: methodology or findings when the *system* is the subject.
- **Parameters** — 1–2 focal nodes (the primary integration point/store/decision). **Orthogonal right-angle connectors are mandatory** (no diagonals); quarter-arc bends `r=8`; bridge/hop primitive for crossings; port by direction (top/bottom for vertical, left/right for horizontal). Zone above 9 nodes.

## IT current-state
- **What** — the legacy landscape grouped by phase/department, pain-points flagged, file-based hand-offs labelled.
- **Why** — documents the *before* state so a modernization proposal's gap is visible.
- **When/Where** — modernization proposals, "here's the friction in today's setup". Report: findings (context for a recommendation).
- **Parameters** — components grouped by zone; pain-point flags; hand-off labels (CSV/Excel/Email/Copy); horizontal default, vertical variant. Companion to `dp-integration` (before → after).

## High-Level
- **What** — end-to-end data stack (ingestion → storage → query → analytics → viz) on a container orchestrator.
- **Why** — collapses a full platform into one phase-banded overview with the deployment boundary explicit.
- **When/Where** — "what does the whole platform look like?" one-pager. Report: architecture appendix.
- **Parameters** — phase chevron banner + deployment boundary + orchestration bar + identity footer + optional cross-cutting strip (Orchestration/Security/Observability). Icon set from `assets/icons.html`.

## Nested
- **What** — hierarchy expressed through containment (outer = broader, inner = specific).
- **Why** — containment *is* the meaning; better than arrows for scope/trust boundaries.
- **When/Where** — scope boundaries, trust zones, folder nesting, blast radius, config cascades. Report: scope-of-analysis figure.
- **Parameters** — rect containment, hairline borders, `paper-2` fills; no connector spaghetti.

## Tree
- **What** — parent → children hierarchy as a branched structure.
- **Why** — clean way to show taxonomy, dependency, or decision breakdown when ownership isn't the point.
- **When/Where** — taxonomy, dependency trees, file trees, decision breakdowns, aspect maps. Report: **aspect tree** (root = research question → aspects).
- **Parameters** — nodes `rx=6`, Geist 12px name + optional mono sublabel; width 120–180px; coral on **one** node (root OR critical leaf, not both); **2 widths max**; draw connectors before nodes.

## Org chart
- **What** — hierarchy where nodes are people/teams/roles/agents and edges are ownership/routing.
- **Why** — shows *who owns what*, not just structure; surfaces coverage gaps and escalation paths.
- **When/Where** — team/agent maps, escalation, routing, responsibility audits. Report: rarely (only for team/organization findings).
- **Parameters** — root/front-door top-center; coral on the node receiving ambiguous work; >8 specialists → group under pod nodes.

## Layer stack
- **What** — stacked abstraction levels.
- **Why** — makes "which layer owns which concern" explicit; ideal for abstraction/trust stacking.
- **When/Where** — OSI, CSS cascade, tech stack, memory hierarchy, trust/control layers. Report: methodology (control/governance layers).
- **Parameters** — equal-height horizontal bands, top = highest abstraction; hairline separators.

## ER / data model
- **What** — entities + fields + relationship cardinalities.
- **Why** — the canonical way to pin down a domain's data shape before building.
- **When/Where** — DB schemas, API resource relationships, domain models. Report: rarely (domain-modeling side work).
- **Parameters** — entity boxes with field lists; crow's-foot or label cardinalities; relationships only where they carry info.

---

# Flow & process

## Flowchart
- **What** — decision logic with branches and outcomes.
- **Why** — forces the branch conditions and terminal states to be explicit; the anti-mystery diagram.
- **When/Where** — algorithms, "should I…?" flows, triage trees, routing logic. Report: **research-method flow** or **claim→evidence→source graph** (claims as start nodes, evidence, sources as leaves).
- **Parameters** — shape (diamond = decision) signals type, *not* fill color; one entry + clearly terminal leaves; **orthogonal connectors**; combined fragments for branching (see Sequence).

## Process
- **What** — multi-actor sequential process where each step's input/output payload and responsible team are legible.
- **Why** — richer than Swimlane: shows *who* does *what* with *which data* and *which tool*.
- **When/Where** — responsibility audits, data-quality gate reviews, cross-division handoffs. Report: methodology pipeline (Frame → Map → Seed → Extract → Verify → Synthesize) with per-step inputs/outputs.
- **Parameters** — lanes per actor/role; per-node `in`/`out` chips (payload type); exactly one focal node; 3-letter role badges.

## Swimlane
- **What** — cross-functional process laid across lanes (one per actor).
- **Why** — simplest way to show handoffs between teams when data/tool detail doesn't matter.
- **When/Where** — RACI-style flows, vendor handoffs, multi-team shipping. Report: methodology when roles matter but payloads don't.
- **Parameters** — horizontal or vertical lanes; handoffs cross lane boundaries; keep steps coarse.

## Data flow
- **What** — how data moves across *organizational roles* (who initiates/processes/publishes/consumes) with typed payloads.
- **Why** — answers "who does what at each stage", not just "what components exist".
- **When/Where** — multi-role data pipelines (Admin → Engineers → Scientists → Consumers). Report: findings (data provenance).
- **Parameters** — 4–6 steps, lanes per role, typed payloads (raw files/tables/reports), exactly one focal node; prefer Swimlane for non-data business processes.

## Sequence
- **What** — time-ordered messages between actors (lifelines).
- **Why** — the only diagram that captures *ordering + direction + return values* of an interaction.
- **When/Where** — request/response, protocol exchanges, API traces, incident reconstruction, auth/token refresh. Report: verification trail (who-called-what).
- **Parameters** — dashed stroke + filled marker for return messages; coral on one primary success message; **combined fragment frame** for branching (never free-floating if/else arrows).

## State machine
- **What** — states + transitions + guard conditions.
- **Why** — removes ambiguity about what state something is in and what flips it.
- **When/Where** — order status, auth state, connection lifecycle, job queues. Report: rarely (process-state findings).
- **Parameters** — rounded states, labelled transitions with guard text; one start + explicit terminal state(s); coral on the "interesting" state only.

---

# Time

## Timeline
- **What** — events positioned on a time axis.
- **Why** — makes ordering, gaps, and clustering over time instantly readable.
- **When/Where** — release history, milestones, incident timelines, roadmaps. Report: **evidence-by-year timeline** (when sources/clusters emerged).
- **Parameters** — horizontal or vertical; consistent tick spacing; coral on the pivotal event only; label density low.

## Gantt
- **What** — tasks + phases with start/end dates and dependencies.
- **Why** — shows temporal overlap, parallel tracks, and milestone sequencing at a glance.
- **When/Where** — project plans, roadmaps, phase sequencing. Report: research-run plan / rollout roadmap.
- **Parameters** — tasks grouped into phases; dependency arrows only when essential; milestone markers; don't fake overlap.

---

# Cycles & tiers

## Loop
- **What** — a reinforcing cycle/flywheel where the last step feeds the first and a shared hub accumulates state.
- **Why** — shows the compounding dynamic that a linear process can't; the write-back spokes are the point.
- **When/Where** — flywheels, feedback loops, operating loops, compounding growth. Report: findings (reinforcing dynamics, e.g. "evidence → coverage → confidence → more evidence").
- **Parameters** — **hard budget 5–8 stations + exactly one hub**; one station may be focal; clockwise station order; dashed write-back spokes; remove spokes and it's just a circle (that's the fail mode).

## Medallion
- **What** — multi-tier data storage where each tier is a distinct quality/access level of the *same* dataset.
- **Why** — makes "what each bucket contains, who writes it, with what, and how data is promoted" legible at a glance.
- **When/Where** — data platform storage tiers (raw → cleaned → aggregated → archive). Report: findings (data-quality pipeline).
- **Parameters** — tiers as concentric/layered rings or columns; promotion paths 0–2; per-tier writer/tool/format; quality level explicit per tier.

---

# Positioning & comparison

## Quadrant
- **What** — two-axis positioning/prioritization; four named cells.
- **Why** — forces two independent drivers to be chosen and four options to be placed; classic strategy frame.
- **When/Where** — Impact × Effort prioritization, Reach × Frequency, 2×2 scenario planning, portfolio maps. Report: **confidence × stance** 2×2 (claims mapped by evidence strength vs agreement) — excellent for findings.
- **Parameters** — two labelled orthogonal axes; four named bets (not a point cloud); consultant-special variant for BCG/McKinsey 2×2.

## Radar / Spider
- **What** — 3–5 entities scored across 3–5 quantitative criteria on one normalized scale.
- **Why** — where a comparison table runs out of width, radar makes each option's *shape* legible.
- **When/Where** — capability matrices, product/backend evaluations, scorecards. Report: source-class coverage or method comparison.
- **Parameters** — 3–5 spokes; normalize to a shared 0–N scale; use the series palette (accent = focal series); don't exceed 5 entities (spaghetti).

## Venn
- **What** — overlap between 2–3 sets.
- **Why** — the intersection/union *is* the message ("where A meets B").
- **When/Where** — concept overlap, shared attributes, ikigai frames (desirable × feasible × viable). Report: findings (overlap between source claims or methods).
- **Parameters** — equal radii when sets are comparable, proportional when meaningfully different; circles must actually overlap when overlap is the point.

## Pyramid / Funnel
- **What** — ranked hierarchy (pyramid) or conversion drop-off (funnel).
- **Why** — communicates rank/priority or attrition in one shape.
- **When/Where** — hierarchy of needs, prioritization ranks, value pyramids, conversion funnels. Report: findings (evidence-strength pyramid, e.g. primary → secondary → tertiary).
- **Parameters** — widths decrease linearly base→apex; **honest widths** for real funnel data (proportional to count); label each level.

## Bar / Column
- **What** — quantitative comparison across discrete categories.
- **Why** — the most legible way to compare a single numeric value across categories.
- **When/Where** — sprint velocity, revenue by month, adoption, cohort counts. Report: **source-class distribution**, **evidence-per-claim** (numeric charts — usually matplotlib here).
- **Parameters** — vertical default; horizontal when >8 categories or long labels; sorted unless order is meaningful; zero baseline.

## Line
- **What** — continuous trend over time / sequential index.
- **Why** — direction and rate of change are the message.
- **When/Where** — signups over weeks, latency over releases. Report: **citation-count-over-time** or trend lines.
- **Parameters** — polyline is honest; smooth splines only when data is sampled; dots on every series when 4+; area fill optional for focal series.

## Scatter
- **What** — two continuous variables, correlation/clusters/outliers.
- **Why** — reveals relationships (or their absence) that tables hide.
- **When/Where** — correlation analysis, cluster/outlier identification. Report: **citation_count × year** scatter for a field's shape.
- **Parameters** — no forced trend line when genuinely scattered; zero-inclusion decision by range; label only outliers/anchors.

---

# Data-platform specific (niche, use only when on-topic)

## DP integration
- **What** — a platform's integration topology: which sources plug in, which consumers plug out, and the protocol each speaks (hub-and-spoke).
- **Why** — answers "what surfaces does this platform expose, over what wire?" (topology, not phase flow).
- **When/Where** — data-platform architecture docs. Report: architecture appendix.
- **Parameters** — sources 0–6 (left), consumers 0–6 (right), hub in the middle; protocol labels per edge.

## DP security matrix
- **What** — a grid: components × roles, each cell a permission (Admin/Full/R-W/Read/No access) with a visual category.
- **Why** — audits *who can do what*; the one cell to flag as focal is the critical access rule.
- **When/Where** — security/permissions audits. Report: security findings.
- **Parameters** — rows = components, columns = roles/AD groups; permission color categories; one focal cell; `none_label` for omitted cells.

---

# Report-fit cheat sheet (which types map onto a research report)

| Report need | Type | Notes |
|-------------|------|-------|
| Research method (Frame→…→Synthesize) | **Process** | lanes = stages; chips = in/out (query → results → claims) |
| Claim → evidence → source graph | **Flowchart** | claims → evidence nodes → sources; coral = contested claim |
| Evidence by year | **Timeline** | cluster years; coral = pivotal source |
| Aspect map | **Tree** | root = question, leaves = aspects |
| Confidence × stance of claims | **Quadrant** | axes = evidence strength × agreement |
| Source-class coverage | **Bar** | (matplotlib) |
| Evidence per claim | **Bar** | (matplotlib) |
| Citation-count distribution | **Bar** / **Scatter** | (matplotlib) |
| Reinforcing research loop | **Loop** | flywheel: search → verify → synthesize → refine |
| Before/after (gap analysis) | **IT current-state** + **DP integration** | modernization narratives only |

> **Quantitative charts stay matplotlib** (fast, accurate for real data); the
> structural/editorial diagrams above are authored in `diagram-design` style.
