#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Score a completed deep-research run on four axes and emit a self-review.

Reads ledger.json (schema v1, from research_ledger.py) and scores:
    coverage (25)        — source-class diversity + hop depth vs effort target
    contradiction (25)   — red-team pass ran; contradictions surfaced
    citation (25)        — every evidence has source_id + locator; no orphans
    uncertainty (25)     — open claims declared; confidence calibrated

Total is 0–100. Emits a JSON summary, and with --md, a Markdown self-review
section suitable for appending to a report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Must match research_ledger.py's EFFORT_DEFAULTS (hop target + source-class target).
EFFORT_TARGETS = {
    "quick":      {"hop_target": 4,  "source_classes": 1},
    "standard":   {"hop_target": 8,  "source_classes": 3},
    "deep":       {"hop_target": 14, "source_classes": 4},
    "exhaustive": {"hop_target": 20, "source_classes": 5},
}


def _load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"no ledger.json at {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid ledger.json: {exc}")


def score_coverage(data: dict, t: dict) -> tuple[int, list[str]]:
    evidence = data.get("evidence", [])
    hops = data.get("hops", [])
    classes = {e.get("source_type") for e in evidence if e.get("source_type")}
    class_target = t["source_classes"]
    hop_target = t["hop_target"]
    class_ratio = min(1.0, len(classes) / class_target) if class_target else 1.0
    hop_ratio = min(1.0, len(hops) / hop_target) if hop_target else 1.0
    score = round(25 * (0.6 * class_ratio + 0.4 * hop_ratio))
    notes = [f"{len(classes)}/{class_target} source classes, {len(hops)}/{hop_target} hops"]
    if class_ratio < 1.0:
        notes.append("source-class coverage below the effort target")
    if hop_ratio < 1.0:
        notes.append("hop depth below the effort target (fine only if gaps are explicit)")
    return score, notes


def score_contradiction(data: dict) -> tuple[int, list[str]]:
    counter = data.get("counter_evidence", [])
    hops = data.get("hops", [])
    contradict_hops = [h for h in hops if h.get("mode") == "contradict"]
    contested_claims = [c for c in data.get("claims", []) if c.get("stance_summary") == "contested"]
    score = 0
    notes = []
    if counter:
        score += 10
        notes.append(f"{len(counter)} counter-evidence entries recorded")
    if contradict_hops:
        score += 10
        notes.append("contradiction query(s) ran (red-team pass)")
    if contested_claims:
        score += 5
        notes.append(f"{len(contested_claims)} contested claim(s) surfaced")
    if not (counter or contradict_hops):
        notes.append("no red-team pass — a ledger with zero contradictions is a red flag")
    return score, notes


def score_citation(data: dict) -> tuple[int, list[str]]:
    evidence = data.get("evidence", [])
    claims = data.get("claims", [])
    hops = data.get("hops", [])
    hop_numbers = {h.get("n") for h in hops}
    missing_locator = sum(1 for e in evidence if not e.get("quote_or_locator"))
    missing_source = sum(1 for e in evidence if not e.get("source_id"))
    orphan = sum(1 for e in evidence if e.get("hop") not in hop_numbers)
    claims_no_ev = sum(1 for c in claims if not c.get("evidence_ids"))
    score = 25
    notes = []
    if missing_locator:
        score -= 5 * min(1, missing_locator)
        notes.append(f"{missing_locator} evidence item(s) missing a locator")
    if missing_source:
        score -= 5 * min(1, missing_source)
        notes.append(f"{missing_source} evidence item(s) missing a source_id")
    if orphan:
        score -= 5 * min(1, orphan)
        notes.append(f"{orphan} orphan evidence item(s) (missing hop)")
    if claims_no_ev:
        score -= 5 * min(1, claims_no_ev)
        notes.append(f"{claims_no_ev} claim(s) with no evidence")
    if not notes:
        notes.append("all evidence has source_id + locator; no orphan hops")
    return max(0, score), notes


def score_uncertainty(data: dict) -> tuple[int, list[str]]:
    claims = data.get("claims", [])
    open_claims = [c for c in claims if not c.get("evidence_ids")]
    score = 25
    notes = []
    if open_claims:
        score -= 5 * min(1, len(open_claims))
        notes.append(f"{len(open_claims)} open claim(s) — declared or silently dropped?")
    # derived vs base confidence: a mismatch means the claim was demoted/promoted
    # by agreement, which is calibration at work — count how many are calibrated.
    calibrated = sum(1 for c in claims if c.get("confidence_derived") and c.get("confidence_derived") != c.get("confidence"))
    if calibrated:
        notes.append(f"{calibrated} claim(s) confidence recalibrated by evidence agreement")
    else:
        notes.append("no claim confidence recalibrated — verify manual confidences against evidence")
    if not notes:
        notes.append("no open claims; uncertainty is clean")
    return score, notes


def evaluate(data: dict) -> dict:
    effort = data.get("effort", "standard")
    t = EFFORT_TARGETS.get(effort, EFFORT_TARGETS["standard"])
    axes = {
        "coverage": score_coverage(data, t),
        "contradiction": score_contradiction(data),
        "citation": score_citation(data),
        "uncertainty": score_uncertainty(data),
    }
    total = sum(v[0] for v in axes.values())
    verdict = ("strong" if total >= 80 else "adequate" if total >= 60
               else "weak" if total >= 40 else "insufficient")
    return {
        "effort": effort,
        "total": total,
        "verdict": verdict,
        "axes": {k: {"score": v[0], "notes": v[1]} for k, v in axes.items()},
    }


def render_md(result: dict, question: str) -> str:
    L = ["## Self-review (research rubric)", ""]
    L.append(f"Score: **{result['total']}/100** ({result['verdict']}) · effort {result['effort']}")
    L.append("")
    L.append("| axis | score | notes |")
    L.append("|------|------:|-------|")
    for axis, v in result["axes"].items():
        L.append(f"| {axis} | {v['score']}/25 | {'; '.join(v['notes'])} |")
    L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="score a deep-research run")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--md", action="store_true", help="also emit a Markdown self-review section")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir).expanduser().resolve()
    data = _load(run_dir / "ledger.json")
    result = evaluate(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.md:
        print("\n--- markdown ---")
        print(render_md(result, data.get("question", "")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
