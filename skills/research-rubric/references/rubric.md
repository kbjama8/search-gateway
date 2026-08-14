# Rubric Definitions

Four axes, each 0–25, summed to a 0–100 total. Each axis is scored against the
ledger's own `effort` (hop + source-class targets), so a `quick` run is not
penalized for not being `exhaustive`.

## Coverage (25)

- Source-class diversity: `len(unique source_types) / source_class_target`.
- Hop depth: `len(hops) / hop_target`.
- Weighted 60/40 (diversity matters more than raw hop count).
- Below-target is a note, not an automatic failure — explicit gaps are allowed.

## Contradiction (25)

- `+10` — counter-evidence recorded (`counter_evidence` non-empty).
- `+10` — a `contradict`-mode hop ran (the red-team pass).
- `+5` — contested claims are surfaced via `stance_summary=contested`.
- Zero across all three is the red flag: a ledger with no contradictions is not
  a clean result, it is an unsearched one.

## Citation (25)

Start at 25, subtract for each defect class present (5 each, capped per class):

- evidence missing `quote_or_locator`;
- evidence missing `source_id`;
- orphan evidence (references a hop that does not exist);
- claim with no evidence.

## Uncertainty (25)

- Subtract for undeclared open claims (claims with no evidence).
- Credit (note, not score) when `confidence_derived != confidence` — evidence
  agreement actually moved a confidence, i.e. the claim was calibrated, not
  asserted.

## Verdicts

| Total | Verdict |
|-------|---------|
| 80–100 | strong |
| 60–79 | adequate |
| 40–59 | weak |
| < 40 | insufficient |
