# 0003: fusion weight is each source's rolling 24h success rate

**Status: Accepted**

## Context

Reciprocal Rank Fusion combines ranked lists without needing cross-source
score calibration — `fusion.py`'s docstring states the score formula
directly: `score(doc) = sum over sources s of w_s / (K + rank_s(doc))`. The
open question was what `w_s` should be. A source having a bad day (upstream
outage, expired auth, a rate-limit ban) shouldn't get the same fusion weight
as a source that's healthy — but that determination needs to be automatic,
because nobody is watching 22 sources' health in real time between searches.

## Decision

`w_s` is `stats.reliability(source)` — the rolling 24-hour success rate,
computed as `1.0 - (errors / total)`, floored at `0.05` so a source is never
fully zeroed out even during a total outage (`stats.py`). `WEIGHTED_RRF`
(default on) controls whether this weighting applies; `RRF_K=60` is the
fusion constant. The counters themselves are written by every `_run_one()`
call in `orchestrator.py` via `stats.record()`/`stats.record_error()`, using
a 24-hour Redis key expiry as the rolling window.

## Consequences

- A source with a 60% success rate over the last day contributes
  proportionally less to fusion on every subsequent query, automatically —
  no alerting rule, no manual downgrade, no deploy required to respond to a
  degraded upstream.
- The floor at `0.05` means a fully-down source is never completely excluded
  from fusion if it does happen to return something — a deliberate choice to
  never treat "currently unreliable" as "permanently untrustworthy."
- This makes source reliability a first-class, queryable signal:
  `stats_report()` exposes the same numbers `fusion.py` reads, so `reliability`
  is diagnosable, not just an internal weighting nobody can inspect.