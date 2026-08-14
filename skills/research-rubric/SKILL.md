---
name: research-rubric
description: >
  Use to score a completed deep-research run — "evaluate my research", "how good
  was that run", "self-review this report", "score the evidence". Produces a
  0–100 score across coverage, contradiction-handling, citation hygiene, and
  uncertainty honesty, plus a Markdown self-review section to append to the
  report. Run after a ledger passes `lint`.
---

# Research Rubric

Score a completed deep-research run and produce a self-review. `scripts/eval_run.py`
reads a ledger and scores four axes (0–25 each, 100 total):

| Axis | What it measures |
|------|------------------|
| **coverage** | source-class diversity + hop depth vs the effort target |
| **contradiction** | red-team pass ran; counter-evidence + contested claims surfaced |
| **citation** | every evidence has `source_id` + locator; no orphan hops; claims backed |
| **uncertainty** | open claims declared; confidence recalibrated by evidence agreement |

Full definitions in [references/rubric.md](references/rubric.md).

## Workflow

1. Ensure the run passes `lint` first (`research_ledger.py lint`).
2. Score it:

```bash
python3 "$SKILL_DIR/scripts/eval_run.py" \   # $SKILL_DIR = this skill's dir
  --run-dir <run-dir> --md
```

3. The `--md` output is a **Self-review** section — append it to `report.md`
   (before the bibliography) so the report ships with its own audit.

## Reading the score

| Total | Verdict | Action |
|-------|---------|--------|
| 80–100 | strong | ship |
| 60–79 | adequate | note the flagged axes, then ship |
| 40–59 | weak | fix the lowest axes before finalizing |
| < 40 | insufficient | treat as a gap, not a finding — re-run research |

## Notes

- The rubric is a *signal*, not a substitute for judgment — read the per-axis
  notes, don't just look at the number.
- The effort→targets mapping mirrors `research_ledger.py`'s `EFFORT_DEFAULTS`;
  if you change one, change the other.
