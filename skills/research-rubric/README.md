# Research Rubric Skill

Scores a completed deep-research run (0–100) across coverage,
contradiction-handling, citation hygiene, and uncertainty honesty, and emits a
Markdown self-review section.

## Layout

```
research-rubric/
├── SKILL.md            # workflow + score reading
├── scripts/eval_run.py # stdlib scorer (ledger.json → JSON + markdown)
└── references/
    └── rubric.md       # axis definitions
```

## One-liner

```bash
python3 "$SKILL_DIR/scripts/eval_run.py" \   # $SKILL_DIR = this skill's dir
  --run-dir <run-dir> --md
```
