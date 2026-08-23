# Next-Session Kickoff Prompt

Copy-paste the block below as the first message of the next session. It is
written for a fresh-context agent; everything it references lives in this
repo.

---

```
Phase 7 handoff execution. You are picking up the search-gateway project
(Project Gatekeeper) at a defined checkpoint — do not explore from scratch.

FIRST, read these three files in order and internalize them:
1. docs/extraction/PHASE7-HANDOFF.md   — the handoff: state, research,
   locked decisions D7.1-D7.4, release specs, checklist
2. docs/extraction/PLAN.md             — the assignment + status board
3. docs/extraction/LESSONS.md          — the research journal + doctrine

Then execute Phase 7 exactly as the handoff specifies, in this order:

STEP 0 — Fold the Phase 7 research findings (§3 of the handoff) into
LESSONS.md and close parking-lot items R8/R13-R16. Update the PLAN status
board at the end of each release.

STEP 1 — Release 0.4.1 (zero-risk): L1 egress floor
(search_gateway/extract/egress.py) with tests/test_egress.py; secrets vault
(search_gateway/extract/vault.py) with FULL migration per D7.3 +
tests/test_vault.py; block-event telemetry in stats.py + the four new
doctor sections (egress/vault/blocks/profiles). Config → 79 vars.
Bump to 0.4.1, CHANGELOG, sync every affected doc in the SAME commit
(config-reference, security, deployment, api/tools, project-map, README,
.env.example). Verify: pytest -m "not slow" green, ruff clean, coverage
gate ≥85%, crg graph refresh. Commit (conventional style, e.g. "feat:
containment floor + vault + telemetry (v0.4.1)") and push.

STEP 2 — Release 0.4.2 (sharp end): L2 forced-proxy egress for anonymous
engines only (D7.2) with Camoufox launch flags; L3 kernel filter
(search_gateway/extract/harden.py + `search-gateway harden` CLI) with
MANDATORY enforcement per D7.1 (browser-tier ops fail with the explicit
"egress-unhardened" message until installed) + tests/test_harden_rules.py
(pure-function ruleset golden test, mocked nft — no kernel in CI);
bench.py browser tier (slow-marked); hardened systemd unit + deployment
walkthrough. Bump to 0.4.2, CHANGELOG, docs in the same commit. Verify
as above, commit, push. Update PLAN status board; leave the working tree
clean.

DOCTRINE (non-negotiable, from the repo's own docs):
- Public-content research only; no credential abuse, no captcha-solving.
- Everything risky is env-gated, default OFF unless the handoff says
  otherwise (EGRESS_FLOOR is ON by design; HARDEN is required-by-default).
- Degrade explicitly, never silently — the envelope names every state.
- Contract-tested: any tool/source/envelope change updates
  tests/test_contract.py in the same commit.
- Decisions D7.1-D7.4 are LOCKED — do not re-ask.
- Machine facts: Redis is password-protected; tests get credentials from
  ~/.agent-reach/gateway.env via tests/conftest.py — do not delete it.
  If the search-gateway MCP channel is down, research via
  `mcporter call exa.web_search_exa query="..."` or
  `curl -s https://r.jina.ai/<url>` — never invent tools.
- Follow the workspace's skill discipline (spec/plan/build/test chains),
  and update docs/extraction/PLAN.md + LESSONS.md as you go, not at the end.
- Commit messages match repo history (conventional commits; the last
  feature commit was "feat: Project Gatekeeper extraction overhaul
  (v0.4.0)").

Start with STEP 0 and report your plan briefly before building.
```

---

If you want it tighter, the 3-line essence is:

```
Read docs/extraction/PHASE7-HANDOFF.md, PLAN.md, LESSONS.md first.
Execute Phase 7 per the handoff: 0.4.1 (floor+vault+telemetry) then
0.4.2 (L2/L3+bench+hardened unit), each verified (pytest, ruff,
coverage ≥85%), committed and pushed, docs synced in the same commit.
Decisions D7.1–D7.4 are locked; do not re-ask.
```
